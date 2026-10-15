import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.app.database import (
    Base,
    CalendarEvent,
    Entity,
    KnowledgeDocument,
    KnowledgeSpace,
    PolicyRule,
    Project,
    ProjectRisk,
    User,
    WorkItem,
    WorkItemLink,
)
from backend.app.work_intelligence import work_intelligence_briefing


def test_briefing_is_explainable_offline_and_does_not_leak_restricted_sources() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        now = datetime.now(timezone.utc)
        async with sessions() as session:
            entity = Entity(id="entity", name="Example")
            admin = User(id="admin", entity_id="entity", email="admin@example.com", display_name="Admin", password_hash="x", role="admin")
            member = User(id="member", entity_id="entity", email="member@example.com", display_name="Member", password_hash="x", role="basic", timezone="UTC")
            visible = Project(id="visible", entity_id="entity", owner_id="admin", title="Visible delivery", visibility="workspace", graph={"title": "Visible", "nodes": [], "edges": []})
            hidden = Project(id="hidden", entity_id="entity", owner_id="admin", title="Secret acquisition", visibility="restricted", graph={"title": "Hidden", "nodes": [], "edges": []})
            overdue = WorkItem(
                id="overdue", entity_id="entity", sequence_number=1, key="EX-1",
                reporter_id="admin", assignee_id="member", project_id="visible",
                summary="Finish launch evidence", status="in_progress", priority="highest",
                due_date=(now - timedelta(days=3)).date(),
            )
            hidden_item = WorkItem(
                id="hidden-item", entity_id="entity", sequence_number=2, key="EX-2",
                reporter_id="admin", assignee_id="member", project_id="hidden",
                summary="Confidential diligence", status="in_progress", priority="highest",
                due_date=(now - timedelta(days=5)).date(),
            )
            blocker = WorkItem(
                id="blocker", entity_id="entity", sequence_number=3, key="EX-3",
                reporter_id="admin", project_id="visible", summary="Approve controls",
                status="in_progress", priority="high",
            )
            risk = ProjectRisk(
                id="risk", entity_id="entity", project_id="visible", title="Launch capacity",
                probability=4, impact=5, status="open", mitigation="Add an on-call rotation",
            )
            meeting = CalendarEvent(
                id="meeting", entity_id="entity", organizer_id="member", title="Launch review",
                starts_at=now - timedelta(hours=2), ends_at=now - timedelta(hours=1),
                updated_at=now - timedelta(hours=1),
            )
            space = KnowledgeSpace(id="space", entity_id="entity", name="Team", visibility="workspace", created_by_id="admin")
            document = KnowledgeDocument(
                id="document", entity_id="entity", space_id="space", owner_id="admin",
                title="Launch runbook", slug="launch-runbook", status="published",
                review_due_at=(now - timedelta(days=1)).date(), updated_at=now - timedelta(days=200),
            )
            session.add_all([
                entity, admin, member, visible, hidden, overdue, hidden_item, blocker, risk,
                meeting, space, document,
                WorkItemLink(id="link", entity_id="entity", source_id="blocker", target_id="overdue", link_type="blocks", created_by_id="admin"),
            ])
            await session.commit()

            briefing = await work_intelligence_briefing(member, session)
            rendered = str(briefing)
            assert briefing["engine"] == "deterministic"
            assert briefing["model_required"] is False
            assert briefing["summary"]["overdue_assigned"] == 1
            assert {item["kind"] for item in briefing["recommendations"]} >= {
                "overdue_work", "project_risk", "meeting_followup", "stale_knowledge",
            }
            assert all(item["sources"] and item["freshness"] and item["permission_scope"] for item in briefing["recommendations"])
            assert all(item["proposed_action"]["mutation"] is False for item in briefing["recommendations"])
            assert "Secret acquisition" not in rendered
            assert "Confidential diligence" not in rendered

            session.add(PolicyRule(
                id="deny-risk", entity_id="entity", name="Hide risks", effect="deny",
                actions=["read"], subject_type="user", subject_id="member",
                resource_type="risk", created_by_id="admin", priority=100,
            ))
            await session.commit()
            restricted = await work_intelligence_briefing(member, session)
            assert not any(item["kind"] == "project_risk" for item in restricted["recommendations"])
        await engine.dispose()

    asyncio.run(scenario())
