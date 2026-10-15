import asyncio

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.app.change_proposals import (
    GraphOperation,
    ProposalCreate,
    ProposalDecision,
    apply_proposal,
    create_proposal,
    decide_proposal,
    list_proposals,
    rollback_proposal,
)
from backend.app.database import (
    AuditEvent,
    Base,
    Entity,
    ObjectRelationship,
    ObjectRelationshipHistory,
    Project,
    User,
    WorkItem,
)


def test_reviewed_graph_change_is_idempotent_reversible_and_audited() -> None:
    asyncio.run(exercise_reviewed_change())


async def exercise_reviewed_change() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with sessions() as session:
        entity = Entity(id="20000000-0000-0000-0000-000000000001", name="Governed Co")
        author = User(id="20000000-0000-0000-0000-000000000002", entity_id=entity.id,
                      email="author@governed.test", display_name="Author", password_hash="x", role="admin")
        reviewer = User(id="20000000-0000-0000-0000-000000000003", entity_id=entity.id,
                        email="reviewer@governed.test", display_name="Reviewer", password_hash="x", role="admin")
        project = Project(id="20000000-0000-0000-0000-000000000004", entity_id=entity.id,
                          owner_id=author.id, title="Launch", visibility="restricted", graph={"nodes": [], "edges": []})
        work = WorkItem(id="20000000-0000-0000-0000-000000000005", entity_id=entity.id,
                        sequence_number=1, key="GOV-1", reporter_id=author.id, project_id=project.id,
                        summary="Release readiness")
        session.add_all([entity, author, reviewer, project, work])
        await session.commit()

        payload = ProposalCreate(
            title="Connect launch work",
            rationale="Expose the delivery relationship in the canonical graph.",
            idempotency_key="governed:create:launch-work",
            evidence=[{"type": "work_item", "id": work.id, "observed_at": "2026-09-13T10:00:00Z"}],
            operations=[GraphOperation(
                action="create", source_type="project", source_id=project.id,
                target_type="work_item", target_id=work.id, relationship_type="parent_of",
                metadata={"reason": "approved delivery structure"},
            )],
        )
        proposal = await create_proposal(payload, author, session)
        duplicate = await create_proposal(payload, author, session)
        assert duplicate["id"] == proposal["id"]
        assert proposal["status"] == "pending"
        assert proposal["preview"]["requires_review"] is True
        assert proposal["preview"]["rollback_supported"] is True

        with pytest.raises(HTTPException) as self_review:
            await decide_proposal(proposal["id"], ProposalDecision(decision="approved"), author, session)
        assert self_review.value.status_code == 403

        approved = await decide_proposal(
            proposal["id"], ProposalDecision(decision="approved", note="Evidence verified."), reviewer, session,
        )
        assert approved["status"] == "approved"
        assert approved["can_apply"] is True

        applied = await apply_proposal(proposal["id"], reviewer, session)
        assert applied["status"] == "applied"
        assert len(applied["after_snapshot"]) == 1
        replay = await apply_proposal(proposal["id"], reviewer, session)
        assert replay["after_snapshot"] == applied["after_snapshot"]
        relationship = await session.scalar(select(ObjectRelationship))
        assert relationship.relationship_type == "parent_of"

        rolled_back = await rollback_proposal(proposal["id"], reviewer, session)
        assert rolled_back["status"] == "rolled_back"
        assert await session.scalar(select(ObjectRelationship.id)) is None
        rollback_replay = await rollback_proposal(proposal["id"], reviewer, session)
        assert rollback_replay["status"] == "rolled_back"

        history = list(await session.scalars(select(ObjectRelationshipHistory)))
        assert [event.action for event in history] == ["created", "rolled_back"]
        audits = list(await session.scalars(select(AuditEvent).where(AuditEvent.target_type == "change_proposal")))
        assert {event.action for event in audits} == {
            "change_proposal.created", "change_proposal.approved",
            "change_proposal.applied", "change_proposal.rolled_back",
        }
        listed = await list_proposals(None, 100, author, session)
        assert listed["count"] == 1
        assert listed["items"][0]["created_by"]["display_name"] == "Author"

    await engine.dispose()


def test_apply_rejects_graph_drift_after_approval() -> None:
    asyncio.run(exercise_drift_protection())


async def exercise_drift_protection() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with sessions() as session:
        entity = Entity(id="30000000-0000-0000-0000-000000000001", name="Drift Co")
        author = User(id="30000000-0000-0000-0000-000000000002", entity_id=entity.id, email="author@drift.test", display_name="Author", password_hash="x", role="admin")
        reviewer = User(id="30000000-0000-0000-0000-000000000003", entity_id=entity.id, email="reviewer@drift.test", display_name="Reviewer", password_hash="x", role="admin")
        project = Project(id="30000000-0000-0000-0000-000000000004", entity_id=entity.id, owner_id=author.id, title="Project", graph={"nodes": [], "edges": []})
        work = WorkItem(id="30000000-0000-0000-0000-000000000005", entity_id=entity.id, sequence_number=1, key="DRI-1", reporter_id=author.id,
                        project_id=project.id, summary="Task")
        relationship = ObjectRelationship(id="30000000-0000-0000-0000-000000000006", entity_id=entity.id, created_by_id=author.id,
                                          source_type="project", source_id=project.id,
                                          target_type="work_item", target_id=work.id,
                                          relationship_type="related_to", metadata_json={"version": 1})
        session.add_all([entity, author, reviewer, project, work, relationship])
        await session.commit()
        proposal = await create_proposal(ProposalCreate(
            title="Strengthen relationship", idempotency_key="governed:update:drift",
            operations=[GraphOperation(action="update", relationship_id=relationship.id,
                                       relationship_type="supports", metadata={"version": 2})],
        ), author, session)
        await decide_proposal(proposal["id"], ProposalDecision(decision="approved"), reviewer, session)
        relationship.metadata_json = {"version": 99}
        await session.commit()
        with pytest.raises(HTTPException) as drift:
            await apply_proposal(proposal["id"], reviewer, session)
        assert drift.value.status_code == 409
        assert "changed after review" in drift.value.detail

    await engine.dispose()
