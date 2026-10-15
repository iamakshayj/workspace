import asyncio
import json
import logging
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import SESSION_COOKIE, active_session_user_id
from .config import get_settings
from .database import (
    CalendarEvent,
    CalendarEventAttendee,
    CommunicationChannel,
    CommunicationChannelMember,
    CommunicationChannelMessage,
    DirectMessage,
    Notification,
    User,
    session_factory,
)
from .identity import as_utc, user_summary
from .realtime import RealtimeBroker, RealtimeEnvelope, RealtimeUnavailableError, realtime_broker


router = APIRouter(prefix="/communications", tags=["communications"])
settings = get_settings()
logger = logging.getLogger("flowforge.communications")
CALL_ROOM_EVENT_TYPES = {
    "call_chat",
    "call_reaction",
    "call_hand",
    "call_caption",
    "call_state",
    "call_recording",
    "call_breakout",
}
CALL_MESSAGE_TYPES = {
    "call_invite", "call_join", "call_signal", "call_leave", "call_decline",
    "call_control", *CALL_ROOM_EVENT_TYPES,
}
CALL_CONTEXT_TYPES = {"direct", "channel", "calendar"}
CALL_SIGNAL_TYPES = {"offer", "answer", "ice"}
COMMUNICATION_MESSAGE_TYPES = CALL_MESSAGE_TYPES | {"typing"}
MAX_SOCKET_MESSAGE_BYTES = 64 * 1024


class CommunicationHub:
    def __init__(self, broker: RealtimeBroker | None = None) -> None:
        self.broker = broker or realtime_broker
        self.clients: dict[str, dict[str, WebSocket]] = {}
        self.socket_connections: dict[int, str] = {}
        self.subscriptions: dict[str, str] = {}
        self.lock = asyncio.Lock()

    async def connect(self, user_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        connection_id = str(uuid4())
        try:
            async with self.lock:
                first_local_connection = not self.clients.get(user_id)
                self.clients.setdefault(user_id, {})[connection_id] = websocket
                self.socket_connections[id(websocket)] = connection_id
                if first_local_connection:
                    async def receive_event(
                        payload: dict[str, Any],
                        envelope: RealtimeEnvelope,
                    ) -> None:
                        await self._deliver(user_id, payload, envelope)

                    self.subscriptions[user_id] = await self.broker.subscribe(
                        self._topic(user_id),
                        receive_event,
                    )
        except Exception:
            await self._remove_local(user_id, connection_id)
            raise

    async def disconnect(self, user_id: str, websocket: WebSocket) -> None:
        connection_id = self.socket_connections.get(id(websocket))
        if not connection_id:
            return
        await self._remove_local(user_id, connection_id)

    async def _remove_local(self, user_id: str, connection_id: str) -> None:
        subscription = None
        async with self.lock:
            user_clients = self.clients.get(user_id)
            if not user_clients:
                return
            socket = user_clients.pop(connection_id, None)
            if socket:
                self.socket_connections.pop(id(socket), None)
            if not user_clients:
                self.clients.pop(user_id, None)
                subscription = self.subscriptions.pop(user_id, None)
        if subscription:
            await self.broker.unsubscribe(self._topic(user_id), subscription)

    async def publish(self, user_id: str, payload: dict[str, Any]) -> None:
        try:
            await self.broker.publish(self._topic(user_id), payload)
        except RealtimeUnavailableError:
            logger.exception(
                "Realtime delivery failed for user %s; persisted data remains available",
                user_id,
            )

    async def _deliver(
        self,
        user_id: str,
        payload: dict[str, Any],
        _envelope: RealtimeEnvelope,
    ) -> None:
        clients = list(self.clients.get(user_id, {}).items())
        results = await asyncio.gather(
            *(self._send(socket, payload) for _, socket in clients),
            return_exceptions=True,
        )
        for (connection_id, _), delivered in zip(clients, results):
            if delivered is not True:
                await self._remove_local(user_id, connection_id)

    async def _send(self, websocket: WebSocket, payload: dict[str, Any]) -> bool:
        try:
            await websocket.send_json(payload)
        except (RuntimeError, WebSocketDisconnect):
            return False
        return True

    @staticmethod
    def _topic(user_id: str) -> str:
        return f"user:{user_id}"


communication_hub = CommunicationHub()


def serialize_message_metadata(message: DirectMessage | CommunicationChannelMessage) -> dict[str, Any]:
    return {
        "parent_id": message.parent_id,
        "reactions": message.reactions or {},
        "pinned": message.pinned,
        "attachments": message.attachments or [],
        "edited_at": as_utc(message.edited_at).isoformat() if message.edited_at else None,
        "deleted_at": as_utc(message.deleted_at).isoformat() if message.deleted_at else None,
    }


def serialize_direct_message(
    message: DirectMessage,
    sender: User,
    recipient: User,
) -> dict[str, Any]:
    return {
        "id": message.id,
        "body": "" if message.deleted_at else message.body,
        "read": message.read_at is not None,
        "created_at": as_utc(message.created_at).isoformat(),
        "sender": user_summary(sender),
        "recipient": user_summary(recipient),
        **serialize_message_metadata(message),
    }


def serialize_channel_message(
    message: CommunicationChannelMessage,
    sender: User,
) -> dict[str, Any]:
    return {
        "id": message.id,
        "channel_id": message.channel_id,
        "body": "" if message.deleted_at else message.body,
        "created_at": as_utc(message.created_at).isoformat(),
        "sender": user_summary(sender),
        **serialize_message_metadata(message),
    }


def serialize_notification(
    notification: Notification,
    actor: User | None,
) -> dict[str, Any]:
    return {
        "id": notification.id,
        "kind": notification.kind,
        "title": notification.title,
        "body": notification.body,
        "project_id": notification.project_id,
        "contact_id": notification.contact_id,
        "calendar_event_id": notification.calendar_event_id,
        "work_item_id": notification.work_item_id,
        "communication_channel_id": notification.communication_channel_id,
        "communication_message_id": notification.communication_message_id,
        "document_id": notification.document_id,
        "read": notification.read_at is not None,
        "created_at": as_utc(notification.created_at).isoformat(),
        "actor": user_summary(actor) if actor else None,
    }


class CallProtocolError(ValueError):
    pass


def normalized_call_identity(payload: dict[str, Any]) -> tuple[str, str, dict[str, str], str]:
    call_id = str(payload.get("call_id", "")).strip()
    client_id = str(payload.get("client_id", "")).strip()
    media = str(payload.get("media", "video")).strip().lower()
    context = payload.get("context")
    if (
        not 8 <= len(call_id) <= 80
        or not 8 <= len(client_id) <= 80
        or media not in {"audio", "video"}
        or not isinstance(context, dict)
    ):
        raise CallProtocolError("Invalid call details")
    context_kind = str(context.get("kind", "")).strip().lower()
    context_id = str(context.get("id", "")).strip()
    if context_kind not in CALL_CONTEXT_TYPES or not 1 <= len(context_id) <= 80:
        raise CallProtocolError("Invalid call context")
    return call_id, client_id, {"kind": context_kind, "id": context_id}, media


async def call_context_participants(
    session: AsyncSession,
    user: User,
    context: dict[str, str],
) -> list[str]:
    kind, context_id = context["kind"], context["id"]
    if kind == "direct":
        contact = await session.get(User, context_id)
        if not contact or contact.entity_id != user.entity_id or contact.id == user.id:
            raise CallProtocolError("Call conversation not found")
        return [user.id, contact.id]

    if kind == "channel":
        channel = await session.get(CommunicationChannel, context_id)
        if not channel or channel.entity_id != user.entity_id:
            raise CallProtocolError("Call conversation not found")
        if channel.visibility == "private":
            membership = await session.scalar(select(CommunicationChannelMember.id).where(
                CommunicationChannelMember.channel_id == channel.id,
                CommunicationChannelMember.user_id == user.id,
            ))
            if not membership:
                raise CallProtocolError("Call conversation not found")
            return list(await session.scalars(select(CommunicationChannelMember.user_id).where(
                CommunicationChannelMember.channel_id == channel.id,
            )))
        return list(await session.scalars(select(User.id).where(User.entity_id == user.entity_id)))

    event = await session.get(CalendarEvent, context_id)
    if (
        not event
        or event.entity_id != user.entity_id
        or event.event_type != "meeting"
        or event.status != "scheduled"
    ):
        raise CallProtocolError("Meeting not found")
    attendee_ids = list(await session.scalars(select(CalendarEventAttendee.user_id).where(
        CalendarEventAttendee.event_id == event.id,
    )))
    if user.id not in attendee_ids:
        raise CallProtocolError("Meeting not found")
    return attendee_ids


async def handle_call_message(
    session: AsyncSession,
    user: User,
    payload: dict[str, Any],
) -> None:
    message_type = str(payload.get("type", ""))
    if message_type not in CALL_MESSAGE_TYPES:
        raise CallProtocolError("Unsupported communication event")
    call_id, client_id, context, media = normalized_call_identity(payload)
    participant_ids = list(dict.fromkeys(await call_context_participants(session, user, context)))
    event = {
        "type": {
            "call_invite": "call_invite",
            "call_join": "call_participant_joined",
            "call_leave": "call_participant_left",
            "call_decline": "call_declined",
        }.get(message_type, message_type),
        "call_id": call_id,
        "client_id": client_id,
        "context": context,
        "media": media,
        "title": str(payload.get("title", "")).strip()[:160],
        "user": user_summary(user),
    }

    if message_type == "call_signal":
        target_user_id = str(payload.get("target_user_id", ""))
        target_client_id = str(payload.get("target_client_id", ""))
        signal = payload.get("signal")
        if (
            target_user_id == user.id
            or target_user_id not in participant_ids
            or not 8 <= len(target_client_id) <= 80
            or not isinstance(signal, dict)
            or signal.get("kind") not in CALL_SIGNAL_TYPES
            or not isinstance(signal.get("data"), dict)
        ):
            raise CallProtocolError("Invalid call signal")
        event.update({
            "target_user_id": target_user_id,
            "target_client_id": target_client_id,
            "signal": signal,
        })
        await communication_hub.publish(target_user_id, event)
        return

    if message_type == "call_control":
        target_user_id = str(payload.get("target_user_id", ""))
        target_client_id = str(payload.get("target_client_id", ""))
        action = str(payload.get("action", ""))
        if (
            target_user_id == user.id
            or target_user_id not in participant_ids
            or not 8 <= len(target_client_id) <= 80
            or action not in {"mute", "remove"}
        ):
            raise CallProtocolError("Invalid call control")
        event.update({
            "target_user_id": target_user_id,
            "target_client_id": target_client_id,
            "action": action,
        })
        await communication_hub.publish(target_user_id, event)
        return

    if message_type == "call_chat":
        body = str(payload.get("body", "")).strip()
        if not 1 <= len(body) <= 2000:
            raise CallProtocolError("Call messages must be between 1 and 2000 characters")
        event["body"] = body
    elif message_type == "call_reaction":
        emoji = str(payload.get("emoji", "")).strip()
        if not 1 <= len(emoji) <= 16:
            raise CallProtocolError("Invalid call reaction")
        event["emoji"] = emoji
    elif message_type == "call_hand":
        event["raised"] = bool(payload.get("raised"))
    elif message_type == "call_caption":
        caption = str(payload.get("caption", "")).strip()
        if not 1 <= len(caption) <= 5000:
            raise CallProtocolError("Invalid call caption")
        event.update({"caption": caption, "final": bool(payload.get("final", True))})
    elif message_type == "call_state":
        state = payload.get("state")
        if not isinstance(state, dict):
            raise CallProtocolError("Invalid participant state")
        event["state"] = {
            "mic_enabled": bool(state.get("mic_enabled", True)),
            "camera_enabled": bool(state.get("camera_enabled", True)),
            "screen_sharing": bool(state.get("screen_sharing", False)),
        }
    elif message_type == "call_recording":
        recording_state = str(payload.get("recording_state", ""))
        if recording_state not in {"started", "stopped"}:
            raise CallProtocolError("Invalid recording state")
        event["recording_state"] = recording_state
    elif message_type == "call_breakout":
        rooms = payload.get("rooms")
        if not isinstance(rooms, list) or len(rooms) > 20:
            raise CallProtocolError("Invalid breakout rooms")
        normalized_rooms = []
        assigned_users: set[str] = set()
        for room in rooms:
            if not isinstance(room, dict):
                raise CallProtocolError("Invalid breakout rooms")
            name = str(room.get("name", "")).strip()[:80]
            user_ids = [str(value) for value in room.get("user_ids", [])]
            if not name or any(value not in participant_ids for value in user_ids):
                raise CallProtocolError("Invalid breakout rooms")
            assigned_users.update(user_ids)
            normalized_rooms.append({"name": name, "user_ids": list(dict.fromkeys(user_ids))})
        event["rooms"] = normalized_rooms

    if message_type == "call_decline":
        target_user_id = str(payload.get("target_user_id", ""))
        target_client_id = str(payload.get("target_client_id", ""))
        if target_user_id == user.id or target_user_id not in participant_ids:
            raise CallProtocolError("Invalid call recipient")
        if target_client_id:
            event["target_client_id"] = target_client_id
        await communication_hub.publish(target_user_id, event)
        return

    recipients = [participant_id for participant_id in participant_ids if participant_id != user.id]
    await asyncio.gather(*(communication_hub.publish(participant_id, event) for participant_id in recipients))


async def handle_typing_message(session: AsyncSession, user: User, payload: dict[str, Any]) -> None:
    context = payload.get("context")
    if not isinstance(context, dict):
        raise CallProtocolError("Invalid typing context")
    context_kind = str(context.get("kind", ""))
    context_id = str(context.get("id", ""))
    if context_kind not in {"direct", "channel"} or not 1 <= len(context_id) <= 80:
        raise CallProtocolError("Invalid typing context")
    participants = await call_context_participants(
        session, user, {"kind": context_kind, "id": context_id}
    )
    event = {
        "type": "typing",
        "context": {"kind": context_kind, "id": context_id},
        "active": bool(payload.get("active")),
        "user": user_summary(user),
    }
    await asyncio.gather(*(
        communication_hub.publish(user_id, event)
        for user_id in participants if user_id != user.id
    ))


@router.websocket("")
async def communications_socket(websocket: WebSocket) -> None:
    token = websocket.cookies.get(SESSION_COOKIE)
    async with session_factory() as session:
        user_id = await active_session_user_id(token, settings, session) if token else None
        if not user_id:
            await websocket.close(code=4401, reason="Authentication required")
            return
        user = await session.get(User, user_id)
        if not user:
            await websocket.close(code=4401, reason="Authentication required")
            return

    try:
        await communication_hub.connect(user_id, websocket)
    except RealtimeUnavailableError:
        await websocket.close(code=1013, reason="Realtime communications are unavailable")
        return
    try:
        if not await communication_hub._send(websocket, {"type": "ready"}):
            return
        while True:
            raw_message = await websocket.receive_text()
            if len(raw_message.encode("utf-8")) > MAX_SOCKET_MESSAGE_BYTES:
                await communication_hub._send(websocket, {
                    "type": "call_error", "message": "The call update was too large.",
                })
                continue
            payload: dict[str, Any] | None = None
            try:
                payload = json.loads(raw_message)
                if not isinstance(payload, dict):
                    raise CallProtocolError("Invalid communication event")
                async with session_factory() as session:
                    socket_user = await session.get(User, user_id)
                    if not socket_user:
                        await websocket.close(code=4401, reason="Authentication required")
                        return
                    message_type = str(payload.get("type", ""))
                    if message_type not in COMMUNICATION_MESSAGE_TYPES:
                        raise CallProtocolError("Unsupported communication event")
                    if message_type == "typing":
                        await handle_typing_message(session, socket_user, payload)
                    else:
                        await handle_call_message(session, socket_user, payload)
            except (json.JSONDecodeError, CallProtocolError) as error:
                await communication_hub._send(websocket, {
                    "type": "call_error", "message": str(error),
                    "call_id": payload.get("call_id") if payload else None,
                })
    except WebSocketDisconnect:
        pass
    finally:
        await communication_hub.disconnect(user_id, websocket)
