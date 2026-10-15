"""Tenant-isolated service desk, SLA tracking, on-call, and guest sharing."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from secrets import token_urlsafe
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import get_current_user
from .config import Settings, get_settings
from .database import (
    CalendarEvent, GuestAccessGrant, GuestPortalActivity, KnowledgeDocument, Notification,
    OnCallSchedule, Project, ServiceTicket, ServiceTicketComment, User, get_session,
)
from .governance import record_audit_event


router = APIRouter(prefix="/service-desk", tags=["service desk"])
public_router = APIRouter(prefix="/public/guest", tags=["guest portal"])

SLA_MINUTES = {"critical": (15, 240), "high": (60, 480), "normal": (240, 2880), "low": (480, 7200)}
TICKET_STATUSES = {"open", "triage", "in_progress", "waiting", "resolved", "closed"}
GUEST_PERMISSIONS = {"view", "comment", "approve"}


def utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


class TicketCreate(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    description: str = Field(default="", max_length=50_000)
    ticket_type: Literal["request", "incident", "problem", "change"] = "request"
    severity: Literal["critical", "high", "normal", "low"] = "normal"
    priority: Literal["urgent", "high", "medium", "low"] = "medium"
    service: str = Field(default="workspace", min_length=1, max_length=80)
    assignee_id: str | None = None
    project_id: str | None = None
    tags: list[str] = Field(default_factory=list, max_length=30)
    custom_fields: dict[str, Any] = Field(default_factory=dict)


class TicketUpdate(BaseModel):
    status: Literal["open", "triage", "in_progress", "waiting", "resolved", "closed"] | None = None
    severity: Literal["critical", "high", "normal", "low"] | None = None
    priority: Literal["urgent", "high", "medium", "low"] | None = None
    assignee_id: str | None = None
    service: str | None = Field(default=None, min_length=1, max_length=80)
    custom_fields: dict[str, Any] | None = None


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=20_000)
    internal: bool = False


class OnCallWrite(BaseModel):
    service: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=2, max_length=160)
    member_ids: list[str] = Field(min_length=1, max_length=100)
    timezone: str = Field(default="UTC", max_length=64)
    rotation: dict[str, Any] = Field(default_factory=lambda: {"cadence": "weekly"})
    active: bool = True


class GuestGrantWrite(BaseModel):
    guest_email: str = Field(min_length=3, max_length=320)
    guest_name: str = Field(default="", max_length=120)
    resource_type: Literal["project", "document", "meeting", "ticket"]
    resource_id: str = Field(min_length=1, max_length=80)
    permissions: list[Literal["view", "comment", "approve"]] = Field(default_factory=lambda: ["view"])
    expires_in_hours: int = Field(default=168, ge=1, le=24 * 90)

    @field_validator("guest_email")
    @classmethod
    def email_shape(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("Enter a valid guest email")
        return normalized


class GuestActionWrite(BaseModel):
    action: Literal["comment", "approve"]
    body: str = Field(default="", max_length=20_000)

    @model_validator(mode="after")
    def require_comment_body(self) -> "GuestActionWrite":
        if self.action == "comment" and not self.body.strip():
            raise ValueError("A comment cannot be empty")
        return self


async def entity_user(user_id: str | None, user: User, session: AsyncSession) -> User | None:
    if not user_id:
        return None
    item = await session.get(User, user_id)
    if not item or item.entity_id != user.entity_id or item.account_status != "active":
        raise HTTPException(status_code=422, detail="Assignee must be an active workspace user")
    return item


async def ticket_or_404(ticket_id: str, user: User, session: AsyncSession) -> ServiceTicket:
    item = await session.get(ServiceTicket, ticket_id)
    if not item or item.entity_id != user.entity_id:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return item


def ticket_dict(item: ServiceTicket, users: dict[str, User], now: datetime | None = None) -> dict[str, Any]:
    moment = now or datetime.now(timezone.utc)
    response_due, resolution_due = utc(item.response_due_at), utc(item.resolution_due_at)
    return {
        "id": item.id, "title": item.title, "description": item.description, "ticket_type": item.ticket_type,
        "status": item.status, "severity": item.severity, "priority": item.priority, "service": item.service,
        "source": item.source, "project_id": item.project_id, "tags": item.tags, "custom_fields": item.custom_fields,
        "requester": user_dict(users.get(item.requester_id)), "assignee": user_dict(users.get(item.assignee_id)),
        "external_requester_email": item.external_requester_email, "response_due_at": response_due,
        "resolution_due_at": resolution_due, "first_response_at": utc(item.first_response_at), "resolved_at": utc(item.resolved_at),
        "response_breached": bool(not item.first_response_at and response_due and response_due < moment),
        "resolution_breached": bool(item.status not in {"resolved", "closed"} and resolution_due and resolution_due < moment),
        "created_at": utc(item.created_at), "updated_at": utc(item.updated_at),
    }


def user_dict(item: User | None) -> dict[str, str] | None:
    return {"id": item.id, "display_name": item.display_name, "email": item.email} if item else None


@router.get("")
async def list_tickets(
    status_filter: str | None = Query(default=None, alias="status"), assignee_id: str | None = None,
    search: str = Query(default="", max_length=200), user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    query = select(ServiceTicket).where(ServiceTicket.entity_id == user.entity_id)
    if status_filter:
        if status_filter not in TICKET_STATUSES: raise HTTPException(status_code=422, detail="Unsupported ticket status")
        query = query.where(ServiceTicket.status == status_filter)
    if assignee_id == "me": query = query.where(ServiceTicket.assignee_id == user.id)
    elif assignee_id: query = query.where(ServiceTicket.assignee_id == assignee_id)
    if search.strip():
        term = f"%{search.strip()}%"
        query = query.where(or_(ServiceTicket.title.ilike(term), ServiceTicket.description.ilike(term), ServiceTicket.service.ilike(term)))
    items = list(await session.scalars(query.order_by(ServiceTicket.updated_at.desc()).limit(1000)))
    user_ids = {value for item in items for value in (item.requester_id, item.assignee_id) if value}
    users = {item.id: item for item in await session.scalars(select(User).where(User.id.in_(user_ids)))} if user_ids else {}
    serialized = [ticket_dict(item, users) for item in items]
    return {"items": serialized, "summary": {"total": len(items), "open": sum(item["status"] not in {"resolved", "closed"} for item in serialized), "sla_breached": sum(item["response_breached"] or item["resolution_breached"] for item in serialized)}}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_ticket(payload: TicketCreate, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    assignee = await entity_user(payload.assignee_id, user, session)
    if payload.project_id:
        project = await session.get(Project, payload.project_id)
        if not project or project.entity_id != user.entity_id: raise HTTPException(status_code=422, detail="Project not found")
    now = datetime.now(timezone.utc); response_minutes, resolution_minutes = SLA_MINUTES[payload.severity]
    item = ServiceTicket(entity_id=user.entity_id, requester_id=user.id, assignee_id=assignee.id if assignee else None,
        project_id=payload.project_id, title=payload.title.strip(), description=payload.description.strip(), ticket_type=payload.ticket_type,
        severity=payload.severity, priority=payload.priority, service=payload.service.strip(), tags=sorted(set(payload.tags)), custom_fields=payload.custom_fields,
        response_due_at=now + timedelta(minutes=response_minutes), resolution_due_at=now + timedelta(minutes=resolution_minutes), created_at=now, updated_at=now)
    session.add(item); await session.flush()
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="service_ticket.created", target_type="service_ticket", target_id=item.id, details={"type": item.ticket_type, "severity": item.severity})
    if assignee and assignee.id != user.id:
        session.add(Notification(entity_id=user.entity_id, user_id=assignee.id, actor_id=user.id, kind="assignment", title=f"Service ticket assigned · {item.title}", body=f"{item.severity.title()} {item.ticket_type} for {item.service}", group_key=f"service-ticket:{item.id}"))
    await session.commit()
    return ticket_dict(item, {user.id: user, **({assignee.id: assignee} if assignee else {})})


@router.patch("/{ticket_id}")
async def update_ticket(ticket_id: str, payload: TicketUpdate, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    item = await ticket_or_404(ticket_id, user, session)
    if user.role != "admin" and user.id not in {item.requester_id, item.assignee_id}:
        raise HTTPException(status_code=403, detail="Only the requester, assignee, or an administrator can update this ticket")
    previous_status = item.status
    if "assignee_id" in payload.model_fields_set:
        assignee = await entity_user(payload.assignee_id, user, session)
        item.assignee_id = assignee.id if assignee else None
    for field in ("status", "severity", "priority", "service", "custom_fields"):
        value = getattr(payload, field)
        if value is not None: setattr(item, field, value)
    now = datetime.now(timezone.utc)
    if previous_status == "open" and item.status != "open" and not item.first_response_at: item.first_response_at = now
    if item.status in {"resolved", "closed"}: item.resolved_at = item.resolved_at or now
    elif previous_status in {"resolved", "closed"}: item.resolved_at = None
    item.updated_at = now
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="service_ticket.updated", target_type="service_ticket", target_id=item.id, details={"from": previous_status, "to": item.status, "assignee_id": item.assignee_id})
    await session.commit()
    users = {candidate.id: candidate for candidate in await session.scalars(select(User).where(User.id.in_([value for value in (item.requester_id, item.assignee_id) if value])))}
    return ticket_dict(item, users)


@router.get("/{ticket_id}/comments")
async def ticket_comments(ticket_id: str, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> list[dict[str, Any]]:
    await ticket_or_404(ticket_id, user, session)
    comments = list(await session.scalars(select(ServiceTicketComment).where(ServiceTicketComment.ticket_id == ticket_id).order_by(ServiceTicketComment.created_at)))
    author_ids = {item.author_id for item in comments if item.author_id}
    users = {item.id: item for item in await session.scalars(select(User).where(User.id.in_(author_ids)))} if author_ids else {}
    return [{"id": item.id, "body": item.body, "internal": item.internal, "author": user_dict(users.get(item.author_id)), "external_author": item.external_author, "created_at": utc(item.created_at)} for item in comments]


@router.post("/{ticket_id}/comments", status_code=201)
async def add_ticket_comment(ticket_id: str, payload: CommentCreate, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    item = await ticket_or_404(ticket_id, user, session)
    comment = ServiceTicketComment(ticket_id=item.id, entity_id=user.entity_id, author_id=user.id, body=payload.body.strip(), internal=payload.internal)
    session.add(comment); item.first_response_at = item.first_response_at or datetime.now(timezone.utc); item.updated_at = datetime.now(timezone.utc)
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="service_ticket.commented", target_type="service_ticket", target_id=item.id, details={"internal": payload.internal})
    await session.commit()
    return {"id": comment.id, "body": comment.body, "internal": comment.internal, "author": user_dict(user), "created_at": utc(comment.created_at)}


@router.get("/configuration/on-call")
async def list_on_call(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> list[dict[str, Any]]:
    items = await session.scalars(select(OnCallSchedule).where(OnCallSchedule.entity_id == user.entity_id).order_by(OnCallSchedule.service, OnCallSchedule.name))
    return [{"id": item.id, "service": item.service, "name": item.name, "member_ids": item.member_ids, "timezone": item.timezone, "rotation": item.rotation, "active": item.active} for item in items]


@router.post("/configuration/on-call", status_code=201)
async def create_on_call(payload: OnCallWrite, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    if user.role != "admin": raise HTTPException(status_code=403, detail="Administrator access required")
    members = list(await session.scalars(select(User).where(User.entity_id == user.entity_id, User.id.in_(set(payload.member_ids)), User.account_status == "active")))
    if len(members) != len(set(payload.member_ids)): raise HTTPException(status_code=422, detail="Every on-call member must be an active workspace user")
    item = OnCallSchedule(entity_id=user.entity_id, service=payload.service.strip(), name=payload.name.strip(), member_ids=sorted(set(payload.member_ids)), timezone=payload.timezone, rotation=payload.rotation, active=payload.active, created_by_id=user.id)
    session.add(item); record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="on_call.created", target_type="on_call_schedule", target_id=item.id, details={"service": item.service})
    await session.commit()
    return {"id": item.id, "service": item.service, "name": item.name, "member_ids": item.member_ids, "timezone": item.timezone, "rotation": item.rotation, "active": item.active}


async def resolve_guest_resource(grant: GuestAccessGrant, session: AsyncSession) -> dict[str, Any]:
    model = {"project": Project, "document": KnowledgeDocument, "meeting": CalendarEvent, "ticket": ServiceTicket}[grant.resource_type]
    item = await session.get(model, grant.resource_id)
    if not item or getattr(item, "entity_id", None) != grant.entity_id: raise HTTPException(status_code=404, detail="Shared resource is no longer available")
    return {"id": item.id, "type": grant.resource_type, "title": getattr(item, "title", None) or getattr(item, "summary", None) or "Shared resource", "description": getattr(item, "description", "") or getattr(item, "summary", ""), "status": getattr(item, "status", None)}


async def guest_grant(token: str, session: AsyncSession) -> GuestAccessGrant:
    digest = sha256(token.encode()).hexdigest(); now = datetime.now(timezone.utc)
    grant = await session.scalar(select(GuestAccessGrant).where(GuestAccessGrant.token_hash == digest))
    if not grant or grant.revoked_at or (utc(grant.expires_at) and utc(grant.expires_at) <= now): raise HTTPException(status_code=404, detail="This guest link is invalid or expired")
    return grant


@router.get("/configuration/guest-grants")
async def list_guest_grants(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> list[dict[str, Any]]:
    items = await session.scalars(select(GuestAccessGrant).where(GuestAccessGrant.entity_id == user.entity_id).order_by(GuestAccessGrant.created_at.desc()).limit(500))
    return [{"id": item.id, "guest_email": item.guest_email, "guest_name": item.guest_name, "resource_type": item.resource_type, "resource_id": item.resource_id, "permissions": item.permissions, "expires_at": utc(item.expires_at), "revoked_at": utc(item.revoked_at), "last_accessed_at": utc(item.last_accessed_at)} for item in items]


@router.post("/configuration/guest-grants", status_code=201)
async def create_guest_grant(payload: GuestGrantWrite, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    if user.role != "admin": raise HTTPException(status_code=403, detail="Administrator access required")
    raw_token = token_urlsafe(32); now = datetime.now(timezone.utc)
    grant = GuestAccessGrant(entity_id=user.entity_id, guest_email=payload.guest_email, guest_name=payload.guest_name.strip(), resource_type=payload.resource_type, resource_id=payload.resource_id, permissions=sorted(set(payload.permissions) | {"view"}), token_hash=sha256(raw_token.encode()).hexdigest(), created_by_id=user.id, expires_at=now + timedelta(hours=payload.expires_in_hours), created_at=now)
    await resolve_guest_resource(grant, session)
    session.add(grant); record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="guest_access.created", target_type=payload.resource_type, target_id=payload.resource_id, details={"grant_id": grant.id, "permissions": grant.permissions, "expires_at": grant.expires_at.isoformat()})
    await session.commit()
    return {"id": grant.id, "url": f"{settings.frontend_url.rstrip('/')}/guest/{raw_token}", "guest_email": grant.guest_email, "permissions": grant.permissions, "expires_at": grant.expires_at}


@router.post("/configuration/guest-grants/{grant_id}/revoke")
async def revoke_guest_grant(grant_id: str, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    if user.role != "admin": raise HTTPException(status_code=403, detail="Administrator access required")
    grant = await session.get(GuestAccessGrant, grant_id)
    if not grant or grant.entity_id != user.entity_id: raise HTTPException(status_code=404, detail="Guest grant not found")
    grant.revoked_at = datetime.now(timezone.utc); record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="guest_access.revoked", target_type=grant.resource_type, target_id=grant.resource_id, details={"grant_id": grant.id})
    await session.commit(); return {"id": grant.id, "revoked_at": grant.revoked_at}


@public_router.get("/{token}")
async def view_guest_resource(token: str, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    grant = await guest_grant(token, session); grant.last_accessed_at = datetime.now(timezone.utc)
    resource = await resolve_guest_resource(grant, session)
    activities = list(await session.scalars(select(GuestPortalActivity).where(GuestPortalActivity.grant_id == grant.id).order_by(GuestPortalActivity.created_at)))
    await session.commit()
    return {"guest": {"name": grant.guest_name, "email": grant.guest_email}, "permissions": grant.permissions, "expires_at": utc(grant.expires_at), "resource": resource, "activity": [{"id": item.id, "action": item.action, "body": item.body, "created_at": utc(item.created_at)} for item in activities]}


@public_router.post("/{token}/actions", status_code=201)
async def guest_action(token: str, payload: GuestActionWrite, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    grant = await guest_grant(token, session)
    required = "comment" if payload.action == "comment" else "approve"
    if required not in grant.permissions: raise HTTPException(status_code=403, detail=f"This link does not allow {required} actions")
    activity = GuestPortalActivity(grant_id=grant.id, entity_id=grant.entity_id, action=payload.action, body=payload.body.strip(), metadata_json={"guest_email": grant.guest_email})
    session.add(activity); record_audit_event(session, entity_id=grant.entity_id, actor_id=None, action=f"guest.{payload.action}", target_type=grant.resource_type, target_id=grant.resource_id, details={"grant_id": grant.id, "guest_email_hash": sha256(grant.guest_email.encode()).hexdigest()})
    if grant.resource_type == "ticket" and payload.action == "comment": session.add(ServiceTicketComment(ticket_id=grant.resource_id, entity_id=grant.entity_id, external_author=grant.guest_email, body=payload.body.strip(), internal=False))
    await session.commit(); return {"id": activity.id, "action": activity.action, "created_at": activity.created_at}
