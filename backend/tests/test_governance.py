import asyncio

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.app.database import AuditEvent, Base, Entity, Project, ProjectCollaborator, ProjectRevision, User
from backend.app.governance import (
    can_approve_project,
    can_edit_project,
    can_manage_project,
    default_project_role,
    normalize_project_role,
    normalize_visibility,
    project_access_role,
    record_audit_event,
    snapshot_project,
)


def user(role: str) -> User:
    return User(
        id=f"{role}-user",
        entity_id="entity-1",
        display_name="Test User",
        email=f"{role}@example.com",
        password_hash="unused",
        role=role,
    )


def test_project_roles_have_separate_edit_approve_and_manage_capabilities() -> None:
    assert can_edit_project("editor")
    assert not can_edit_project("approver")
    assert can_approve_project("approver")
    assert not can_approve_project("owner")
    assert can_manage_project("owner")
    assert not can_manage_project("editor")


def test_workspace_role_only_sets_a_safe_default_project_role() -> None:
    assert default_project_role(user("admin")) == "editor"
    assert default_project_role(user("basic")) == "viewer"


def test_project_role_and_visibility_validation_is_closed_by_default() -> None:
    assert normalize_project_role(" Approver ") == "approver"
    assert normalize_visibility(" Restricted ") == "restricted"

    with pytest.raises(ValueError, match="Project role"):
        normalize_project_role("administrator")
    with pytest.raises(ValueError, match="Visibility"):
        normalize_visibility("public")


def test_restricted_access_revisions_and_auditing_are_persisted() -> None:
    async def scenario() -> None:
        engine = create_async_engine(
            "sqlite+aiosqlite://",
            poolclass=StaticPool,
        )
        session_maker = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with session_maker() as session:
            entity = Entity(id="entity-1", name="Test workspace")
            admin = user("admin")
            viewer = user("basic")
            project = Project(
                id="project-1",
                entity_id=entity.id,
                owner_id=admin.id,
                title="Controlled process",
                description="",
                status="active",
                visibility="workspace",
                approval_status="draft",
                source_text="Start",
                graph={"title": "Controlled process", "nodes": [], "edges": []},
            )
            session.add_all([entity, admin, viewer, project])
            await session.flush()

            assert await project_access_role(session, project, viewer) == "viewer"
            project.visibility = "restricted"
            assert await project_access_role(session, project, viewer) is None

            session.add(ProjectCollaborator(
                project_id=project.id,
                user_id=viewer.id,
                access_role="editor",
            ))
            await session.flush()
            assert await project_access_role(session, project, viewer) == "editor"
            assert await project_access_role(session, project, admin) == "admin"

            first = await snapshot_project(session, project, admin.id, "Created")
            project.title = "Controlled process v2"
            second = await snapshot_project(session, project, admin.id, "Updated")
            record_audit_event(
                session,
                entity_id=entity.id,
                actor_id=admin.id,
                project_id=project.id,
                action="project.revision_created",
                details={"revision": second.version},
            )
            await session.commit()

            versions = list(await session.scalars(
                select(ProjectRevision.version).order_by(ProjectRevision.version)
            ))
            event_count = await session.scalar(select(func.count(AuditEvent.id)))
            assert first.version == 1
            assert versions == [1, 2]
            assert event_count == 1
        await engine.dispose()

    asyncio.run(scenario())
