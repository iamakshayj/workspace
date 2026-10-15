import asyncio

from backend.app.collaboration import CollaborationHub, RoomClient
from backend.app.communications import CommunicationHub
from backend.app.realtime import InMemoryRealtimeBus, RealtimeBroker


class RecordingSocket:
    def __init__(self) -> None:
        self.accepted = False
        self.messages: list[dict] = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, payload: dict) -> None:
        self.messages.append(payload)


def test_realtime_brokers_fan_out_events_across_instances() -> None:
    async def scenario() -> None:
        bus = InMemoryRealtimeBus()
        first = RealtimeBroker(None, memory_bus=bus)
        second = RealtimeBroker(None, memory_bus=bus)
        received: list[tuple[str, str | None]] = []

        async def receive(payload, envelope) -> None:
            received.append((payload["type"], envelope.exclude_connection_id))

        await first.start()
        await second.start()
        try:
            await first.subscribe("project:one", receive)
            await second.subscribe("project:one", receive)
            await first.publish(
                "project:one",
                {"type": "document"},
                exclude_connection_id="connection-one",
            )

            assert received == [
                ("document", "connection-one"),
                ("document", "connection-one"),
            ]
            assert await first.is_ready()
            assert await second.is_ready()
        finally:
            await first.stop()
            await second.stop()

        assert not await first.is_ready()
        assert not await second.is_ready()

    asyncio.run(scenario())


def test_presence_is_shared_deduplicated_and_expires() -> None:
    async def scenario() -> None:
        now = [100.0]
        bus = InMemoryRealtimeBus(clock=lambda: now[0])
        first = RealtimeBroker(None, memory_bus=bus, presence_ttl_seconds=15)
        second = RealtimeBroker(None, memory_bus=bus, presence_ttl_seconds=15)
        avery = {"id": "user-1", "display_name": "Avery", "role": "admin"}
        taylor = {"id": "user-2", "display_name": "Taylor", "role": "basic"}

        await first.start()
        await second.start()
        try:
            await first.upsert_presence("project-1", "avery-tab-1", avery)
            await second.upsert_presence("project-1", "avery-tab-2", avery)
            await second.upsert_presence("project-1", "taylor-tab-1", taylor)

            users, pruned = await first.list_presence("project-1")
            assert [user["id"] for user in users] == ["user-1", "user-2"]
            assert pruned is False

            await first.remove_presence("project-1", "avery-tab-1")
            users, _ = await second.list_presence("project-1")
            assert [user["id"] for user in users] == ["user-1", "user-2"]

            now[0] += 16
            users, pruned = await first.list_presence("project-1")
            assert users == []
            assert pruned is True
        finally:
            await first.stop()
            await second.stop()

    asyncio.run(scenario())


def test_collaboration_hubs_share_events_and_presence_across_instances() -> None:
    async def scenario() -> None:
        bus = InMemoryRealtimeBus()
        first_broker = RealtimeBroker(None, memory_bus=bus, presence_ttl_seconds=15)
        second_broker = RealtimeBroker(None, memory_bus=bus, presence_ttl_seconds=15)
        first_hub = CollaborationHub(first_broker)
        second_hub = CollaborationHub(second_broker)
        first_socket = RecordingSocket()
        second_socket = RecordingSocket()
        first_client = RoomClient(
            websocket=first_socket,
            user_id="user-1",
            display_name="Avery Admin",
            role="admin",
            color="#2563eb",
        )
        second_client = RoomClient(
            websocket=second_socket,
            user_id="user-2",
            display_name="Taylor Viewer",
            role="basic",
            color="#7c3aed",
        )

        await first_broker.start()
        await second_broker.start()
        try:
            await first_hub.connect("project-1", first_client)
            await second_hub.connect("project-1", second_client)
            first_socket.messages.clear()
            second_socket.messages.clear()

            await first_hub.broadcast(
                "project-1",
                {"type": "document", "revision": 2},
                exclude=first_socket,
            )

            assert not any(message["type"] == "document" for message in first_socket.messages)
            assert second_socket.messages == [{"type": "document", "revision": 2}]

            second_socket.messages.clear()
            await first_hub.disconnect("project-1", first_socket)

            assert {message["type"] for message in second_socket.messages} == {
                "cursor_removed",
                "presence",
            }
            presence = next(
                message for message in second_socket.messages if message["type"] == "presence"
            )
            assert [user["id"] for user in presence["users"]] == ["user-2"]
        finally:
            await first_hub.disconnect("project-1", first_socket)
            await second_hub.disconnect("project-1", second_socket)
            await first_broker.stop()
            await second_broker.stop()

    asyncio.run(scenario())


def test_personal_events_reach_sockets_owned_by_another_instance() -> None:
    async def scenario() -> None:
        bus = InMemoryRealtimeBus()
        first_broker = RealtimeBroker(None, memory_bus=bus)
        second_broker = RealtimeBroker(None, memory_bus=bus)
        first_hub = CommunicationHub(first_broker)
        second_hub = CommunicationHub(second_broker)
        recipient_socket = RecordingSocket()

        await first_broker.start()
        await second_broker.start()
        try:
            await second_hub.connect("user-2", recipient_socket)
            await first_hub.publish(
                "user-2",
                {"type": "direct_message", "message": {"id": "message-1"}},
            )

            assert recipient_socket.accepted is True
            assert recipient_socket.messages == [
                {"type": "direct_message", "message": {"id": "message-1"}}
            ]
        finally:
            await second_hub.disconnect("user-2", recipient_socket)
            await first_broker.stop()
            await second_broker.stop()

    asyncio.run(scenario())
