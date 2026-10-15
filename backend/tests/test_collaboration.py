import asyncio
from datetime import date, datetime, timezone

from backend.app.collaboration import (
    AVATAR_COLORS,
    CollaborationHub,
    avatar_color,
    require_project_editor,
    serialize_deliverable,
    serialize_task,
)
from backend.app.database import ProjectDeliverable, ProjectTask, User
from backend.app.identity import user_handle


class DisconnectedSocket:
    async def send_json(self, _payload) -> None:
        from starlette.websockets import WebSocketDisconnect

        raise WebSocketDisconnect()


def test_collaboration_avatar_colors_are_stable_per_user() -> None:
    first = avatar_color("user-123")

    assert first == avatar_color("user-123")
    assert first in AVATAR_COLORS
    assert avatar_color("user-456") in AVATAR_COLORS


def test_mention_handle_is_stable_and_url_safe() -> None:
    user = User(
        id="755dff59-3193-49ef-88e6-7ff05d0816a7",
        entity_id="entity-1",
        display_name="Taylor Collaborator",
        email="Taylor+Ops@example.com",
        password_hash="unused",
        role="basic",
    )

    assert user_handle(user) == "taylor-ops-755d"


def test_basic_users_cannot_modify_a_collaborative_flowchart() -> None:
    basic_user = User(
        id="user-1",
        entity_id="entity-1",
        display_name="Taylor Viewer",
        email="taylor@example.com",
        password_hash="unused",
        role="basic",
    )

    try:
        require_project_editor(basic_user)
    except PermissionError as error:
        assert str(error) == "View-only users cannot modify this flowchart."
    else:
        raise AssertionError("Basic users must not receive collaborative write access")


def test_admin_users_can_modify_a_collaborative_flowchart() -> None:
    admin_user = User(
        id="user-1",
        entity_id="entity-1",
        display_name="Avery Admin",
        email="avery@example.com",
        password_hash="unused",
        role="admin",
    )

    require_project_editor(admin_user)


def test_collaboration_send_treats_a_disconnect_as_a_closed_socket() -> None:
    delivered = asyncio.run(CollaborationHub().send(DisconnectedSocket(), {"type": "ready"}))

    assert delivered is False


def test_planning_records_serialize_flowchart_and_deliverable_links() -> None:
    created_at = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
    creator = User(
        id="user-1",
        entity_id="entity-1",
        display_name="Avery Admin",
        email="avery@example.com",
        password_hash="unused",
        role="admin",
    )
    owner = User(
        id="user-2",
        entity_id="entity-1",
        display_name="Taylor Viewer",
        email="taylor@example.com",
        password_hash="unused",
        role="basic",
    )
    deliverable = ProjectDeliverable(
        id="deliverable-1",
        project_id="project-1",
        creator_id=creator.id,
        owner_id=owner.id,
        title="Policy ready",
        description="Approved and published.",
        status="in_progress",
        target_date=date(2026, 9, 15),
        node_id="approval",
        created_at=created_at,
        updated_at=created_at,
    )
    task = ProjectTask(
        id="task-1",
        project_id="project-1",
        creator_id=creator.id,
        assignee_id=owner.id,
        deliverable_id=deliverable.id,
        node_id="approval",
        title="Review branch",
        details="Confirm the escalation path.",
        status="todo",
        priority="high",
        due_date=date(2026, 9, 14),
        created_at=created_at,
        updated_at=created_at,
    )

    serialized_deliverable = serialize_deliverable(deliverable, creator, owner)
    serialized_task = serialize_task(task, creator, owner)

    assert serialized_deliverable["target_date"] == "2026-09-15"
    assert serialized_deliverable["node_id"] == "approval"
    assert serialized_deliverable["owner"]["id"] == owner.id
    assert serialized_task["deliverable_id"] == deliverable.id
    assert serialized_task["node_id"] == "approval"
    assert serialized_task["assignee"]["id"] == owner.id
