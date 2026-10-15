import asyncio
from datetime import datetime, timedelta, timezone
from hashlib import sha256

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from backend.app.config import Settings
from backend.app.database import ApiAccessToken, Base, Entity, Project, User
from backend.app.public_api import api_principal, api_projects


def request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/public/v1/projects", "headers": []})


def test_public_api_token_is_scoped_tenant_bound_revocable_and_residency_checked() -> None:
    asyncio.run(scenario())


async def scenario() -> None:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    raw = "wsp_" + "x" * 48
    settings = Settings(deployment_region="us-central")
    async with sessions() as session:
        entity = Entity(id="tenant-a", name="Tenant A", data_region="us-central")
        other = Entity(id="tenant-b", name="Tenant B", data_region="us-central")
        admin = User(id="admin", entity_id=entity.id, email="admin@a.test", display_name="Admin", password_hash="x", role="admin")
        other_admin = User(id="other", entity_id=other.id, email="admin@b.test", display_name="Other", password_hash="x", role="admin")
        token = ApiAccessToken(
            id="token", entity_id=entity.id, name="Reports", token_prefix=raw[:12],
            token_hash=sha256(raw.encode()).hexdigest(), scopes=["projects:read"],
            created_by_id=admin.id, expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )
        session.add_all([
            entity, other, admin, other_admin, token,
            Project(id="project-a", entity_id=entity.id, owner_id=admin.id, title="Visible", graph={"nodes": [], "edges": []}),
            Project(id="project-b", entity_id=other.id, owner_id=other_admin.id, title="Never visible", graph={"nodes": [], "edges": []}),
        ])
        await session.commit()

        principal = await api_principal(request(), f"Bearer {raw}", session, settings)
        page = await api_projects(principal, session, limit=100, offset=0)
        assert [item["id"] for item in page["data"]] == ["project-a"]
        with pytest.raises(HTTPException) as scope_error:
            principal.require("work:read")
        assert scope_error.value.status_code == 403

        token.revoked_at = datetime.now(timezone.utc)
        await session.commit()
        with pytest.raises(HTTPException) as revoked:
            await api_principal(request(), f"Bearer {raw}", session, settings)
        assert revoked.value.status_code == 401

        token.revoked_at = None
        entity.data_region = "eu-west"
        await session.commit()
        with pytest.raises(HTTPException) as residency:
            await api_principal(request(), f"Bearer {raw}", session, settings)
        assert residency.value.status_code == 403
    await engine.dispose()
