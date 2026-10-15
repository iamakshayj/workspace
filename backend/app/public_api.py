"""Versioned service-token API with scope and tenant enforcement."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from secrets import compare_digest
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings, get_settings
from .database import ApiAccessToken, Entity, KnowledgeDocument, Project, User, WorkItem, get_session
from .policy_engine import PolicyContext, evaluate_policy, load_policy_snapshot
from .work_graph import build_access_scope, can_view_object, object_summary


router = APIRouter(prefix="/public/v1", tags=["public API"])


class ApiPrincipal:
    def __init__(self, user: User, token: ApiAccessToken) -> None:
        self.user = user
        self.token = token

    def require(self, scope: str) -> None:
        if scope not in set(self.token.scopes or []):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"message": "API token does not include the required scope", "code": "scope_required", "scope": scope},
            )


async def api_principal(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ApiPrincipal:
    scheme, _, raw = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not raw.startswith("wsp_") or len(raw) < 32:
        raise HTTPException(status_code=401, detail="A valid Workspace API bearer token is required")
    digest = sha256(raw.encode()).hexdigest()
    token = await session.scalar(select(ApiAccessToken).where(ApiAccessToken.token_hash == digest))
    now = datetime.now(timezone.utc)
    if (
        not token or not compare_digest(token.token_hash, digest) or token.revoked_at
        or (token.expires_at and token.expires_at.replace(tzinfo=token.expires_at.tzinfo or timezone.utc) <= now)
    ):
        raise HTTPException(status_code=401, detail="API token is expired, revoked, or invalid")
    user = await session.get(User, token.created_by_id)
    if not user or user.entity_id != token.entity_id or user.account_status != "active":
        raise HTTPException(status_code=401, detail="API token owner is inactive")
    entity = await session.get(Entity, token.entity_id)
    if not entity or entity.data_region != settings.deployment_region:
        raise HTTPException(status_code=403, detail="This workspace is assigned to a different data-residency deployment")
    last_used = token.last_used_at.replace(tzinfo=token.last_used_at.tzinfo or timezone.utc) if token.last_used_at else None
    if not last_used or last_used < now - timedelta(minutes=5):
        token.last_used_at = now
        await session.commit()
    request.state.api_token_id = token.id
    request.state.api_scopes = list(token.scopes or [])
    return ApiPrincipal(user, token)


@router.get("/projects")
async def api_projects(
    principal: ApiPrincipal = Depends(api_principal),
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=1_000_000),
) -> dict:
    principal.require("projects:read")
    user = principal.user
    access_scope = await build_access_scope(session, user)
    policy_snapshot = await load_policy_snapshot(session, user)
    rows = list(await session.scalars(select(Project).where(Project.entity_id == user.entity_id).order_by(Project.updated_at.desc(), Project.id).offset(offset).limit(limit + 1)))
    results = []
    for item in rows:
        if not await can_view_object(session, user, "project", item, access_scope):
            continue
        decision = await evaluate_policy(session, user, PolicyContext(
            action="read", resource_type="project", resource_id=item.id, project_id=item.id,
            classification=str((item.profile or {}).get("classification") or "internal"),
            source_type="public_api", preauthorized=True,
        ), snapshot=policy_snapshot)
        if decision.allowed:
            results.append(object_summary("project", item))
        if len(results) >= limit:
            break
    return {"data": results, "offset": offset, "limit": limit, "has_more": len(rows) > limit}


@router.get("/work-items")
async def api_work_items(
    principal: ApiPrincipal = Depends(api_principal),
    session: AsyncSession = Depends(get_session),
    project_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=1_000_000),
) -> dict:
    principal.require("work:read")
    user = principal.user
    access_scope = await build_access_scope(session, user)
    policy_snapshot = await load_policy_snapshot(session, user)
    query = select(WorkItem).where(WorkItem.entity_id == user.entity_id, WorkItem.archived.is_(False))
    if project_id:
        query = query.where(WorkItem.project_id == project_id)
    rows = list(await session.scalars(query.order_by(WorkItem.updated_at.desc(), WorkItem.id).offset(offset).limit(limit + 1)))
    results = []
    for item in rows:
        if not await can_view_object(session, user, "work_item", item, access_scope):
            continue
        decision = await evaluate_policy(session, user, PolicyContext(
            action="read", resource_type="work_item", resource_id=item.id, project_id=item.project_id,
            source_type="public_api", preauthorized=True,
        ), snapshot=policy_snapshot)
        if decision.allowed:
            results.append(object_summary("work_item", item))
        if len(results) >= limit:
            break
    return {"data": results, "offset": offset, "limit": limit, "has_more": len(rows) > limit}


@router.get("/documents")
async def api_documents(
    principal: ApiPrincipal = Depends(api_principal),
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=1_000_000),
) -> dict:
    principal.require("documents:read")
    user = principal.user
    access_scope = await build_access_scope(session, user)
    policy_snapshot = await load_policy_snapshot(session, user)
    rows = list(await session.scalars(select(KnowledgeDocument).where(
        KnowledgeDocument.entity_id == user.entity_id, KnowledgeDocument.status != "archived",
    ).order_by(KnowledgeDocument.updated_at.desc(), KnowledgeDocument.id).offset(offset).limit(limit + 1)))
    results = []
    for item in rows:
        if not await can_view_object(session, user, "document", item, access_scope):
            continue
        decision = await evaluate_policy(session, user, PolicyContext(
            action="read", resource_type="document", resource_id=item.id,
            classification=item.classification, source_type="public_api", preauthorized=True,
        ), snapshot=policy_snapshot)
        if decision.allowed:
            results.append(object_summary("document", item))
        if len(results) >= limit:
            break
    return {"data": results, "offset": offset, "limit": limit, "has_more": len(rows) > limit}
