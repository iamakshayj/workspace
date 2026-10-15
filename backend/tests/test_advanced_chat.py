import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import strawberry
from graphql import GraphQLError
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.app.database import Base, DirectMessage, Entity, Notification, User
from backend.app.graphql_schema import MessageAttachmentInput, Mutation, Query


def test_advanced_direct_chat_is_persistent_authorized_and_searchable(monkeypatch) -> None:
    asyncio.run(exercise_advanced_direct_chat(monkeypatch))


async def exercise_advanced_direct_chat(monkeypatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with sessions() as session:
        entity = Entity(id="chat-entity", name="Northwind")
        author = User(
            id="chat-author", entity_id=entity.id, email="author@example.com",
            display_name="Author", password_hash="test", role="admin",
        )
        recipient = User(
            id="chat-recipient", entity_id=entity.id, email="recipient@example.com",
            display_name="Recipient", password_hash="test", role="basic",
        )
        session.add_all([entity, author, recipient])
        await session.commit()
        monkeypatch.setattr("backend.app.graphql_schema.communication_hub.publish", AsyncMock())
        author_info = SimpleNamespace(context=SimpleNamespace(session=session, user=author))
        recipient_info = SimpleNamespace(context=SimpleNamespace(session=session, user=recipient))

        first = await Mutation().send_direct_message(
            author_info, strawberry.ID(recipient.id), "Launch plan is ready",
            attachments=[MessageAttachmentInput(name="Plan", url="https://example.com/plan")],
        )
        reply = await Mutation().send_direct_message(
            recipient_info, strawberry.ID(author.id), "I will review it",
            parent_id=strawberry.ID(str(first.id)),
        )
        assert str(reply.parent_id) == str(first.id)
        assert first.attachments[0].name == "Plan"

        await Mutation().toggle_chat_message_reaction(
            recipient_info, "direct", strawberry.ID(str(first.id)), "👍"
        )
        await Mutation().toggle_chat_message_pin(
            recipient_info, "direct", strawberry.ID(str(first.id))
        )
        assert await Mutation().toggle_chat_message_bookmark(
            recipient_info, "direct", strawberry.ID(str(first.id))
        ) is True
        await Mutation().update_chat_message(
            author_info, "direct", strawberry.ID(str(first.id)), "Launch plan is approved"
        )

        messages = await Query().direct_messages(
            recipient_info, strawberry.ID(author.id), limit=100
        )
        updated = next(item for item in messages if str(item.id) == str(first.id))
        assert updated.body == "Launch plan is approved"
        assert updated.edited_at is not None
        assert updated.pinned is True
        assert updated.bookmarked is True
        assert updated.reactions[0].count == 1
        assert updated.reactions[0].reacted_by_me is True

        results = await Query().message_search(recipient_info, "approved")
        assert [(result.kind, result.context_title, result.body) for result in results] == [
            ("direct", "Author", "Launch plan is approved")
        ]

        with pytest.raises(GraphQLError, match="Only the author"):
            await Mutation().delete_chat_message(
                recipient_info, "direct", strawberry.ID(str(first.id))
            )
        await Mutation().delete_chat_message(
            author_info, "direct", strawberry.ID(str(first.id))
        )
        stored = await session.scalar(select(DirectMessage).where(DirectMessage.id == str(first.id)))
        assert stored.deleted_at is not None
        assert stored.attachments == []

        channel = await Mutation().create_communication_channel(
            author_info, "Launch leads", "", "group", [strawberry.ID(recipient.id)]
        )
        channel_message = await Mutation().send_channel_message(
            author_info, channel.id, "@recipient-chat please review the approved plan"
        )
        mention = await session.scalar(select(Notification).where(Notification.kind == "chat_mention"))
        assert mention.user_id == recipient.id
        assert mention.communication_channel_id == str(channel.id)
        assert mention.communication_message_id == str(channel_message.id)

    await engine.dispose()
