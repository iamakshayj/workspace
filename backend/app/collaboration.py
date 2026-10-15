import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
import logging
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from sqlalchemy import select

from .auth import SESSION_COOKIE, active_session_user_id
from .config import get_settings
from .database import (
    Notification,
    Project,
    ProjectDeliverable,
    ProjectNote,
    ProjectTask,
    User,
    session_factory,
)
from .identity import AVATAR_COLORS, as_utc, avatar_color, user_handle, user_summary
from .communications import communication_hub, serialize_notification
from .governance import can_edit_project, project_access_role
from .realtime import RealtimeBroker, RealtimeEnvelope, RealtimeUnavailableError, realtime_broker
from .schemas import ProjectWrite


router = APIRouter(prefix="/collaboration", tags=["collaboration"])
settings = get_settings()
logger = logging.getLogger("flowforge.collaboration")


@dataclass
class RoomClient:
    websocket: WebSocket
    user_id: str
    display_name: str
    role: str
    color: str
    connection_id: str = field(default_factory=lambda: str(uuid4()))

    def presence(self) -> dict[str, str]:
        return {
            "id": self.user_id,
            "display_name": self.display_name,
            "role": self.role,
            "color": self.color,
        }


class CollaborationHub:
    def __init__(self, broker: RealtimeBroker | None = None) -> None:
        self.broker = broker or realtime_broker
        self.rooms: dict[str, dict[str, RoomClient]] = {}
        self.socket_connections: dict[int, str] = {}
        self.subscriptions: dict[str, str] = {}
        self.heartbeat_tasks: dict[str, asyncio.Task] = {}
        self.room_locks: dict[str, asyncio.Lock] = {}
        self.lock = asyncio.Lock()

    async def connect(self, project_id: str, client: RoomClient) -> None:
        await client.websocket.accept()
        try:
            async with self.lock:
                first_local_connection = not self.rooms.get(project_id)
                self.rooms.setdefault(project_id, {})[client.connection_id] = client
                self.socket_connections[id(client.websocket)] = client.connection_id
                self.room_locks.setdefault(project_id, asyncio.Lock())
                if first_local_connection:
                    async def receive_event(
                        payload: dict[str, Any],
                        envelope: RealtimeEnvelope,
                    ) -> None:
                        await self._deliver(project_id, payload, envelope)

                    self.subscriptions[project_id] = await self.broker.subscribe(
                        self._topic(project_id),
                        receive_event,
                    )
        except Exception:
            await self._remove_local(project_id, client)
            raise
        presence_created = False
        try:
            await self.broker.upsert_presence(
                project_id,
                client.connection_id,
                client.presence(),
            )
            presence_created = True
            self.heartbeat_tasks[client.connection_id] = asyncio.create_task(
                self._heartbeat(project_id, client),
                name=f"presence-{project_id}-{client.connection_id}",
            )
            await self.broadcast_presence(project_id)
        except Exception:
            await self._remove_local(project_id, client)
            if presence_created:
                try:
                    await self.broker.remove_presence(project_id, client.connection_id)
                except RealtimeUnavailableError:
                    logger.exception("Could not roll back distributed project presence")
            raise

    async def disconnect(self, project_id: str, websocket: WebSocket) -> None:
        connection_id = self.socket_connections.get(id(websocket))
        if not connection_id:
            return
        client = self.rooms.get(project_id, {}).get(connection_id)
        if not client:
            return
        await self._remove_local(project_id, client)
        try:
            await self.broker.remove_presence(project_id, connection_id)
            users, _ = await self.broker.list_presence(project_id)
            if not any(user.get("id") == client.user_id for user in users):
                await self.broadcast(
                    project_id,
                    {"type": "cursor_removed", "user_id": client.user_id},
                )
            await self.broadcast_presence(project_id, users)
        except RealtimeUnavailableError:
            logger.exception("Could not remove distributed project presence")

    async def _remove_local(self, project_id: str, client: RoomClient) -> None:
        subscription = None
        heartbeat = None
        async with self.lock:
            room = self.rooms.get(project_id)
            if room:
                room.pop(client.connection_id, None)
                self.socket_connections.pop(id(client.websocket), None)
                heartbeat = self.heartbeat_tasks.pop(client.connection_id, None)
                if not room:
                    self.rooms.pop(project_id, None)
                    self.room_locks.pop(project_id, None)
                    subscription = self.subscriptions.pop(project_id, None)
        if heartbeat:
            heartbeat.cancel()
            try:
                await heartbeat
            except asyncio.CancelledError:
                pass
        if subscription:
            await self.broker.unsubscribe(self._topic(project_id), subscription)

    def document_lock(self, project_id: str) -> asyncio.Lock:
        return self.room_locks.setdefault(project_id, asyncio.Lock())

    async def send(self, websocket: WebSocket, payload: dict[str, Any]) -> bool:
        try:
            await websocket.send_json(payload)
        except (RuntimeError, WebSocketDisconnect):
            return False
        return True

    async def broadcast(
        self,
        project_id: str,
        payload: dict[str, Any],
        *,
        exclude: WebSocket | None = None,
    ) -> None:
        await self.broker.publish(
            self._topic(project_id),
            payload,
            exclude_connection_id=(
                self.socket_connections.get(id(exclude)) if exclude else None
            ),
        )

    async def _deliver(
        self,
        project_id: str,
        payload: dict[str, Any],
        envelope: RealtimeEnvelope,
    ) -> None:
        clients = [
            client
            for client in self.rooms.get(project_id, {}).values()
            if client.connection_id != envelope.exclude_connection_id
        ]
        results = await asyncio.gather(
            *(self.send(client.websocket, payload) for client in clients),
            return_exceptions=True,
        )
        for client, delivered in zip(clients, results):
            if delivered is not True:
                await self._remove_local(project_id, client)
                try:
                    await self.broker.remove_presence(project_id, client.connection_id)
                except RealtimeUnavailableError:
                    logger.exception("Could not remove failed project presence")

    async def broadcast_presence(
        self,
        project_id: str,
        users: list[dict[str, Any]] | None = None,
    ) -> None:
        if users is None:
            users, _ = await self.broker.list_presence(project_id)
        await self.broadcast(
            project_id,
            {"type": "presence", "users": users},
        )

    async def _heartbeat(self, project_id: str, client: RoomClient) -> None:
        interval = max(5, self.broker.presence_ttl_seconds // 3)
        while True:
            await asyncio.sleep(interval)
            try:
                await self.broker.upsert_presence(
                    project_id,
                    client.connection_id,
                    client.presence(),
                )
                users, pruned = await self.broker.list_presence(project_id)
                if pruned:
                    await self.broadcast_presence(project_id, users)
            except RealtimeUnavailableError:
                logger.exception("Distributed project presence heartbeat failed")

    @staticmethod
    def _topic(project_id: str) -> str:
        return f"project:{project_id}"


hub = CollaborationHub()


class DocumentConflictError(ValueError):
    def __init__(self, current_revision: int) -> None:
        super().__init__("This flowchart changed before your update could be applied.")
        self.current_revision = current_revision


def require_project_editor(user: User, access_role: str | None = None) -> None:
    effective_access = access_role or ("admin" if user.role == "admin" else None)
    if not can_edit_project(effective_access):
        raise PermissionError("View-only users cannot modify this flowchart.")


def require_project_commenter(user: User, access_role: str | None = None) -> None:
    effective_access = access_role or ("admin" if user.role == "admin" else None)
    if effective_access not in {"admin", "owner", "editor", "commenter", "approver"}:
        raise PermissionError("Comment access is required for flowchart notes.")


def serialize_note(note: ProjectNote, author: User) -> dict[str, Any]:
    return {
        "id": note.id,
        "body": note.body,
        "node_id": note.node_id,
        "resolved": note.resolved,
        "resolved_at": as_utc(note.resolved_at).isoformat() if note.resolved_at else None,
        "created_at": as_utc(note.created_at).isoformat(),
        "author": user_summary(author),
    }


def serialize_task(
    task: ProjectTask,
    creator: User,
    assignee: User | None,
) -> dict[str, Any]:
    return {
        "id": task.id,
        "title": task.title,
        "details": task.details,
        "status": task.status,
        "priority": task.priority,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "deliverable_id": task.deliverable_id,
        "node_id": task.node_id,
        "created_at": as_utc(task.created_at).isoformat(),
        "updated_at": as_utc(task.updated_at).isoformat(),
        "creator": user_summary(creator),
        "assignee": user_summary(assignee) if assignee else None,
    }


def serialize_deliverable(
    deliverable: ProjectDeliverable,
    creator: User,
    owner: User | None,
) -> dict[str, Any]:
    return {
        "id": deliverable.id,
        "title": deliverable.title,
        "description": deliverable.description,
        "status": deliverable.status,
        "target_date": deliverable.target_date.isoformat() if deliverable.target_date else None,
        "node_id": deliverable.node_id,
        "created_at": as_utc(deliverable.created_at).isoformat(),
        "updated_at": as_utc(deliverable.updated_at).isoformat(),
        "creator": user_summary(creator),
        "owner": user_summary(owner) if owner else None,
    }


async def recent_notes(project_id: str) -> list[dict[str, Any]]:
    async with session_factory() as session:
        rows = (
            await session.execute(
                select(ProjectNote, User)
                .join(User, User.id == ProjectNote.author_id)
                .where(ProjectNote.project_id == project_id)
                .order_by(ProjectNote.created_at.desc())
                .limit(100)
            )
        ).all()
    return [serialize_note(note, author) for note, author in reversed(rows)]


async def recent_tasks(project_id: str) -> list[dict[str, Any]]:
    async with session_factory() as session:
        tasks = list(
            await session.scalars(
                select(ProjectTask)
                .where(ProjectTask.project_id == project_id)
                .order_by(ProjectTask.created_at.asc())
                .limit(200)
            )
        )
        user_ids = {
            user_id
            for task in tasks
            for user_id in (task.creator_id, task.assignee_id)
            if user_id
        }
        users = {}
        if user_ids:
            user_rows = await session.scalars(select(User).where(User.id.in_(user_ids)))
            users = {user.id: user for user in user_rows}
    return [
        serialize_task(task, users[task.creator_id], users.get(task.assignee_id))
        for task in tasks
    ]


async def recent_deliverables(project_id: str) -> list[dict[str, Any]]:
    async with session_factory() as session:
        deliverables = list(
            await session.scalars(
                select(ProjectDeliverable)
                .where(ProjectDeliverable.project_id == project_id)
                .order_by(ProjectDeliverable.target_date.asc(), ProjectDeliverable.created_at.asc())
                .limit(100)
            )
        )
        user_ids = {
            user_id
            for deliverable in deliverables
            for user_id in (deliverable.creator_id, deliverable.owner_id)
            if user_id
        }
        users = {}
        if user_ids:
            user_rows = await session.scalars(select(User).where(User.id.in_(user_ids)))
            users = {user.id: user for user in user_rows}
    return [
        serialize_deliverable(
            deliverable,
            users[deliverable.creator_id],
            users.get(deliverable.owner_id),
        )
        for deliverable in deliverables
    ]


async def persist_document(
    project_id: str,
    user_id: str,
    raw_document: Any,
    expected_revision: int | None,
) -> tuple[dict[str, Any], int]:
    try:
        validated = ProjectWrite.model_validate(raw_document)
    except ValidationError as error:
        raise ValueError("Invalid flowchart document") from error

    async with session_factory() as session:
        project = await session.scalar(
            select(Project).where(Project.id == project_id).with_for_update()
        )
        user = await session.get(User, user_id)
        if not project or not user or project.entity_id != user.entity_id:
            raise ValueError("Project no longer exists")
        require_project_editor(user, await project_access_role(session, project, user))
        current_revision = project.revision or 0
        if expected_revision != current_revision:
            raise DocumentConflictError(current_revision)
        graph = validated.graph.model_dump(mode="json")
        graph["title"] = validated.title
        project.title = validated.title
        project.source_text = validated.source_text
        project.graph = graph
        project.revision = (project.revision or 0) + 1
        project.approval_status = "draft"
        await session.commit()
        await session.refresh(project)
        return {
            "title": project.title,
            "source_text": project.source_text,
            "graph": project.graph,
        }, project.revision


async def persist_note(
    project_id: str,
    client: RoomClient,
    body: str,
    mentioned_user_ids: list[str],
    node_id: str | None,
) -> tuple[dict[str, Any], list[tuple[str, dict[str, Any]]]]:
    async with session_factory() as session:
        project = await session.get(Project, project_id)
        author = await session.get(User, client.user_id)
        if not project or not author or project.entity_id != author.entity_id:
            raise ValueError("Project no longer exists")
        require_project_commenter(author, await project_access_role(session, project, author))
        if node_id and node_id not in {node.get("id") for node in project.graph.get("nodes", [])}:
            raise ValueError("The selected flowchart step no longer exists")

        candidate_ids = set(mentioned_user_ids[:20]) - {author.id}
        mentioned_users = []
        if candidate_ids:
            mentioned_users = list(
                await session.scalars(
                    select(User).where(
                        User.id.in_(candidate_ids),
                        User.entity_id == project.entity_id,
                    )
                )
            )
        lowered_body = body.lower()
        mentioned_users = [
            user for user in mentioned_users if f"@{user_handle(user)}" in lowered_body
        ]

        note = ProjectNote(
            project_id=project.id,
            author_id=author.id,
            body=body,
            node_id=node_id,
        )
        session.add(note)
        await session.flush()
        notifications = [
            Notification(
                entity_id=project.entity_id,
                user_id=user.id,
                actor_id=author.id,
                kind="mention",
                title=f"{author.display_name} mentioned you",
                body=body,
                project_id=project.id,
            )
            for user in mentioned_users
        ]
        session.add_all(notifications)
        await session.commit()
        await session.refresh(note)
        for notification in notifications:
            await session.refresh(notification)
        return serialize_note(note, author), [
            (notification.user_id, serialize_notification(notification, author))
            for notification in notifications
        ]


async def resolve_note(
    project_id: str,
    user_id: str,
    note_id: str,
    resolved: bool,
) -> dict[str, Any]:
    async with session_factory() as session:
        project = await session.get(Project, project_id)
        user = await session.get(User, user_id)
        note = await session.get(ProjectNote, note_id)
        if (
            not project
            or not user
            or not note
            or note.project_id != project.id
            or project.entity_id != user.entity_id
        ):
            raise ValueError("Note not found")
        require_project_commenter(user, await project_access_role(session, project, user))
        note.resolved = resolved
        note.resolved_at = datetime.now(timezone.utc) if resolved else None
        await session.commit()
        await session.refresh(note)
        return {
            "id": note.id,
            "resolved": note.resolved,
            "resolved_at": as_utc(note.resolved_at).isoformat() if note.resolved_at else None,
        }


async def persist_deliverable(
    project_id: str,
    client: RoomClient,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], tuple[str, dict[str, Any]] | None]:
    title = str(payload.get("title") or "").strip()
    description = str(payload.get("description") or "").strip()
    owner_id = str(payload.get("owner_id") or "").strip() or None
    target_date_value = str(payload.get("target_date") or "").strip()
    node_id = str(payload.get("node_id") or "").strip() or None
    if not title or len(title) > 160 or len(description) > 2_000:
        raise ValueError(
            "Deliverable titles must be 1–160 characters and descriptions at most 2,000 characters."
        )
    try:
        target_date = date.fromisoformat(target_date_value) if target_date_value else None
    except ValueError as error:
        raise ValueError("Deliverable target date must use YYYY-MM-DD format.") from error

    async with session_factory() as session:
        project = await session.get(Project, project_id)
        creator = await session.get(User, client.user_id)
        if not project or not creator or project.entity_id != creator.entity_id:
            raise ValueError("Project no longer exists")
        require_project_editor(creator, await project_access_role(session, project, creator))
        owner = await session.get(User, owner_id) if owner_id else None
        if owner_id and (not owner or owner.entity_id != project.entity_id):
            raise ValueError("Deliverable owner is not in this entity.")
        if node_id and node_id not in {node.get("id") for node in project.graph.get("nodes", [])}:
            raise ValueError("The linked flowchart step no longer exists.")

        deliverable = ProjectDeliverable(
            project_id=project.id,
            creator_id=creator.id,
            owner_id=owner.id if owner else None,
            title=title,
            description=description,
            target_date=target_date,
            node_id=node_id,
        )
        session.add(deliverable)
        project.updated_at = datetime.now(timezone.utc)
        notification = None
        if owner and owner.id != creator.id:
            notification = Notification(
                entity_id=project.entity_id,
                user_id=owner.id,
                actor_id=creator.id,
                kind="deliverable_assigned",
                title=f"{creator.display_name} made you a deliverable owner",
                body=title,
                project_id=project.id,
            )
            session.add(notification)
        await session.commit()
        await session.refresh(deliverable)
        if notification:
            await session.refresh(notification)
        notification_event = (
            (owner.id, serialize_notification(notification, creator))
            if owner and notification
            else None
        )
        return serialize_deliverable(deliverable, creator, owner), notification_event


async def update_deliverable_status(
    project_id: str,
    user_id: str,
    deliverable_id: str,
    status: str,
) -> dict[str, Any]:
    normalized_status = status.strip().lower()
    if normalized_status not in {"planned", "in_progress", "blocked", "done"}:
        raise ValueError("Deliverable status must be planned, in_progress, blocked, or done.")
    async with session_factory() as session:
        project = await session.get(Project, project_id)
        user = await session.get(User, user_id)
        deliverable = await session.get(ProjectDeliverable, deliverable_id)
        if (
            not project
            or not user
            or not deliverable
            or deliverable.project_id != project.id
            or project.entity_id != user.entity_id
        ):
            raise ValueError("Deliverable not found")
        require_project_editor(user, await project_access_role(session, project, user))
        deliverable.status = normalized_status
        project.updated_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(deliverable)
        creator = await session.get(User, deliverable.creator_id)
        owner = await session.get(User, deliverable.owner_id) if deliverable.owner_id else None
        if not creator:
            raise ValueError("Deliverable creator no longer exists")
        return serialize_deliverable(deliverable, creator, owner)


async def update_deliverable_fields(
    project_id: str,
    user_id: str,
    deliverable_id: str,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], tuple[str, dict[str, Any]] | None]:
    async with session_factory() as session:
        project = await session.get(Project, project_id)
        user = await session.get(User, user_id)
        deliverable = await session.get(ProjectDeliverable, deliverable_id)
        if (
            not project or not user or not deliverable
            or deliverable.project_id != project.id or project.entity_id != user.entity_id
        ):
            raise ValueError("Deliverable not found")
        require_project_editor(user, await project_access_role(session, project, user))

        title = str(payload.get("title", deliverable.title)).strip()
        description = str(payload.get("description", deliverable.description)).strip()
        status = str(payload.get("status", deliverable.status)).strip().lower()
        owner_id = (
            str(payload.get("owner_id") or "").strip() or None
            if "owner_id" in payload else deliverable.owner_id
        )
        node_id = (
            str(payload.get("node_id") or "").strip() or None
            if "node_id" in payload else deliverable.node_id
        )
        target_date_value = payload.get("target_date")
        try:
            target_date = (
                date.fromisoformat(str(target_date_value)) if target_date_value else None
            ) if "target_date" in payload else deliverable.target_date
        except ValueError as error:
            raise ValueError("Deliverable target date must use YYYY-MM-DD format.") from error
        if not title or len(title) > 160 or len(description) > 2_000:
            raise ValueError(
                "Deliverable titles must be 1–160 characters and descriptions at most 2,000 characters."
            )
        if status not in {"planned", "in_progress", "blocked", "done"}:
            raise ValueError("Deliverable status must be planned, in_progress, blocked, or done.")
        owner = await session.get(User, owner_id) if owner_id else None
        if owner_id and (not owner or owner.entity_id != project.entity_id):
            raise ValueError("Deliverable owner is not in this entity.")
        if node_id and node_id not in {node.get("id") for node in project.graph.get("nodes", [])}:
            raise ValueError("The linked workflow step no longer exists.")

        previous_owner_id = deliverable.owner_id
        deliverable.title = title
        deliverable.description = description
        deliverable.status = status
        deliverable.owner_id = owner_id
        deliverable.target_date = target_date
        deliverable.node_id = node_id
        project.updated_at = datetime.now(timezone.utc)
        notification = None
        if owner and owner.id != previous_owner_id and owner.id != user.id:
            notification = Notification(
                entity_id=project.entity_id, user_id=owner.id, actor_id=user.id,
                kind="deliverable_assigned",
                title=f"{user.display_name} made you a deliverable owner",
                body=title, project_id=project.id,
            )
            session.add(notification)
        await session.commit()
        await session.refresh(deliverable)
        creator = await session.get(User, deliverable.creator_id)
        if not creator:
            raise ValueError("Deliverable creator no longer exists")
        if notification:
            await session.refresh(notification)
        return serialize_deliverable(deliverable, creator, owner), (
            (owner.id, serialize_notification(notification, user))
            if owner and notification else None
        )


async def persist_task(
    project_id: str,
    client: RoomClient,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], tuple[str, dict[str, Any]] | None]:
    title = str(payload.get("title") or "").strip()
    details = str(payload.get("details") or "").strip()
    priority = str(payload.get("priority") or "medium").lower()
    assignee_id = str(payload.get("assignee_id") or "").strip() or None
    deliverable_id = str(payload.get("deliverable_id") or "").strip() or None
    node_id = str(payload.get("node_id") or "").strip() or None
    due_date_value = str(payload.get("due_date") or "").strip()
    if not title or len(title) > 160 or len(details) > 1_000:
        raise ValueError("Task titles must be 1–160 characters and details at most 1,000 characters.")
    if priority not in {"low", "medium", "high"}:
        raise ValueError("Task priority must be low, medium, or high.")
    try:
        due_date = date.fromisoformat(due_date_value) if due_date_value else None
    except ValueError as error:
        raise ValueError("Task due date must use YYYY-MM-DD format.") from error

    async with session_factory() as session:
        project = await session.get(Project, project_id)
        creator = await session.get(User, client.user_id)
        if not project or not creator or project.entity_id != creator.entity_id:
            raise ValueError("Project no longer exists")
        require_project_editor(creator, await project_access_role(session, project, creator))
        assignee = await session.get(User, assignee_id) if assignee_id else None
        if assignee_id and (not assignee or assignee.entity_id != project.entity_id):
            raise ValueError("Task assignee is not in this entity.")
        deliverable = (
            await session.get(ProjectDeliverable, deliverable_id) if deliverable_id else None
        )
        if deliverable_id and (
            not deliverable or deliverable.project_id != project.id
        ):
            raise ValueError("Task deliverable is not part of this flowchart.")
        if node_id and node_id not in {node.get("id") for node in project.graph.get("nodes", [])}:
            raise ValueError("The linked flowchart step no longer exists.")

        task = ProjectTask(
            project_id=project.id,
            creator_id=creator.id,
            assignee_id=assignee.id if assignee else None,
            deliverable_id=deliverable.id if deliverable else None,
            node_id=node_id,
            title=title,
            details=details,
            priority=priority,
            due_date=due_date,
        )
        session.add(task)
        project.updated_at = datetime.now(timezone.utc)
        notification = None
        if assignee and assignee.id != creator.id:
            notification = Notification(
                entity_id=project.entity_id,
                user_id=assignee.id,
                actor_id=creator.id,
                kind="task_assigned",
                title=f"{creator.display_name} assigned you a task",
                body=title,
                project_id=project.id,
            )
            session.add(notification)
        await session.commit()
        await session.refresh(task)
        if notification:
            await session.refresh(notification)
        notification_event = (
            (assignee.id, serialize_notification(notification, creator))
            if assignee and notification
            else None
        )
        return serialize_task(task, creator, assignee), notification_event


async def update_task_status(
    project_id: str,
    user_id: str,
    task_id: str,
    status: str,
) -> dict[str, Any]:
    normalized_status = status.strip().lower()
    if normalized_status not in {"todo", "in_progress", "done"}:
        raise ValueError("Task status must be todo, in_progress, or done.")
    async with session_factory() as session:
        project = await session.get(Project, project_id)
        user = await session.get(User, user_id)
        task = await session.get(ProjectTask, task_id)
        if (
            not project
            or not user
            or not task
            or task.project_id != project.id
            or project.entity_id != user.entity_id
        ):
            raise ValueError("Task not found")
        require_project_editor(user, await project_access_role(session, project, user))
        task.status = normalized_status
        project.updated_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(task)
        creator = await session.get(User, task.creator_id)
        assignee = await session.get(User, task.assignee_id) if task.assignee_id else None
        if not creator:
            raise ValueError("Task creator no longer exists")
        return serialize_task(task, creator, assignee)


async def update_task_fields(
    project_id: str,
    user_id: str,
    task_id: str,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], tuple[str, dict[str, Any]] | None]:
    async with session_factory() as session:
        project = await session.get(Project, project_id)
        user = await session.get(User, user_id)
        task = await session.get(ProjectTask, task_id)
        if (
            not project or not user or not task
            or task.project_id != project.id or project.entity_id != user.entity_id
        ):
            raise ValueError("Task not found")
        require_project_editor(user, await project_access_role(session, project, user))

        title = str(payload.get("title", task.title)).strip()
        details = str(payload.get("details", task.details)).strip()
        status = str(payload.get("status", task.status)).strip().lower()
        priority = str(payload.get("priority", task.priority)).strip().lower()
        assignee_id = (
            str(payload.get("assignee_id") or "").strip() or None
            if "assignee_id" in payload else task.assignee_id
        )
        deliverable_id = (
            str(payload.get("deliverable_id") or "").strip() or None
            if "deliverable_id" in payload else task.deliverable_id
        )
        node_id = (
            str(payload.get("node_id") or "").strip() or None
            if "node_id" in payload else task.node_id
        )
        due_date_value = payload.get("due_date")
        try:
            due_date = (
                date.fromisoformat(str(due_date_value)) if due_date_value else None
            ) if "due_date" in payload else task.due_date
        except ValueError as error:
            raise ValueError("Task due date must use YYYY-MM-DD format.") from error
        if not title or len(title) > 160 or len(details) > 1_000:
            raise ValueError("Task titles must be 1–160 characters and details at most 1,000 characters.")
        if status not in {"todo", "in_progress", "done"}:
            raise ValueError("Task status must be todo, in_progress, or done.")
        if priority not in {"low", "medium", "high"}:
            raise ValueError("Task priority must be low, medium, or high.")
        assignee = await session.get(User, assignee_id) if assignee_id else None
        if assignee_id and (not assignee or assignee.entity_id != project.entity_id):
            raise ValueError("Task assignee is not in this entity.")
        deliverable = await session.get(ProjectDeliverable, deliverable_id) if deliverable_id else None
        if deliverable_id and (not deliverable or deliverable.project_id != project.id):
            raise ValueError("Task deliverable is not part of this workflow.")
        if node_id and node_id not in {node.get("id") for node in project.graph.get("nodes", [])}:
            raise ValueError("The linked workflow step no longer exists.")

        previous_assignee_id = task.assignee_id
        task.title = title
        task.details = details
        task.status = status
        task.priority = priority
        task.assignee_id = assignee_id
        task.deliverable_id = deliverable_id
        task.node_id = node_id
        task.due_date = due_date
        project.updated_at = datetime.now(timezone.utc)
        notification = None
        if assignee and assignee.id != previous_assignee_id and assignee.id != user.id:
            notification = Notification(
                entity_id=project.entity_id, user_id=assignee.id, actor_id=user.id,
                kind="task_assigned", title=f"{user.display_name} assigned you a task",
                body=title, project_id=project.id,
            )
            session.add(notification)
        await session.commit()
        await session.refresh(task)
        creator = await session.get(User, task.creator_id)
        if not creator:
            raise ValueError("Task creator no longer exists")
        if notification:
            await session.refresh(notification)
        return serialize_task(task, creator, assignee), (
            (assignee.id, serialize_notification(notification, user))
            if assignee and notification else None
        )


@router.websocket("/projects/{project_id}")
async def project_collaboration(websocket: WebSocket, project_id: str) -> None:
    token = websocket.cookies.get(SESSION_COOKIE)
    async with session_factory() as session:
        user_id = await active_session_user_id(token, settings, session) if token else None
        if not user_id:
            await websocket.close(code=4401, reason="Authentication required")
            return
        user = await session.get(User, user_id)
        project = await session.get(Project, project_id)
        if not user:
            await websocket.close(code=4401, reason="Authentication required")
            return
        access = await project_access_role(session, project, user) if project else None
        if not project or project.entity_id != user.entity_id or not access:
            await websocket.close(code=4404, reason="Project not found")
            return
        snapshot = {
            "title": project.title,
            "source_text": project.source_text,
            "graph": project.graph,
        }
        revision = project.revision or 0
        client = RoomClient(
            websocket=websocket,
            user_id=user.id,
            display_name=user.display_name,
            role=access,
            color=avatar_color(user.id),
        )

    try:
        await hub.connect(project_id, client)
    except RealtimeUnavailableError:
        await websocket.close(code=1013, reason="Realtime collaboration is unavailable")
        return
    try:
        delivered = await hub.send(
            websocket,
            {
                "type": "snapshot",
                "document": snapshot,
                "revision": revision,
                "notes": await recent_notes(project_id),
                "tasks": await recent_tasks(project_id),
                "deliverables": await recent_deliverables(project_id),
            },
        )
        if not delivered:
            return
        while True:
            payload = await websocket.receive_json()
            event_type = payload.get("type")
            if event_type == "cursor":
                try:
                    x = min(1.0, max(0.0, float(payload.get("x"))))
                    y = min(1.0, max(0.0, float(payload.get("y"))))
                except (TypeError, ValueError):
                    continue
                await hub.broadcast(
                    project_id,
                    {
                        "type": "cursor",
                        "user_id": client.user_id,
                        "display_name": client.display_name,
                        "color": client.color,
                        "x": x,
                        "y": y,
                    },
                    exclude=websocket,
                )
            elif event_type == "document":
                try:
                    async with hub.document_lock(project_id):
                        document, revision = await persist_document(
                            project_id,
                            client.user_id,
                            payload.get("document"),
                            payload.get("expected_revision"),
                        )
                except PermissionError as error:
                    await hub.send(
                        websocket,
                        {"type": "error", "code": "FORBIDDEN", "message": str(error)},
                    )
                    continue
                except DocumentConflictError as error:
                    await hub.send(
                        websocket,
                        {
                            "type": "error",
                            "code": "CONFLICT",
                            "message": str(error),
                            "current_revision": error.current_revision,
                        },
                    )
                    continue
                except ValueError as error:
                    await hub.send(
                        websocket,
                        {"type": "error", "code": "BAD_DOCUMENT", "message": str(error)},
                    )
                    continue
                await hub.broadcast(
                    project_id,
                    {
                        "type": "document",
                        "document": document,
                        "revision": revision,
                        "actor_id": client.user_id,
                    },
                    exclude=websocket,
                )
                await hub.send(websocket, {"type": "ack", "revision": revision})
            elif event_type == "note":
                body = str(payload.get("body") or "").strip()
                mentioned_user_ids = [
                    str(user_id) for user_id in (payload.get("mentioned_user_ids") or [])
                ]
                node_id = str(payload.get("node_id") or "").strip() or None
                if not body or len(body) > 2_000:
                    await hub.send(
                        websocket,
                        {"type": "error", "code": "BAD_NOTE", "message": "Notes must be between 1 and 2,000 characters."},
                    )
                    continue
                try:
                    note, notifications = await persist_note(
                        project_id,
                        client,
                        body,
                        mentioned_user_ids,
                        node_id,
                    )
                except PermissionError as error:
                    await hub.send(
                        websocket,
                        {"type": "error", "code": "FORBIDDEN", "message": str(error)},
                    )
                    continue
                except ValueError as error:
                    await hub.send(
                        websocket,
                        {"type": "error", "code": "BAD_NOTE", "message": str(error)},
                    )
                    continue
                await hub.broadcast(project_id, {"type": "note", "note": note})
                for recipient_id, notification in notifications:
                    await communication_hub.publish(
                        recipient_id,
                        {"type": "notification", "notification": notification},
                    )
            elif event_type == "note_resolve":
                note_id = str(payload.get("note_id") or "")
                try:
                    update = await resolve_note(
                        project_id,
                        client.user_id,
                        note_id,
                        bool(payload.get("resolved", True)),
                    )
                except PermissionError as error:
                    await hub.send(
                        websocket,
                        {"type": "error", "code": "FORBIDDEN", "message": str(error)},
                    )
                    continue
                except ValueError as error:
                    await hub.send(
                        websocket,
                        {"type": "error", "code": "BAD_NOTE", "message": str(error)},
                    )
                    continue
                await hub.broadcast(project_id, {"type": "note_resolved", **update})
            elif event_type == "task_create":
                try:
                    task, notification = await persist_task(project_id, client, payload)
                except PermissionError as error:
                    await hub.send(
                        websocket,
                        {"type": "error", "code": "FORBIDDEN", "message": str(error)},
                    )
                    continue
                except ValueError as error:
                    await hub.send(
                        websocket,
                        {"type": "error", "code": "BAD_TASK", "message": str(error)},
                    )
                    continue
                await hub.broadcast(project_id, {"type": "task", "task": task})
                if notification:
                    recipient_id, notification_payload = notification
                    await communication_hub.publish(
                        recipient_id,
                        {"type": "notification", "notification": notification_payload},
                    )
            elif event_type == "task_update":
                try:
                    task, notification = await update_task_fields(
                        project_id,
                        client.user_id,
                        str(payload.get("task_id") or ""),
                        payload,
                    )
                except PermissionError as error:
                    await hub.send(
                        websocket,
                        {"type": "error", "code": "FORBIDDEN", "message": str(error)},
                    )
                    continue
                except ValueError as error:
                    await hub.send(
                        websocket,
                        {"type": "error", "code": "BAD_TASK", "message": str(error)},
                    )
                    continue
                await hub.broadcast(project_id, {"type": "task_updated", "task": task})
                if notification:
                    recipient_id, notification_payload = notification
                    await communication_hub.publish(
                        recipient_id,
                        {"type": "notification", "notification": notification_payload},
                    )
            elif event_type == "deliverable_create":
                try:
                    deliverable, notification = await persist_deliverable(
                        project_id, client, payload
                    )
                except PermissionError as error:
                    await hub.send(
                        websocket,
                        {"type": "error", "code": "FORBIDDEN", "message": str(error)},
                    )
                    continue
                except ValueError as error:
                    await hub.send(
                        websocket,
                        {
                            "type": "error",
                            "code": "BAD_DELIVERABLE",
                            "message": str(error),
                        },
                    )
                    continue
                await hub.broadcast(
                    project_id,
                    {"type": "deliverable", "deliverable": deliverable},
                )
                if notification:
                    recipient_id, notification_payload = notification
                    await communication_hub.publish(
                        recipient_id,
                        {"type": "notification", "notification": notification_payload},
                    )
            elif event_type == "deliverable_update":
                try:
                    deliverable, notification = await update_deliverable_fields(
                        project_id,
                        client.user_id,
                        str(payload.get("deliverable_id") or ""),
                        payload,
                    )
                except PermissionError as error:
                    await hub.send(
                        websocket,
                        {"type": "error", "code": "FORBIDDEN", "message": str(error)},
                    )
                    continue
                except ValueError as error:
                    await hub.send(
                        websocket,
                        {
                            "type": "error",
                            "code": "BAD_DELIVERABLE",
                            "message": str(error),
                        },
                    )
                    continue
                await hub.broadcast(
                    project_id,
                    {"type": "deliverable_updated", "deliverable": deliverable},
                )
                if notification:
                    recipient_id, notification_payload = notification
                    await communication_hub.publish(
                        recipient_id,
                        {"type": "notification", "notification": notification_payload},
                    )
    except WebSocketDisconnect:
        pass
    finally:
        await hub.disconnect(project_id, websocket)
