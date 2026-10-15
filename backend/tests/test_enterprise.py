import asyncio

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.app.database import (
    ApprovalDefinition, ApprovalInstance, Base, Entity, ObjectRelationship, Project,
    SavedWorkspaceView, User, WorkItem,
)
from backend.app.enterprise import (
    ApprovalDecisionWrite, ApprovalDefinitionWrite, ApprovalRequestWrite, RelationshipWrite,
    ReportQueryWrite, ViewWrite, create_approval_definition, create_relationship,
    decide_approval, dependency_map, organization_timeline, request_approval,
    run_report, save_view, verify_audit_chain,
)


def test_enterprise_dependencies_approvals_views_and_audit() -> None:
    asyncio.run(exercise_enterprise())


async def exercise_enterprise() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with sessions() as session:
        entity = Entity(id="11111111-1111-1111-1111-111111111111", name="Northwind")
        admin = User(id="22222222-2222-2222-2222-222222222222", entity_id=entity.id,
                     email="admin@example.com", display_name="Admin", password_hash="x", role="admin")
        reviewer = User(id="33333333-3333-3333-3333-333333333333", entity_id=entity.id,
                        email="reviewer@example.com", display_name="Reviewer", password_hash="x", role="basic")
        project = Project(id="44444444-4444-4444-4444-444444444444", entity_id=entity.id,
                          owner_id=admin.id, title="Launch", graph={"nodes": [], "edges": []})
        first = WorkItem(id="55555555-5555-5555-5555-555555555555", entity_id=entity.id,
                         sequence_number=1, key="NOR-1", reporter_id=admin.id,
                         project_id=project.id, summary="Design")
        second = WorkItem(id="66666666-6666-6666-6666-666666666666", entity_id=entity.id,
                          sequence_number=2, key="NOR-2", reporter_id=admin.id,
                          project_id=project.id, summary="Build")
        session.add_all([entity, admin, reviewer, project, first, second])
        await session.commit()

        edge = await create_relationship(RelationshipWrite(
            source_type="work_item", source_id=first.id, target_type="work_item",
            target_id=second.id, relationship_type="blocks",
        ), admin, session)
        assert edge["source_id"] == first.id
        with pytest.raises(HTTPException) as cycle:
            await create_relationship(RelationshipWrite(
                source_type="work_item", source_id=second.id, target_type="work_item",
                target_id=first.id, relationship_type="blocks",
            ), admin, session)
        assert cycle.value.status_code == 409
        with pytest.raises(HTTPException) as dangling:
            await create_relationship(RelationshipWrite(
                source_type="work_item", source_id="missing", target_type="work_item",
                target_id=first.id, relationship_type="related_to",
            ), admin, session)
        assert dangling.value.status_code == 400

        first_view = await save_view(ViewWrite(
            name="My board", view_type="board", config={"mine": True}, is_default=True,
        ), admin, session)
        second_view = await save_view(ViewWrite(
            name="Team board", view_type="board", config={"swimlane": "team"}, is_default=True,
        ), admin, session)
        rows = (await session.scalars(select(SavedWorkspaceView).order_by(SavedWorkspaceView.created_at))).all()
        assert {row.id for row in rows} == {first_view["id"], second_view["id"]}
        assert [row.is_default for row in rows] == [False, True]

        definition_payload = ApprovalDefinitionWrite(
            name="Two-person signoff", target_types=["project"],
            stages=[{"name": "Review", "mode": "parallel", "approver_ids": [admin.id, reviewer.id]}],
        )
        definition_result = await create_approval_definition(definition_payload, admin, session)
        approval = await request_approval(ApprovalRequestWrite(
            definition_id=definition_result["id"], target_type="project", target_id=project.id,
        ), admin, session)
        pending = await decide_approval(approval["id"], ApprovalDecisionWrite(decision="approved"), admin, session)
        assert pending["status"] == "pending"
        completed = await decide_approval(approval["id"], ApprovalDecisionWrite(decision="approved"), reviewer, session)
        assert completed["status"] == "approved"
        assert len(completed["decisions"]) == 2

        verification = await verify_audit_chain(admin, session)
        assert verification["valid"] is True
        assert verification["event_count"] >= 3

        guest = User(id="77777777-7777-7777-7777-777777777777", entity_id=entity.id,
                     email="guest@example.com", display_name="Guest", password_hash="x", role="guest")
        session.add(guest)
        await session.commit()
        for operation in (
            lambda: dependency_map(None, guest, session),
            lambda: organization_timeline("", None, None, 20, guest, session),
            lambda: run_report(ReportQueryWrite(), guest, session),
        ):
            with pytest.raises(HTTPException) as forbidden:
                await operation()
            assert forbidden.value.status_code == 403

    await engine.dispose()
