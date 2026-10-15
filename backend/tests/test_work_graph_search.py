import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.app.database import (
    AgileRelease,
    Base,
    Entity,
    KnowledgeDocument,
    KnowledgeDocumentAccess,
    KnowledgeSpace,
    ObjectRelationshipHistory,
    Project,
    ProjectCollaborator,
    RecentSearch,
    ServiceTicket,
    User,
    WorkItem,
)
from backend.app.enterprise_search import (
    SavedSearchWrite,
    create_saved_search,
    enterprise_search,
    recent_searches,
    saved_searches,
)
from backend.app.work_graph import (
    RelationshipCreate,
    create_graph_relationship,
    object_history,
    related_objects,
)


def test_permission_filtered_work_graph_and_enterprise_search() -> None:
    asyncio.run(exercise_graph_and_search())


async def exercise_graph_and_search() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with sessions() as session:
        entity = Entity(id="10000000-0000-0000-0000-000000000001", name="Graph Co")
        admin = User(id="10000000-0000-0000-0000-000000000002", entity_id=entity.id,
                     email="admin@graph.test", display_name="Admin", password_hash="x", role="admin")
        editor = User(id="10000000-0000-0000-0000-000000000003", entity_id=entity.id,
                      email="editor@graph.test", display_name="Editor", password_hash="x", role="basic")
        guest = User(id="10000000-0000-0000-0000-000000000004", entity_id=entity.id,
                     email="guest@graph.test", display_name="Guest", password_hash="x", role="guest")
        project = Project(id="10000000-0000-0000-0000-000000000005", entity_id=entity.id,
                          owner_id=admin.id, title="Customer launch", description="Release the customer portal",
                          visibility="restricted", graph={"nodes": [], "edges": []})
        hidden_project = Project(id="10000000-0000-0000-0000-000000000006", entity_id=entity.id,
                                 owner_id=admin.id, title="Secret acquisition", description="Confidential target",
                                 visibility="restricted", graph={"nodes": [], "edges": []})
        launch = WorkItem(id="10000000-0000-0000-0000-000000000007", entity_id=entity.id,
                          sequence_number=1, key="GRA-1", reporter_id=admin.id, project_id=project.id,
                          summary="Deploy customer portal", description="Production rollout")
        secret = WorkItem(id="10000000-0000-0000-0000-000000000008", entity_id=entity.id,
                          sequence_number=2, key="GRA-2", reporter_id=admin.id, project_id=hidden_project.id,
                          summary="Acquisition diligence", description="Do not disclose")
        space = KnowledgeSpace(id="10000000-0000-0000-0000-000000000009", entity_id=entity.id,
                               name="Delivery", created_by_id=admin.id)
        document = KnowledgeDocument(id="10000000-0000-0000-0000-000000000010", entity_id=entity.id,
                                     space_id=space.id, owner_id=admin.id, title="Launch runbook",
                                     slug="launch-runbook", summary="Release checklist", body="Deploy and verify",
                                     status="published", visibility="workspace")
        release = AgileRelease(id="10000000-0000-0000-0000-000000000011", entity_id=entity.id,
                               created_by_id=admin.id, name="Autumn rollout", description="Customer shipment")
        now = datetime.now(timezone.utc)
        ticket = ServiceTicket(id="10000000-0000-0000-0000-000000000012", entity_id=entity.id,
                               requester_id=admin.id, assignee_id=editor.id, project_id=project.id,
                               title="Customer portal outage", description="Checkout deployment failed",
                               ticket_type="incident", severity="critical", priority="urgent", service="portal",
                               response_due_at=now + timedelta(minutes=15), resolution_due_at=now + timedelta(hours=4))
        session.add_all([entity, admin, editor, guest, project, hidden_project, launch, secret, space, document, release, ticket])
        session.add_all([
            ProjectCollaborator(project_id=project.id, user_id=editor.id, access_role="editor"),
            ProjectCollaborator(project_id=project.id, user_id=guest.id, access_role="viewer"),
            KnowledgeDocumentAccess(document_id=document.id, user_id=guest.id, role="viewer"),
        ])
        await session.commit()

        first = await create_graph_relationship(RelationshipCreate(
            source_type="project", source_id=project.id, target_type="work_item", target_id=launch.id,
            relationship_type="parent_of",
        ), admin, session)
        await create_graph_relationship(RelationshipCreate(
            source_type="work_item", source_id=launch.id, target_type="document", target_id=document.id,
            relationship_type="documented_by",
        ), editor, session)
        await create_graph_relationship(RelationshipCreate(
            source_type="project", source_id=hidden_project.id, target_type="work_item", target_id=secret.id,
            relationship_type="parent_of",
        ), admin, session)

        traversal = await related_objects("project", project.id, 2, "both", "", 100, guest, session)
        assert {item["id"] for item in traversal["nodes"]} == {launch.id, document.id}
        assert len(traversal["edges"]) == 2
        assert traversal["nodes"][1]["depth"] == 2

        with pytest.raises(HTTPException) as hidden:
            await related_objects("project", hidden_project.id, 1, "both", "", 100, guest, session)
        assert hidden.value.status_code == 404

        await create_graph_relationship(RelationshipCreate(
            source_type="service_ticket", source_id=ticket.id, target_type="project", target_id=project.id,
            relationship_type="impacts",
        ), admin, session)
        ticket_graph = await related_objects("service_ticket", ticket.id, 1, "both", "", 100, editor, session)
        assert ticket_graph["nodes"][0]["id"] == project.id

        history = await object_history("project", project.id, 50, admin, session)
        assert any(item["action"] == "relationship.created" for item in history["events"])
        stored_history = list(await session.scalars(select(ObjectRelationshipHistory)))
        assert len(stored_history) == 4
        assert first["source_id"] == project.id

        admin_results = await enterprise_search(q="acquisition", mode="keyword", types="project,work_item",
                                                statuses="", project_id=None, owner_id=None, updated_from=None,
                                                updated_to=None, offset=0, limit=40, remember=True,
                                                user=admin, session=session)
        assert admin_results["total"] == 2
        guest_results = await enterprise_search(q="acquisition", mode="keyword", types="project,work_item",
                                                statuses="", project_id=None, owner_id=None, updated_from=None,
                                                updated_to=None, offset=0, limit=40, remember=True,
                                                user=guest, session=session)
        assert guest_results["total"] == 0

        semantic = await enterprise_search(q="deploy", mode="semantic", types="release", statuses="",
                                           project_id=None, owner_id=None, updated_from=None, updated_to=None,
                                           offset=0, limit=40, remember=True, user=editor, session=session)
        assert semantic["results"][0]["id"] == release.id
        assert semantic["results"][0]["matched_by"] == "semantic"

        tickets = await enterprise_search(q="outage", mode="keyword", types="service_ticket", statuses="",
                                          project_id=None, owner_id=None, updated_from=None, updated_to=None,
                                          offset=0, limit=40, remember=False, user=editor, session=session)
        assert tickets["results"][0]["url"] == f"/service?ticket={ticket.id}"

        saved = await create_saved_search(SavedSearchWrite(
            name="Launch work", query="launch", mode="hybrid", filters={"types": ["project", "work_item"]},
        ), editor, session)
        assert saved["can_edit"] is True
        assert len(await saved_searches(editor, session)) == 1
        assert len(await recent_searches(editor, session)) == 1
        assert len(list(await session.scalars(select(RecentSearch).where(RecentSearch.user_id == admin.id)))) == 1

    await engine.dispose()
