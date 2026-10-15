import asyncio
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.app.config import Settings
from backend.app.database import Base, Entity, GuestAccessGrant, Project, ServiceTicketComment, User
from backend.app.service_desk import (
    CommentCreate, GuestActionWrite, GuestGrantWrite, OnCallWrite, TicketCreate, TicketUpdate,
    add_ticket_comment, create_guest_grant, create_on_call, create_ticket, guest_action,
    list_tickets, update_ticket, view_guest_resource,
)


def test_service_desk_and_guest_portal_lifecycle() -> None:
    asyncio.run(exercise_service_desk())


async def exercise_service_desk() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as session:
        entity = Entity(id="entity", name="Example")
        admin = User(id="admin", entity_id="entity", email="admin@example.com", display_name="Admin", password_hash="x", role="admin")
        agent = User(id="agent", entity_id="entity", email="agent@example.com", display_name="Support Agent", password_hash="x", role="basic")
        project = Project(id="project", entity_id="entity", owner_id="admin", title="Portal launch", graph={"nodes": [], "edges": []})
        session.add_all([entity, admin, agent, project]); await session.commit()

        ticket = await create_ticket(TicketCreate(title="Production login unavailable", description="Customers cannot sign in", ticket_type="incident", severity="critical", priority="urgent", service="identity", assignee_id="agent", project_id="project"), admin, session)
        assert ticket["assignee"]["id"] == "agent"
        assert ticket["response_breached"] is False
        summary = await list_tickets(None, None, "login", admin, session)
        assert summary["summary"] == {"total": 1, "open": 1, "sla_breached": 0}

        updated = await update_ticket(ticket["id"], TicketUpdate(status="in_progress"), agent, session)
        assert updated["first_response_at"] is not None
        unassigned = await update_ticket(ticket["id"], TicketUpdate(assignee_id=None), admin, session)
        assert unassigned["assignee"] is None
        await update_ticket(ticket["id"], TicketUpdate(assignee_id="agent"), admin, session)
        comment = await add_ticket_comment(ticket["id"], CommentCreate(body="Investigating identity provider health"), agent, session)
        assert comment["author"]["id"] == "agent"

        schedule = await create_on_call(OnCallWrite(service="identity", name="Identity primary", member_ids=["agent"]), admin, session)
        assert schedule["member_ids"] == ["agent"]

        settings = Settings(frontend_url="https://workspace.example.com", auth_secret="test-secret-at-least-thirty-two-characters")
        grant_result = await create_guest_grant(GuestGrantWrite(guest_email="customer@example.com", guest_name="Customer", resource_type="ticket", resource_id=ticket["id"], permissions=["view", "comment"], expires_in_hours=24), admin, session, settings)
        token = grant_result["url"].rsplit("/", 1)[-1]
        guest_view = await view_guest_resource(token, session)
        assert guest_view["resource"]["type"] == "ticket"
        assert "comment" in guest_view["permissions"]
        action = await guest_action(token, GuestActionWrite(action="comment", body="Service is working again"), session)
        assert action["action"] == "comment"
        external_comment = await session.scalar(select(ServiceTicketComment).where(ServiceTicketComment.external_author == "customer@example.com"))
        assert external_comment and external_comment.internal is False
        with pytest.raises(ValueError):
            GuestActionWrite(action="comment", body="  ")

        grant = await session.scalar(select(GuestAccessGrant))
        grant.revoked_at = datetime.now(timezone.utc); await session.commit()
        with pytest.raises(HTTPException) as invalid:
            await view_guest_resource(token, session)
        assert invalid.value.status_code == 404
    await engine.dispose()
