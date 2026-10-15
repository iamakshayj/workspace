import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.app.database import Base, Entity, KnowledgeDocumentLink, Notification, User
from backend.app.identity import user_handle
from backend.app.knowledge import (
    AccessEntry,
    CommentCreate,
    DuplicateRequest,
    DocumentCreate,
    DocumentUpdate,
    FollowRequest,
    SpaceCreate,
    create_comment,
    create_document,
    create_space,
    duplicate_document,
    follow_document,
    get_document,
    update_document,
)


def test_versioned_knowledge_access_mentions_and_backlinks(monkeypatch) -> None:
    asyncio.run(exercise_knowledge(monkeypatch))


async def exercise_knowledge(monkeypatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with sessions() as session:
        entity = Entity(id="11111111-1111-1111-1111-111111111111", name="Northwind")
        admin = User(id="22222222-2222-2222-2222-222222222222", entity_id=entity.id,
                     email="admin@example.com", display_name="Admin", password_hash="x", role="admin")
        member = User(id="33333333-3333-3333-3333-333333333333", entity_id=entity.id,
                      email="member@example.com", display_name="Member", password_hash="x", role="basic")
        outsider_entity = Entity(id="44444444-4444-4444-4444-444444444444", name="Other")
        outsider = User(id="55555555-5555-5555-5555-555555555555", entity_id=outsider_entity.id,
                        email="outside@example.com", display_name="Outsider", password_hash="x", role="admin")
        session.add_all([entity, admin, member, outsider_entity, outsider])
        await session.commit()
        monkeypatch.setattr("backend.app.knowledge.communication_hub.publish", AsyncMock())

        space = await create_space(
            SpaceCreate(name="Operations", visibility="restricted",
                        members=[AccessEntry(user_id=member.id, role="editor")]),
            session, admin,
        )
        target = await create_document(
            DocumentCreate(space_id=space["id"], title="Runbook", visibility="restricted",
                           labels=["Operations", " operations ", "Runbook"], icon="📘",
                           access=[AccessEntry(user_id=member.id, role="viewer")]),
            session, admin,
        )
        source = await create_document(
            DocumentCreate(space_id=space["id"], title="Incident policy", visibility="restricted",
                           parent_id=target["id"],
                           body=f"See [[doc:{target['id']}]]", classification="confidential",
                           access=[AccessEntry(user_id=member.id, role="commenter")]),
            session, admin,
        )
        assert source["outbound_links"] == [{"id": target["id"], "title": "Runbook"}]
        assert source["parent_id"] == target["id"]
        assert target["labels"] == ["operations", "runbook"]
        assert target["icon"] == "📘"
        assert source["following"] is True
        link = await session.scalar(select(KnowledgeDocumentLink).where(
            KnowledgeDocumentLink.source_document_id == source["id"]
        ))
        assert link.target_document_id == target["id"]

        member_view = await get_document(source["id"], session, member)
        assert member_view["can_comment"] is True
        assert member_view["can_edit"] is False
        with pytest.raises(HTTPException) as denied:
            await get_document(source["id"], session, outsider)
        assert denied.value.status_code == 404

        comment = await create_comment(
            source["id"], CommentCreate(body=f"@{user_handle(member)} please verify"), session, admin,
        )
        assert comment["author"]["id"] == admin.id
        notification = await session.scalar(select(Notification).where(Notification.kind == "document_mention"))
        assert notification.user_id == member.id
        assert notification.document_id == source["id"]

        updated = await update_document(
            source["id"], DocumentUpdate(expected_revision=source["revision"], status="published",
                                          change_summary="Approved policy"), session, admin,
        )
        assert updated["revision"] == source["revision"] + 1
        assert updated["revisions"][0]["change_summary"] == "Approved policy"
        with pytest.raises(HTTPException) as conflict:
            await update_document(
                source["id"], DocumentUpdate(expected_revision=source["revision"], title="Stale edit"),
                session, admin,
            )
        assert conflict.value.status_code == 409

        with pytest.raises(HTTPException) as circular:
            await update_document(
                target["id"], DocumentUpdate(expected_revision=target["revision"], parent_id=source["id"]),
                session, admin,
            )
        assert circular.value.status_code == 400

        unfollowed = await follow_document(
            source["id"], FollowRequest(following=False), session, admin,
        )
        assert unfollowed["following"] is False
        copied = await duplicate_document(
            source["id"], DuplicateRequest(title="Incident policy playbook"), session, admin,
        )
        assert copied["title"] == "Incident policy playbook"
        assert copied["status"] == "draft"
        assert copied["parent_id"] == target["id"]

    await engine.dispose()
