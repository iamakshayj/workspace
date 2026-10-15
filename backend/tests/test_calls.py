import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.app.communications import (
    CallProtocolError,
    call_context_participants,
    handle_call_message,
    handle_typing_message,
)
from backend.app.database import (
    Base,
    CalendarEvent,
    CalendarEventAttendee,
    CommunicationChannel,
    CommunicationChannelMember,
    Entity,
    User,
)


def test_call_rooms_are_scoped_and_signals_are_targeted(monkeypatch) -> None:
    asyncio.run(exercise_call_rooms(monkeypatch))


async def exercise_call_rooms(monkeypatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with sessions() as session:
        entity = Entity(id="entity-1", name="Northwind")
        outsider_entity = Entity(id="entity-2", name="Other")
        owner = User(
            id="user-1", entity_id=entity.id, email="owner@example.com",
            display_name="Owner", password_hash="test", role="admin",
        )
        member = User(
            id="user-2", entity_id=entity.id, email="member@example.com",
            display_name="Member", password_hash="test", role="basic",
        )
        outsider = User(
            id="user-3", entity_id=outsider_entity.id, email="outside@example.com",
            display_name="Outside", password_hash="test", role="basic",
        )
        group = CommunicationChannel(
            id="channel-1", entity_id=entity.id, created_by_id=owner.id,
            name="Launch leads", channel_type="group", visibility="private",
        )
        event = CalendarEvent(
            id="event-1", entity_id=entity.id, organizer_id=owner.id,
            title="Design review", description="", event_type="meeting",
            starts_at=datetime.now(timezone.utc),
            ends_at=datetime.now(timezone.utc) + timedelta(hours=1),
            timezone="UTC", status="scheduled",
        )
        session.add_all([
            entity, outsider_entity, owner, member, outsider, group, event,
            CommunicationChannelMember(channel_id=group.id, user_id=owner.id, role="owner"),
            CommunicationChannelMember(channel_id=group.id, user_id=member.id),
            CalendarEventAttendee(event_id=event.id, user_id=owner.id, response="accepted"),
            CalendarEventAttendee(event_id=event.id, user_id=member.id),
        ])
        await session.commit()

        publish = AsyncMock()
        monkeypatch.setattr("backend.app.communications.communication_hub.publish", publish)
        base = {
            "call_id": "call-12345678", "client_id": "client-12345678", "media": "video",
        }
        await handle_call_message(session, owner, {
            **base, "type": "call_invite", "context": {"kind": "direct", "id": member.id},
        })
        publish.assert_awaited_once()
        recipient_id, invite = publish.await_args.args
        assert recipient_id == member.id
        assert invite["type"] == "call_invite"
        assert invite["user"]["id"] == owner.id

        publish.reset_mock()
        await handle_call_message(session, owner, {
            **base,
            "type": "call_signal",
            "context": {"kind": "calendar", "id": event.id},
            "target_user_id": member.id,
            "target_client_id": "client-87654321",
            "signal": {"kind": "offer", "data": {"type": "offer", "sdp": "test"}},
        })
        publish.assert_awaited_once()
        assert publish.await_args.args[0] == member.id
        assert publish.await_args.args[1]["signal"]["kind"] == "offer"

        publish.reset_mock()
        await handle_call_message(session, owner, {
            **base,
            "type": "call_chat",
            "context": {"kind": "calendar", "id": event.id},
            "body": "Decision: ship after QA signs off",
        })
        publish.assert_awaited_once()
        assert publish.await_args.args[0] == member.id
        assert publish.await_args.args[1]["type"] == "call_chat"
        assert publish.await_args.args[1]["body"].startswith("Decision:")

        publish.reset_mock()
        await handle_call_message(session, owner, {
            **base,
            "type": "call_control",
            "context": {"kind": "calendar", "id": event.id},
            "target_user_id": member.id,
            "target_client_id": "client-87654321",
            "action": "mute",
        })
        publish.assert_awaited_once()
        assert publish.await_args.args[0] == member.id
        assert publish.await_args.args[1]["action"] == "mute"

        with pytest.raises(CallProtocolError, match="Call messages"):
            await handle_call_message(session, owner, {
                **base,
                "type": "call_chat",
                "context": {"kind": "calendar", "id": event.id},
                "body": "",
            })

        publish.reset_mock()
        await handle_typing_message(session, owner, {
            "type": "typing", "active": True,
            "context": {"kind": "channel", "id": group.id},
        })
        publish.assert_awaited_once()
        assert publish.await_args.args[0] == member.id
        assert publish.await_args.args[1]["type"] == "typing"

        assert set(await call_context_participants(
            session, member, {"kind": "channel", "id": group.id},
        )) == {owner.id, member.id}
        with pytest.raises(CallProtocolError, match="not found"):
            await call_context_participants(
                session, outsider, {"kind": "channel", "id": group.id},
            )
        with pytest.raises(CallProtocolError, match="not found"):
            await call_context_participants(
                session, outsider, {"kind": "calendar", "id": event.id},
            )

    await engine.dispose()
