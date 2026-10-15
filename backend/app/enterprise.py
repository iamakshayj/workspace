import csv
import io
import json
import re
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import get_current_user
from .database import (
    AgileRelease, AgileSprint, ApprovalDefinition, ApprovalInstance, AuditEvent, CalendarEvent,
    CalendarEventAttendee, Entity,
    KnowledgeDocument, Notification, NotificationPreference, ObjectRelationship,
    OrganizationUnit, OrganizationUnitMember, Project, ProjectCollaborator, ProjectGroupAccess, ProjectDecision, ProjectRisk,
    SavedWorkspaceView, User, WorkItem, WorkItemActivity, WorkspaceDashboard, WorkspaceFile,
    get_session,
)
from .governance import can_edit_project, project_access_role, record_audit_event
from .identity import as_utc, user_summary
from .work_graph import (
    RelationshipCreate as CanonicalRelationshipCreate,
    create_graph_relationship,
    delete_graph_relationship,
)

router = APIRouter(prefix="/enterprise", tags=["enterprise workspace"])
OBJECT_TYPES = {"organization", "unit", "team", "employee", "project", "work_item", "sprint", "release", "meeting", "document", "file", "decision", "risk", "approval", "workflow", "custom"}
RELATIONSHIP_TYPES = {"parent_of", "child_of", "belongs_to", "owned_by", "assigned_to", "blocked_by", "blocks", "depends_on", "required_by", "related_to", "supports", "contributes_to", "discussed_in", "decided_in", "created_from", "approved_by", "reviewed_by", "mentioned_in", "documented_by", "impacts"}
NOTIFICATION_KINDS = ["assignment", "mention", "comment", "deadline", "approval", "meeting", "risk", "dependency", "workflow", "ai_alert", "chat"]


class OrgUnitWrite(BaseModel):
    name: str = Field(min_length=2, max_length=140)
    unit_type: Literal["business_unit", "department", "team", "group"] = "team"
    description: str = Field(default="", max_length=500)
    parent_id: str | None = None
    manager_id: str | None = None
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    weekly_capacity_hours: float = Field(default=40, ge=0, le=168)
    members: list[dict[str, Any]] = Field(default_factory=list, max_length=1000)

    @field_validator("name", "description")
    @classmethod
    def trim(cls, value: str) -> str:
        return value.strip()


class ProfileWrite(BaseModel):
    job_title: str = Field(default="", max_length=120)
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    manager_id: str | None = None
    skills: list[str] = Field(default_factory=list, max_length=100)
    weekly_capacity_hours: float = Field(default=40, ge=0, le=168)
    profile: dict[str, Any] = Field(default_factory=dict)


class RelationshipWrite(BaseModel):
    source_type: str
    source_id: str
    target_type: str
    target_id: str
    relationship_type: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_relationship(self) -> "RelationshipWrite":
        if self.source_type not in OBJECT_TYPES or self.target_type not in OBJECT_TYPES:
            raise ValueError("Unsupported object type")
        if self.relationship_type not in RELATIONSHIP_TYPES:
            raise ValueError("Unsupported relationship type")
        if self.source_type == self.target_type and self.source_id == self.target_id:
            raise ValueError("An object cannot relate to itself")
        return self


class RiskWrite(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    description: str = Field(default="", max_length=20_000)
    owner_id: str | None = None
    probability: int = Field(default=1, ge=1, le=5)
    impact: int = Field(default=1, ge=1, le=5)
    status: Literal["open", "mitigating", "accepted", "closed"] = "open"
    mitigation: str = Field(default="", max_length=20_000)
    due_date: date | None = None


class DecisionWrite(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    context: str = Field(default="", max_length=20_000)
    decision: str = Field(default="", max_length=20_000)
    alternatives: list[str] = Field(default_factory=list, max_length=50)
    consequences: str = Field(default="", max_length=20_000)
    status: Literal["proposed", "accepted", "rejected", "superseded"] = "proposed"


class ProjectSettingsWrite(BaseModel):
    workflow: dict[str, Any] = Field(default_factory=dict)
    fields: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    notifications: dict[str, Any] = Field(default_factory=dict)
    integrations: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    automations: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    permissions: dict[str, Any] = Field(default_factory=dict)


class ProjectGroupAccessWrite(BaseModel):
    unit_id: str
    access_role: Literal["viewer", "commenter", "editor", "approver"] = "viewer"


class PreferenceWrite(BaseModel):
    kind: str = Field(min_length=1, max_length=40)
    in_app: bool = True
    email: bool = False
    push: bool = False
    digest: Literal["none", "daily", "weekly"] = "none"
    muted: bool = False


class SnoozeWrite(BaseModel):
    until: datetime | None = None


class ViewWrite(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    view_type: Literal["board", "grid", "calendar", "timeline", "gantt", "form", "report", "bulk_selection"]
    scope_type: str = Field(default="workspace", max_length=40)
    scope_id: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    shared: bool = False
    is_default: bool = False


class DashboardWrite(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    widgets: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    layout: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    shared: bool = False
    delivery: dict[str, Any] = Field(default_factory=dict)


class FileWrite(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    item_type: Literal["file", "folder", "external"] = "external"
    parent_id: str | None = None
    external_url: str = Field(default="", max_length=1000)
    provider: Literal["workspace", "sharepoint", "onedrive", "google_drive", "box", "url"] = "url"
    mime_type: str = Field(default="application/octet-stream", max_length=160)
    classification: Literal["public", "internal", "confidential", "restricted"] = "internal"
    tags: list[str] = Field(default_factory=list, max_length=50)
    visibility: Literal["workspace", "restricted"] = "workspace"
    description: str = Field(default="", max_length=10_000)
    content_text: str = Field(default="", max_length=1_000_000)
    preview_url: str = Field(default="", max_length=1000)
    shared_with_ids: list[str] = Field(default_factory=list, max_length=1000)


class ApprovalDefinitionWrite(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    target_types: list[str] = Field(min_length=1, max_length=30)
    stages: list[dict[str, Any]] = Field(min_length=1, max_length=20)
    reminder_hours: int = Field(default=24, ge=1, le=8760)
    escalation_hours: int = Field(default=72, ge=1, le=8760)
    active: bool = True


class ApprovalRequestWrite(BaseModel):
    definition_id: str
    target_type: str
    target_id: str
    due_at: datetime | None = None


class ApprovalDecisionWrite(BaseModel):
    decision: Literal["approved", "rejected", "changes_requested", "delegated"]
    note: str = Field(default="", max_length=5000)
    delegate_to_id: str | None = None


class AccessRequestWrite(BaseModel):
    project_id: str
    requested_role: Literal["viewer", "commenter", "editor", "approver"] = "viewer"
    reason: str = Field(default="", max_length=2000)


class MeetingIntelligenceWrite(BaseModel):
    agenda: str = Field(default="", max_length=50_000)
    notes: str = Field(default="", max_length=200_000)
    action_items: list[dict[str, Any]] = Field(default_factory=list, max_length=500)
    transcript: str = Field(default="", max_length=1_000_000)
    recording_url: str = Field(default="", max_length=1000)


class MeetingCallArtifactWrite(BaseModel):
    notes: str = Field(default="", max_length=50_000)
    transcript: str = Field(default="", max_length=200_000)


class CalendarWorkspaceSettingsWrite(BaseModel):
    working_hours: dict[str, Any] = Field(default_factory=lambda: {"weekdays": [1, 2, 3, 4, 5], "start": "09:00", "end": "17:00"})
    holidays: list[str] = Field(default_factory=list, max_length=500)
    shared_calendars: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    external_sync: dict[str, Any] = Field(default_factory=dict)


class AuditSettingsWrite(BaseModel):
    retention_days: int = Field(default=2555, ge=30, le=36500)
    legal_hold: bool = False
    export_enabled: bool = True


class ReportQueryWrite(BaseModel):
    object_type: Literal["work_item", "project", "risk"] = "work_item"
    group_by: str = Field(default="status", max_length=40)
    measure: Literal["count", "story_points", "risk_score", "progress"] = "count"
    project_id: str | None = None


def iso(value: datetime | None) -> str | None:
    return as_utc(value).isoformat() if value else None


def require_admin(user: User) -> None:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Workspace administrator access is required")


async def entity_users(session: AsyncSession, entity_id: str) -> dict[str, User]:
    rows = (await session.scalars(select(User).where(User.entity_id == entity_id).order_by(User.display_name))).all()
    return {item.id: item for item in rows}


async def same_entity_user(session: AsyncSession, entity_id: str, user_id: str | None) -> User | None:
    if not user_id:
        return None
    item = await session.get(User, user_id)
    if not item or item.entity_id != entity_id:
        raise HTTPException(status_code=400, detail="Selected person must belong to this workspace")
    return item


async def validate_object_reference(
    session: AsyncSession, entity_id: str, object_type: str, object_id: str,
) -> None:
    """Reject cross-tenant and dangling relationships for first-class objects."""
    models = {
        "employee": User, "project": Project, "work_item": WorkItem,
        "sprint": AgileSprint, "release": AgileRelease, "meeting": CalendarEvent,
        "document": KnowledgeDocument, "file": WorkspaceFile,
        "decision": ProjectDecision, "risk": ProjectRisk,
        "approval": ApprovalInstance, "unit": OrganizationUnit, "team": OrganizationUnit,
    }
    model = models.get(object_type)
    if not model:
        return
    item = await session.get(model, object_id)
    if not item or getattr(item, "entity_id", None) != entity_id:
        raise HTTPException(status_code=400, detail=f"{object_type.replace('_', ' ').title()} target not found")


def serialize_unit(item: OrganizationUnit, users: dict[str, User], member_rows: list[OrganizationUnitMember]) -> dict:
    return {"id": item.id, "name": item.name, "unit_type": item.unit_type, "description": item.description,
            "parent_id": item.parent_id, "manager": user_summary(users[item.manager_id]) if item.manager_id in users else None,
            "timezone": item.timezone, "weekly_capacity_hours": item.weekly_capacity_hours,
            "members": [{"user": user_summary(users[row.user_id]), "membership_role": row.membership_role,
                         "allocation_percent": row.allocation_percent} for row in member_rows if row.unit_id == item.id and row.user_id in users]}


def serialize_relationship(item: ObjectRelationship) -> dict:
    return {"id": item.id, "source_type": item.source_type, "source_id": item.source_id,
            "target_type": item.target_type, "target_id": item.target_id,
            "relationship_type": item.relationship_type, "metadata": item.metadata_json,
            "created_at": iso(item.created_at)}


def serialize_risk(item: ProjectRisk, users: dict[str, User]) -> dict:
    return {"id": item.id, "project_id": item.project_id, "title": item.title, "description": item.description,
            "owner": user_summary(users[item.owner_id]) if item.owner_id in users else None,
            "probability": item.probability, "impact": item.impact, "score": item.probability * item.impact,
            "status": item.status, "mitigation": item.mitigation,
            "due_date": item.due_date.isoformat() if item.due_date else None, "updated_at": iso(item.updated_at)}


def serialize_decision(item: ProjectDecision, users: dict[str, User]) -> dict:
    return {"id": item.id, "project_id": item.project_id, "title": item.title, "context": item.context,
            "decision": item.decision, "alternatives": item.alternatives, "consequences": item.consequences,
            "status": item.status, "owner": user_summary(users[item.owner_id]), "decided_at": iso(item.decided_at),
            "updated_at": iso(item.updated_at)}


@router.get("/overview")
async def enterprise_overview(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> dict:
    if user.role == "guest":
        raise HTTPException(status_code=403, detail="Guest accounts do not have workspace operations access")
    users = await entity_users(session, user.entity_id)
    units = (await session.scalars(select(OrganizationUnit).where(OrganizationUnit.entity_id == user.entity_id).order_by(OrganizationUnit.name))).all()
    unit_members = (await session.scalars(select(OrganizationUnitMember).join(OrganizationUnit).where(OrganizationUnit.entity_id == user.entity_id))).all()
    relationships = (await session.scalars(select(ObjectRelationship).where(ObjectRelationship.entity_id == user.entity_id).order_by(ObjectRelationship.created_at.desc()).limit(1000))).all()
    risks = (await session.scalars(select(ProjectRisk).where(ProjectRisk.entity_id == user.entity_id).order_by(ProjectRisk.updated_at.desc()).limit(500))).all()
    decisions = (await session.scalars(select(ProjectDecision).where(ProjectDecision.entity_id == user.entity_id).order_by(ProjectDecision.updated_at.desc()).limit(500))).all()
    views = (await session.scalars(select(SavedWorkspaceView).where(SavedWorkspaceView.entity_id == user.entity_id, or_(SavedWorkspaceView.owner_id == user.id, SavedWorkspaceView.shared.is_(True))))).all()
    dashboards = (await session.scalars(select(WorkspaceDashboard).where(WorkspaceDashboard.entity_id == user.entity_id, or_(WorkspaceDashboard.owner_id == user.id, WorkspaceDashboard.shared.is_(True))))).all()
    files = (await session.scalars(select(WorkspaceFile).where(WorkspaceFile.entity_id == user.entity_id).order_by(WorkspaceFile.updated_at.desc()).limit(1000))).all()
    files = [item for item in files if item.visibility == "workspace" or item.owner_id == user.id or user.id in (item.shared_with_ids or [])]
    definitions = (await session.scalars(select(ApprovalDefinition).where(ApprovalDefinition.entity_id == user.entity_id))).all()
    approvals = (await session.scalars(select(ApprovalInstance).where(ApprovalInstance.entity_id == user.entity_id).order_by(ApprovalInstance.updated_at.desc()).limit(500))).all()
    preferences = (await session.scalars(select(NotificationPreference).where(NotificationPreference.user_id == user.id))).all()
    projects = (await session.scalars(select(Project).where(Project.entity_id == user.entity_id).order_by(Project.title).limit(1000))).all()
    meetings = (await session.scalars(select(CalendarEvent).where(CalendarEvent.entity_id == user.entity_id).order_by(CalendarEvent.starts_at.desc()).limit(500))).all()
    entity = await session.get(Entity, user.entity_id)
    return {
        "projects": [{"id": item.id, "title": item.title, "status": item.status, "profile": item.profile} for item in projects],
        "meetings": [{"id": item.id, "title": item.title, "starts_at": iso(item.starts_at), "agenda": item.agenda,
                      "notes": item.notes, "action_items": item.action_items, "transcript": item.transcript,
                      "recording_url": item.recording_url, "organizer_id": item.organizer_id} for item in meetings],
        "members": [{**user_summary(item), "job_title": item.job_title, "timezone": item.timezone,
                     "manager_id": item.manager_id, "skills": item.skills, "weekly_capacity_hours": item.weekly_capacity_hours,
                     "profile": item.profile} for item in users.values()],
        "units": [serialize_unit(item, users, unit_members) for item in units],
        "relationships": [serialize_relationship(item) for item in relationships],
        "risks": [serialize_risk(item, users) for item in risks],
        "decisions": [serialize_decision(item, users) for item in decisions],
        "views": [{"id": item.id, "name": item.name, "view_type": item.view_type, "scope_type": item.scope_type, "scope_id": item.scope_id, "config": item.config, "shared": item.shared, "is_default": item.is_default} for item in views],
        "dashboards": [{"id": item.id, "name": item.name, "widgets": item.widgets, "layout": item.layout, "shared": item.shared, "delivery": item.delivery} for item in dashboards],
        "files": [{"id": item.id, "name": item.name, "item_type": item.item_type, "parent_id": item.parent_id, "external_url": item.external_url, "provider": item.provider, "mime_type": item.mime_type, "size_bytes": item.size_bytes, "classification": item.classification, "tags": item.tags, "version": item.version, "visibility": item.visibility, "description": item.description, "content_text": item.content_text, "preview_url": item.preview_url, "shared_with_ids": item.shared_with_ids, "owner": user_summary(users[item.owner_id]), "updated_at": iso(item.updated_at)} for item in files],
        "approval_definitions": [{"id": item.id, "name": item.name, "target_types": item.target_types, "stages": item.stages, "reminder_hours": item.reminder_hours, "escalation_hours": item.escalation_hours, "active": item.active} for item in definitions],
        "approvals": [{"id": item.id, "definition_id": item.definition_id, "target_type": item.target_type, "target_id": item.target_id, "status": item.status, "current_stage": item.current_stage, "decisions": item.decisions, "due_at": iso(item.due_at), "delegated_to_id": item.delegated_to_id} for item in approvals],
        "notification_preferences": [{"kind": item.kind, "in_app": item.in_app, "email": item.email, "push": item.push, "digest": item.digest, "muted": item.muted} for item in preferences],
        "notification_kinds": NOTIFICATION_KINDS,
        "governance_settings": entity.governance_settings or {},
    }


@router.post("/units", status_code=status.HTTP_201_CREATED)
async def create_unit(payload: OrgUnitWrite, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> dict:
    require_admin(user)
    if payload.parent_id:
        parent = await session.get(OrganizationUnit, payload.parent_id)
        if not parent or parent.entity_id != user.entity_id:
            raise HTTPException(status_code=400, detail="Parent unit not found")
    await same_entity_user(session, user.entity_id, payload.manager_id)
    users = await entity_users(session, user.entity_id)
    unit = OrganizationUnit(entity_id=user.entity_id, name=payload.name, unit_type=payload.unit_type,
                            description=payload.description, parent_id=payload.parent_id, manager_id=payload.manager_id,
                            timezone=payload.timezone, weekly_capacity_hours=payload.weekly_capacity_hours)
    session.add(unit); await session.flush()
    for entry in payload.members:
        member_id = str(entry.get("user_id", ""))
        if member_id not in users: raise HTTPException(status_code=400, detail="Unit member is outside this workspace")
        session.add(OrganizationUnitMember(unit_id=unit.id, user_id=member_id,
                    membership_role=str(entry.get("membership_role", "member"))[:24],
                    allocation_percent=max(0, min(100, int(entry.get("allocation_percent", 100))))))
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="organization.unit_created", target_type="unit", target_id=unit.id)
    await session.commit(); await session.refresh(unit)
    rows = (await session.scalars(select(OrganizationUnitMember).where(OrganizationUnitMember.unit_id == unit.id))).all()
    return serialize_unit(unit, users, rows)


@router.put("/units/{unit_id}")
async def update_unit(unit_id: str, payload: OrgUnitWrite, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> dict:
    require_admin(user)
    unit = await session.get(OrganizationUnit, unit_id)
    if not unit or unit.entity_id != user.entity_id:
        raise HTTPException(status_code=404, detail="Organization unit not found")
    if payload.parent_id == unit.id:
        raise HTTPException(status_code=400, detail="A unit cannot be its own parent")
    if payload.parent_id:
        parent = await session.get(OrganizationUnit, payload.parent_id)
        if not parent or parent.entity_id != user.entity_id:
            raise HTTPException(status_code=400, detail="Parent unit not found")
        ancestors, cursor = {unit.id}, parent
        while cursor:
            if cursor.id in ancestors:
                raise HTTPException(status_code=409, detail="This parent would create an organization hierarchy cycle")
            ancestors.add(cursor.id)
            cursor = await session.get(OrganizationUnit, cursor.parent_id) if cursor.parent_id else None
    await same_entity_user(session, user.entity_id, payload.manager_id)
    users = await entity_users(session, user.entity_id)
    for field in ("name", "unit_type", "description", "parent_id", "manager_id", "timezone", "weekly_capacity_hours"):
        setattr(unit, field, getattr(payload, field))
    await session.execute(delete(OrganizationUnitMember).where(OrganizationUnitMember.unit_id == unit.id))
    for entry in payload.members:
        member_id = str(entry.get("user_id", ""))
        if member_id not in users:
            raise HTTPException(status_code=400, detail="Unit member is outside this workspace")
        session.add(OrganizationUnitMember(
            unit_id=unit.id, user_id=member_id,
            membership_role=str(entry.get("membership_role", "member"))[:24],
            allocation_percent=max(0, min(100, int(entry.get("allocation_percent", 100)))),
        ))
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="organization.unit_updated", target_type="unit", target_id=unit.id)
    await session.commit()
    rows = (await session.scalars(select(OrganizationUnitMember).where(OrganizationUnitMember.unit_id == unit.id))).all()
    return serialize_unit(unit, users, rows)


@router.put("/people/{person_id}")
async def update_person(person_id: str, payload: ProfileWrite, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> dict:
    if user.role != "admin" and user.id != person_id: raise HTTPException(status_code=403, detail="You can update only your own profile")
    person = await same_entity_user(session, user.entity_id, person_id)
    await same_entity_user(session, user.entity_id, payload.manager_id)
    person.job_title, person.timezone, person.manager_id = payload.job_title.strip(), payload.timezone, payload.manager_id
    person.skills = list(dict.fromkeys(skill.strip()[:80] for skill in payload.skills if skill.strip()))
    person.weekly_capacity_hours, person.profile = payload.weekly_capacity_hours, payload.profile
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="organization.profile_updated", target_type="employee", target_id=person.id)
    await session.commit()
    return {**user_summary(person), "job_title": person.job_title, "timezone": person.timezone, "manager_id": person.manager_id, "skills": person.skills, "weekly_capacity_hours": person.weekly_capacity_hours, "profile": person.profile}


def graph_has_path(edges: list[ObjectRelationship], start: str, target: str) -> bool:
    adjacency: dict[str, set[str]] = {}
    for edge in edges: adjacency.setdefault(edge.source_id, set()).add(edge.target_id)
    stack, visited = [start], set()
    while stack:
        current = stack.pop()
        if current == target: return True
        if current in visited: continue
        visited.add(current); stack.extend(adjacency.get(current, set()))
    return False


@router.post("/relationships", status_code=status.HTTP_201_CREATED)
async def create_relationship(payload: RelationshipWrite, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> dict:
    require_admin(user)
    await validate_object_reference(session, user.entity_id, payload.source_type, payload.source_id)
    await validate_object_reference(session, user.entity_id, payload.target_type, payload.target_id)
    return await create_graph_relationship(
        CanonicalRelationshipCreate(**payload.model_dump()), user, session,
    )


@router.delete("/relationships/{relationship_id}", status_code=204)
async def delete_relationship(relationship_id: str, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> None:
    require_admin(user)
    await delete_graph_relationship(relationship_id, user, session)


@router.get("/dependencies")
async def dependency_map(project_id: str | None = None, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> dict:
    if user.role == "guest":
        raise HTTPException(status_code=403, detail="Guest accounts cannot access the workspace dependency map")
    if project_id:
        project = await session.get(Project, project_id)
        if not project or not await project_access_role(session, project, user):
            raise HTTPException(status_code=404, detail="Project not found")
    items = (await session.scalars(select(WorkItem).where(WorkItem.entity_id == user.entity_id, WorkItem.archived.is_(False)))).all()
    if project_id: items = [item for item in items if item.project_id == project_id]
    ids = {item.id for item in items}
    edges = (await session.scalars(select(ObjectRelationship).where(ObjectRelationship.entity_id == user.entity_id, ObjectRelationship.relationship_type.in_(["blocks", "blocked_by", "depends_on", "required_by"])))).all()
    edges = [edge for edge in edges if edge.source_id in ids and edge.target_id in ids]
    cycles = []
    for edge in edges:
        others = [item for item in edges if item.id != edge.id]
        if graph_has_path(others, edge.target_id, edge.source_id): cycles.append(edge.id)
    blocked = {edge.target_id for edge in edges if edge.relationship_type in {"blocks", "depends_on"}}
    today = datetime.now(timezone.utc).date()
    nodes = [{"id": item.id, "key": item.key, "title": item.summary, "status": item.status, "project_id": item.project_id,
              "start_date": item.start_date.isoformat() if item.start_date else None, "due_date": item.due_date.isoformat() if item.due_date else None,
              "blocked": item.id in blocked, "schedule_impact_days": max(0, (today - item.due_date).days) if item.due_date and item.id in blocked else 0} for item in items]
    return {"nodes": nodes, "edges": [serialize_relationship(item) for item in edges], "cycle_edge_ids": cycles,
            "critical_path": [item["id"] for item in sorted(nodes, key=lambda value: value["due_date"] or "9999") if item["blocked"] or item["due_date"]][:20]}


async def editable_project(session: AsyncSession, project_id: str, user: User) -> Project:
    project = await session.get(Project, project_id); access = await project_access_role(session, project, user) if project else None
    if not project or not access: raise HTTPException(status_code=404, detail="Project not found")
    if not can_edit_project(access): raise HTTPException(status_code=403, detail="Project editor access is required")
    return project


@router.get("/projects/{project_id}/overview")
async def project_overview(project_id: str, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> dict:
    project = await session.get(Project, project_id); access = await project_access_role(session, project, user) if project else None
    if not project or not access: raise HTTPException(status_code=404, detail="Project not found")
    users = await entity_users(session, user.entity_id)
    work = (await session.scalars(select(WorkItem).where(WorkItem.project_id == project.id, WorkItem.archived.is_(False)))).all()
    risks = (await session.scalars(select(ProjectRisk).where(ProjectRisk.project_id == project.id))).all()
    decisions = (await session.scalars(select(ProjectDecision).where(ProjectDecision.project_id == project.id))).all()
    relationships = (await session.scalars(select(ObjectRelationship).where(ObjectRelationship.entity_id == user.entity_id, or_(
        (ObjectRelationship.source_type == "project") & (ObjectRelationship.source_id == project.id),
        (ObjectRelationship.target_type == "project") & (ObjectRelationship.target_id == project.id))))).all()
    related_document_ids = {edge.target_id if edge.source_type == "project" else edge.source_id for edge in relationships if "document" in {edge.source_type, edge.target_type}}
    related_meeting_ids = {edge.target_id if edge.source_type == "project" else edge.source_id for edge in relationships if "meeting" in {edge.source_type, edge.target_type}}
    documents = (await session.scalars(select(KnowledgeDocument).where(KnowledgeDocument.entity_id == user.entity_id, KnowledgeDocument.id.in_(related_document_ids), KnowledgeDocument.status != "archived").order_by(KnowledgeDocument.updated_at.desc()).limit(100))).all() if related_document_ids else []
    meetings = (await session.scalars(select(CalendarEvent).where(CalendarEvent.entity_id == user.entity_id, CalendarEvent.id.in_(related_meeting_ids)).order_by(CalendarEvent.starts_at.desc()).limit(100))).all() if related_meeting_ids else []
    group_access = (await session.execute(select(ProjectGroupAccess, OrganizationUnit).join(
        OrganizationUnit, OrganizationUnit.id == ProjectGroupAccess.unit_id
    ).where(ProjectGroupAccess.project_id == project.id))).all()
    return {"project": {"id": project.id, "title": project.title, "description": project.description, "status": project.status, "profile": project.profile, "settings": project.settings, "access": access},
            "work": [{"id": item.id, "key": item.key, "title": item.summary, "type": item.item_type, "status": item.status, "due_date": item.due_date.isoformat() if item.due_date else None} for item in work],
            "risks": [serialize_risk(item, users) for item in risks], "decisions": [serialize_decision(item, users) for item in decisions],
            "documents": [{"id": item.id, "title": item.title, "status": item.status, "updated_at": iso(item.updated_at)} for item in documents],
            "meetings": [{"id": item.id, "title": item.title, "starts_at": iso(item.starts_at), "agenda": item.agenda, "has_notes": bool(item.notes)} for item in meetings],
            "relationships": [serialize_relationship(item) for item in relationships],
            "group_access": [{"id": row.id, "unit_id": unit.id, "unit_name": unit.name,
                              "access_role": row.access_role} for row, unit in group_access]}


@router.put("/projects/{project_id}/group-access")
async def save_project_group_access(project_id: str, payload: ProjectGroupAccessWrite, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> dict:
    project = await session.get(Project, project_id)
    access = await project_access_role(session, project, user) if project else None
    if not project or not access:
        raise HTTPException(status_code=404, detail="Project not found")
    if access not in {"admin", "owner"}:
        raise HTTPException(status_code=403, detail="Only the project owner or an admin can share with groups")
    unit = await session.get(OrganizationUnit, payload.unit_id)
    if not unit or unit.entity_id != user.entity_id:
        raise HTTPException(status_code=400, detail="Organization group not found")
    item = await session.scalar(select(ProjectGroupAccess).where(
        ProjectGroupAccess.project_id == project.id, ProjectGroupAccess.unit_id == unit.id,
    ))
    if item:
        item.access_role = payload.access_role
    else:
        item = ProjectGroupAccess(project_id=project.id, unit_id=unit.id, access_role=payload.access_role); session.add(item)
    await session.flush()
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="project.group_access_updated", project_id=project.id,
                       target_type="unit", target_id=unit.id, details={"access_role": payload.access_role})
    await session.commit()
    return {"id": item.id, "unit_id": unit.id, "unit_name": unit.name, "access_role": item.access_role}


@router.put("/projects/{project_id}/settings")
async def update_project_settings(project_id: str, payload: ProjectSettingsWrite, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> dict:
    project = await editable_project(session, project_id, user); project.settings = payload.model_dump()
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="project.settings_updated", project_id=project.id, details={"sections": list(project.settings)})
    await session.commit(); return project.settings


@router.post("/projects/{project_id}/risks", status_code=201)
async def create_risk(project_id: str, payload: RiskWrite, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> dict:
    await editable_project(session, project_id, user); owner = await same_entity_user(session, user.entity_id, payload.owner_id)
    item = ProjectRisk(entity_id=user.entity_id, project_id=project_id, owner_id=owner.id if owner else None,
                       title=payload.title.strip(), description=payload.description, probability=payload.probability, impact=payload.impact,
                       status=payload.status, mitigation=payload.mitigation, due_date=payload.due_date)
    session.add(item); await session.flush(); record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="risk.created", project_id=project_id, target_type="risk", target_id=item.id)
    await session.commit(); await session.refresh(item); return serialize_risk(item, await entity_users(session, user.entity_id))


@router.post("/projects/{project_id}/decisions", status_code=201)
async def create_decision(project_id: str, payload: DecisionWrite, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> dict:
    await editable_project(session, project_id, user)
    item = ProjectDecision(entity_id=user.entity_id, project_id=project_id, owner_id=user.id, title=payload.title.strip(), context=payload.context,
                           decision=payload.decision, alternatives=payload.alternatives, consequences=payload.consequences, status=payload.status,
                           decided_at=datetime.now(timezone.utc) if payload.status == "accepted" else None)
    session.add(item); await session.flush(); record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="decision.created", project_id=project_id, target_type="decision", target_id=item.id)
    await session.commit(); await session.refresh(item); return serialize_decision(item, await entity_users(session, user.entity_id))


@router.put("/notification-preferences")
async def save_notification_preference(payload: PreferenceWrite, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> dict:
    item = await session.scalar(select(NotificationPreference).where(NotificationPreference.user_id == user.id, NotificationPreference.kind == payload.kind))
    if not item: item = NotificationPreference(user_id=user.id, kind=payload.kind); session.add(item)
    for key, value in payload.model_dump(exclude={"kind"}).items(): setattr(item, key, value)
    await session.commit(); return payload.model_dump()


@router.put("/notifications/{notification_id}/snooze")
async def snooze_notification(notification_id: str, payload: SnoozeWrite, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> dict:
    item = await session.get(Notification, notification_id)
    if not item or item.user_id != user.id: raise HTTPException(status_code=404, detail="Notification not found")
    item.snoozed_until = payload.until; await session.commit(); return {"id": item.id, "snoozed_until": iso(item.snoozed_until)}


@router.post("/views", status_code=201)
async def save_view(payload: ViewWrite, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> dict:
    if payload.is_default:
        existing_defaults = (await session.scalars(select(SavedWorkspaceView).where(SavedWorkspaceView.owner_id == user.id, SavedWorkspaceView.view_type == payload.view_type, SavedWorkspaceView.is_default.is_(True)))).all()
        for existing in existing_defaults:
            existing.is_default = False
    item = SavedWorkspaceView(entity_id=user.entity_id, owner_id=user.id, **payload.model_dump()); session.add(item); await session.commit(); await session.refresh(item)
    return {"id": item.id, **payload.model_dump()}


@router.post("/dashboards", status_code=201)
async def save_dashboard(payload: DashboardWrite, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> dict:
    item = WorkspaceDashboard(entity_id=user.entity_id, owner_id=user.id, **payload.model_dump()); session.add(item); await session.commit(); await session.refresh(item)
    return {"id": item.id, **payload.model_dump()}


@router.post("/files", status_code=201)
async def create_file_reference(payload: FileWrite, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> dict:
    if payload.parent_id:
        parent = await session.get(WorkspaceFile, payload.parent_id)
        if not parent or parent.entity_id != user.entity_id or parent.item_type != "folder": raise HTTPException(status_code=400, detail="Parent folder not found")
    if payload.item_type == "external" and not payload.external_url.startswith("https://"): raise HTTPException(status_code=422, detail="External file links must use HTTPS")
    await same_entity_users_for_file(session, user.entity_id, payload.shared_with_ids)
    item = WorkspaceFile(entity_id=user.entity_id, owner_id=user.id, **payload.model_dump()); session.add(item); await session.flush()
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="file.created", target_type="file", target_id=item.id, details={"provider": item.provider})
    await session.commit(); await session.refresh(item); return {"id": item.id, "name": item.name, "item_type": item.item_type, "external_url": item.external_url, "provider": item.provider}


async def same_entity_users_for_file(session: AsyncSession, entity_id: str, ids: list[str]) -> None:
    if not ids:
        return
    count = await session.scalar(select(func.count(User.id)).where(User.entity_id == entity_id, User.id.in_(set(ids))))
    if count != len(set(ids)):
        raise HTTPException(status_code=400, detail="Every file collaborator must belong to this workspace")


@router.put("/files/{file_id}")
async def update_file_reference(file_id: str, payload: FileWrite, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> dict:
    item = await session.get(WorkspaceFile, file_id)
    if not item or item.entity_id != user.entity_id:
        raise HTTPException(status_code=404, detail="File not found")
    if item.owner_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Only the owner or an admin can update this file")
    await same_entity_users_for_file(session, user.entity_id, payload.shared_with_ids)
    for key, value in payload.model_dump().items():
        setattr(item, key, value)
    item.version += 1; item.updated_at = datetime.now(timezone.utc)
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="file.version_created", target_type="file", target_id=item.id, details={"version": item.version})
    await session.commit()
    return {"id": item.id, "name": item.name, "version": item.version, "updated_at": iso(item.updated_at)}


@router.get("/files/search")
async def search_files(q: str = Query(min_length=1, max_length=200), user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> list[dict]:
    term = f"%{q.strip()}%"
    rows = (await session.scalars(select(WorkspaceFile).where(
        WorkspaceFile.entity_id == user.entity_id,
        or_(WorkspaceFile.name.ilike(term), WorkspaceFile.description.ilike(term), WorkspaceFile.content_text.ilike(term)),
    ).order_by(WorkspaceFile.updated_at.desc()).limit(200))).all()
    rows = [item for item in rows if item.visibility == "workspace" or item.owner_id == user.id or user.id in (item.shared_with_ids or [])]
    return [{"id": item.id, "name": item.name, "description": item.description,
             "provider": item.provider, "external_url": item.external_url,
             "preview_url": item.preview_url, "version": item.version} for item in rows]


@router.post("/approval-definitions", status_code=201)
async def create_approval_definition(payload: ApprovalDefinitionWrite, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> dict:
    require_admin(user); item = ApprovalDefinition(entity_id=user.entity_id, created_by_id=user.id, **payload.model_dump()); session.add(item); await session.commit(); await session.refresh(item)
    return {"id": item.id, **payload.model_dump()}


@router.post("/approvals", status_code=201)
async def request_approval(payload: ApprovalRequestWrite, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> dict:
    definition = await session.get(ApprovalDefinition, payload.definition_id)
    if not definition or definition.entity_id != user.entity_id or payload.target_type not in definition.target_types: raise HTTPException(status_code=400, detail="Approval definition does not support this target")
    item = ApprovalInstance(entity_id=user.entity_id, definition_id=definition.id, target_type=payload.target_type, target_id=payload.target_id, requested_by_id=user.id, due_at=payload.due_at)
    await validate_object_reference(session, user.entity_id, payload.target_type, payload.target_id)
    session.add(item); await session.flush(); record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="approval.requested", target_type=payload.target_type, target_id=payload.target_id)
    await session.commit(); await session.refresh(item); return {"id": item.id, "status": item.status, "current_stage": item.current_stage}


@router.post("/access-requests", status_code=201)
async def request_project_access(payload: AccessRequestWrite, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> dict:
    project = await session.get(Project, payload.project_id)
    if not project or project.entity_id != user.entity_id:
        raise HTTPException(status_code=404, detail="Project not found")
    existing = await session.scalar(select(ApprovalInstance).where(
        ApprovalInstance.entity_id == user.entity_id, ApprovalInstance.target_type == "project_access",
        ApprovalInstance.target_id == project.id, ApprovalInstance.requested_by_id == user.id,
        ApprovalInstance.status == "pending",
    ))
    if existing:
        raise HTTPException(status_code=409, detail="You already have a pending access request")
    item = ApprovalInstance(entity_id=user.entity_id, definition_id=None, target_type="project_access",
                            target_id=project.id, requested_by_id=user.id,
                            decisions=[{"requested_role": payload.requested_role, "reason": payload.reason}])
    session.add(item); await session.flush()
    admins = (await session.scalars(select(User).where(User.entity_id == user.entity_id, User.role == "admin"))).all()
    for admin in admins:
        session.add(Notification(entity_id=user.entity_id, user_id=admin.id, actor_id=user.id,
                                 kind="approval", title=f"Access requested for {project.title}", body=payload.reason,
                                 project_id=project.id, group_key=f"project-access:{project.id}"))
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="project.access_requested",
                       project_id=project.id, target_type="project_access", target_id=item.id,
                       details={"requested_role": payload.requested_role})
    await session.commit()
    return {"id": item.id, "status": item.status}


@router.put("/approvals/{approval_id}/decision")
async def decide_approval(approval_id: str, payload: ApprovalDecisionWrite, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> dict:
    item = await session.get(ApprovalInstance, approval_id)
    if not item or item.entity_id != user.entity_id: raise HTTPException(status_code=404, detail="Approval not found")
    definition = await session.get(ApprovalDefinition, item.definition_id) if item.definition_id else None
    stages = definition.stages if definition else []
    stage = stages[item.current_stage] if item.current_stage < len(stages) else {}
    approver_ids = set(stage.get("approver_ids", []))
    if user.role != "admin" and user.id not in approver_ids and item.delegated_to_id != user.id: raise HTTPException(status_code=403, detail="You are not an approver for this stage")
    if item.status != "pending":
        raise HTTPException(status_code=409, detail="This approval is already complete")
    if payload.decision == "delegated":
        delegate = await same_entity_user(session, user.entity_id, payload.delegate_to_id); item.delegated_to_id = delegate.id
    else:
        decisions = list(item.decisions or []); decisions.append({"stage": item.current_stage, "user_id": user.id, "decision": payload.decision, "note": payload.note, "at": iso(datetime.now(timezone.utc))}); item.decisions = decisions
        if payload.decision == "approved":
            stage_decisions = {entry["user_id"] for entry in decisions if entry.get("stage") == item.current_stage and entry.get("decision") == "approved"}
            stage_complete = stage.get("mode", "sequential") != "parallel" or approver_ids.issubset(stage_decisions)
            if stage_complete and item.current_stage + 1 < len(stages):
                item.current_stage += 1; item.delegated_to_id = None
            elif stage_complete:
                item.status = "approved"
        else:
            item.status = payload.decision
        if item.target_type == "project_access" and item.status == "approved":
            requested = next((entry.get("requested_role") for entry in item.decisions if entry.get("requested_role")), "viewer")
            collaborator = await session.scalar(select(ProjectCollaborator).where(
                ProjectCollaborator.project_id == item.target_id,
                ProjectCollaborator.user_id == item.requested_by_id,
            ))
            if collaborator:
                collaborator.access_role = requested
            else:
                session.add(ProjectCollaborator(project_id=item.target_id, user_id=item.requested_by_id, access_role=requested))
    item.updated_at = datetime.now(timezone.utc); record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action=f"approval.{payload.decision}", target_type=item.target_type, target_id=item.target_id)
    await session.commit(); return {"id": item.id, "status": item.status, "current_stage": item.current_stage, "decisions": item.decisions, "delegated_to_id": item.delegated_to_id}


@router.post("/approvals/process-reminders")
async def process_approval_reminders(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> dict:
    require_admin(user)
    now = datetime.now(timezone.utc); created = 0
    approvals = (await session.scalars(select(ApprovalInstance).where(
        ApprovalInstance.entity_id == user.entity_id, ApprovalInstance.status == "pending",
    ))).all()
    for approval in approvals:
        definition = await session.get(ApprovalDefinition, approval.definition_id) if approval.definition_id else None
        if not definition:
            continue
        stage = definition.stages[approval.current_stage] if approval.current_stage < len(definition.stages) else {}
        recipients = set(stage.get("approver_ids", []))
        if approval.delegated_to_id:
            recipients = {approval.delegated_to_id}
        age_hours = (now - as_utc(approval.updated_at or approval.created_at)).total_seconds() / 3600
        level = "escalation" if age_hours >= definition.escalation_hours else "reminder" if age_hours >= definition.reminder_hours else ""
        if not level:
            continue
        group_key = f"approval:{approval.id}:{approval.current_stage}:{level}"
        already = await session.scalar(select(Notification.id).where(Notification.group_key == group_key).limit(1))
        if already:
            continue
        for recipient_id in recipients:
            await same_entity_user(session, user.entity_id, recipient_id)
            session.add(Notification(entity_id=user.entity_id, user_id=recipient_id, actor_id=user.id,
                                     kind="approval", title=f"Approval {level} · {approval.target_type}",
                                     body=f"Stage {approval.current_stage + 1} is waiting for your decision.",
                                     group_key=group_key))
            created += 1
    await session.commit()
    return {"processed": len(approvals), "notifications_created": created}


@router.put("/meetings/{event_id}/intelligence")
async def save_meeting_intelligence(event_id: str, payload: MeetingIntelligenceWrite, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> dict:
    event = await session.get(CalendarEvent, event_id)
    if not event or event.entity_id != user.entity_id: raise HTTPException(status_code=404, detail="Meeting not found")
    if event.organizer_id != user.id and user.role != "admin": raise HTTPException(status_code=403, detail="Only the organizer or an admin can update meeting records")
    for key, value in payload.model_dump().items(): setattr(event, key, value)
    event.updated_at = datetime.now(timezone.utc); record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="meeting.record_updated", target_type="meeting", target_id=event.id, details={"transcript": bool(event.transcript), "recording": bool(event.recording_url)})
    await session.commit(); return {"id": event.id, **payload.model_dump()}


@router.post("/meetings/{event_id}/call-artifacts")
async def append_meeting_call_artifacts(event_id: str, payload: MeetingCallArtifactWrite, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> dict:
    """Append live notes and captions without overwriting the meeting's existing record."""
    event = await session.get(CalendarEvent, event_id)
    if not event or event.entity_id != user.entity_id:
        raise HTTPException(status_code=404, detail="Meeting not found")
    membership = await session.scalar(select(CalendarEventAttendee.id).where(
        CalendarEventAttendee.event_id == event.id,
        CalendarEventAttendee.user_id == user.id,
    ))
    if not membership:
        raise HTTPException(status_code=403, detail="Only meeting participants can save call artifacts")
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if payload.notes.strip():
        event.notes = "\n\n".join(filter(None, [event.notes, f"Call notes · {timestamp}\n{payload.notes.strip()}"]))[-200_000:]
    if payload.transcript.strip():
        event.transcript = "\n\n".join(filter(None, [event.transcript, f"Call transcript · {timestamp}\n{payload.transcript.strip()}"]))[-1_000_000:]
    event.updated_at = datetime.now(timezone.utc)
    record_audit_event(
        session, entity_id=user.entity_id, actor_id=user.id,
        action="meeting.call_artifacts_appended", target_type="meeting", target_id=event.id,
        details={"notes": bool(payload.notes.strip()), "transcript": bool(payload.transcript.strip())},
    )
    await session.commit()
    return {"id": event.id, "saved": True}


@router.post("/meetings/{event_id}/extract-followups")
async def extract_meeting_followups(event_id: str, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> dict:
    """Deterministically extracts marked actions, decisions, and risks without a hosted AI API."""
    event = await session.get(CalendarEvent, event_id)
    if not event or event.entity_id != user.entity_id:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if event.organizer_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Only the organizer or an admin can extract follow-ups")
    source = event.transcript or event.notes or ""
    buckets: dict[str, list[dict[str, Any]]] = {"actions": [], "decisions": [], "risks": []}
    markers = {
        "actions": re.compile(r"^(?:[-*]\s*)?(?:\[ ?\]|action(?: item)?|todo|follow[- ]?up)\s*[:\-]\s*(.+)$", re.I),
        "decisions": re.compile(r"^(?:[-*]\s*)?(?:decision|decided)\s*[:\-]\s*(.+)$", re.I),
        "risks": re.compile(r"^(?:[-*]\s*)?(?:risk|blocker)\s*[:\-]\s*(.+)$", re.I),
    }
    for line_number, raw_line in enumerate(source.splitlines(), 1):
        line = raw_line.strip()
        for bucket, pattern in markers.items():
            match = pattern.match(line)
            if match:
                buckets[bucket].append({"id": str(uuid4()), "text": match.group(1).strip()[:1000], "source_line": line_number, "status": "open"})
                break
    existing = list(event.action_items or [])
    known = {str(item.get("text", "")).casefold() for item in existing}
    event.action_items = [*existing, *[item for item in buckets["actions"] if item["text"].casefold() not in known]]
    event.updated_at = datetime.now(timezone.utc)
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="meeting.followups_extracted", target_type="meeting", target_id=event.id,
                       details={key: len(value) for key, value in buckets.items()})
    await session.commit()
    return {**buckets, "action_items": event.action_items, "source": "transcript" if event.transcript else "notes"}


@router.put("/calendar/settings")
async def save_calendar_settings(payload: CalendarWorkspaceSettingsWrite, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> dict:
    profile = dict(user.profile or {})
    profile["calendar"] = payload.model_dump()
    user.profile = profile
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="calendar.settings_updated", target_type="employee", target_id=user.id)
    await session.commit()
    return profile["calendar"]


@router.get("/timeline")
async def organization_timeline(search: str = "", target_type: str | None = None, target_id: str | None = None, limit: int = Query(default=200, ge=1, le=1000), user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> list[dict]:
    if user.role == "guest":
        raise HTTPException(status_code=403, detail="Guest accounts cannot access organizational history")
    query = select(AuditEvent).where(AuditEvent.entity_id == user.entity_id)
    if target_type: query = query.where(AuditEvent.target_type == target_type)
    if target_id: query = query.where(AuditEvent.target_id == target_id)
    if search.strip(): query = query.where(or_(AuditEvent.action.ilike(f"%{search.strip()}%"), AuditEvent.target_type.ilike(f"%{search.strip()}%")))
    events = (await session.scalars(query.order_by(AuditEvent.created_at.desc()).limit(limit))).all(); users = await entity_users(session, user.entity_id)
    return [{"id": item.id, "action": item.action, "target_type": item.target_type, "target_id": item.target_id, "details": item.details, "actor": user_summary(users[item.actor_id]) if item.actor_id in users else None, "created_at": iso(item.created_at), "request_id": item.request_id, "event_hash": item.event_hash} for item in events]


@router.post("/reports/run")
async def run_report(payload: ReportQueryWrite, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> dict:
    if user.role == "guest":
        raise HTTPException(status_code=403, detail="Guest accounts cannot run workspace reports")
    valid_measures = {
        "work_item": {"count", "story_points"},
        "risk": {"count", "risk_score"},
        "project": {"count", "progress"},
    }
    if payload.measure not in valid_measures[payload.object_type]:
        raise HTTPException(status_code=422, detail="That measure is not supported for this object type")
    groups: dict[str, dict[str, float]] = {}
    if payload.object_type == "work_item":
        query = select(WorkItem).where(WorkItem.entity_id == user.entity_id, WorkItem.archived.is_(False))
        if payload.project_id: query = query.where(WorkItem.project_id == payload.project_id)
        rows = (await session.scalars(query.limit(20_000))).all()
        allowed = {"status", "item_type", "priority", "team", "project_id", "assignee_id"}
        if payload.group_by not in allowed: raise HTTPException(status_code=422, detail="Unsupported work-item dimension")
        for row in rows:
            key = str(getattr(row, payload.group_by) or "Unassigned")
            bucket = groups.setdefault(key, {"count": 0, "value": 0}); bucket["count"] += 1
            bucket["value"] += (row.story_points or 0) if payload.measure == "story_points" else 1
    elif payload.object_type == "risk":
        query = select(ProjectRisk).where(ProjectRisk.entity_id == user.entity_id)
        if payload.project_id: query = query.where(ProjectRisk.project_id == payload.project_id)
        rows = (await session.scalars(query.limit(20_000))).all()
        if payload.group_by not in {"status", "project_id", "owner_id"}: raise HTTPException(status_code=422, detail="Unsupported risk dimension")
        for row in rows:
            key = str(getattr(row, payload.group_by) or "Unassigned")
            bucket = groups.setdefault(key, {"count": 0, "value": 0}); bucket["count"] += 1
            bucket["value"] += row.probability * row.impact if payload.measure == "risk_score" else 1
    else:
        rows = (await session.scalars(select(Project).where(Project.entity_id == user.entity_id).limit(20_000))).all()
        if payload.group_by not in {"status", "approval_status", "owner_id"}: raise HTTPException(status_code=422, detail="Unsupported project dimension")
        for row in rows:
            key = str(getattr(row, payload.group_by) or "Unassigned")
            bucket = groups.setdefault(key, {"count": 0, "value": 0}); bucket["count"] += 1
            bucket["value"] += float((row.profile or {}).get("progress") or 0) if payload.measure == "progress" else 1
    result = [{"group": key, "count": int(value["count"]),
               "value": round(value["value"] / value["count"], 2) if payload.measure == "progress" and value["count"] else value["value"]}
              for key, value in sorted(groups.items(), key=lambda item: item[1]["value"], reverse=True)]
    return {"query": payload.model_dump(), "rows": result, "generated_at": iso(datetime.now(timezone.utc)), "row_count": len(result)}


def expected_audit_hash(item: AuditEvent) -> str:
    canonical = json.dumps({"id": item.id, "entity_id": item.entity_id, "actor_id": item.actor_id, "action": item.action, "target_type": item.target_type, "target_id": item.target_id, "details": item.details or {}, "created_at": as_utc(item.created_at).isoformat(), "previous_hash": item.previous_hash}, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(canonical.encode("utf-8")).hexdigest()


@router.get("/audit/verify")
async def verify_audit_chain(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> dict:
    require_admin(user); events = (await session.scalars(select(AuditEvent).where(AuditEvent.entity_id == user.entity_id, AuditEvent.event_hash.is_not(None)).order_by(AuditEvent.created_at, AuditEvent.id))).all()
    previous = None; broken = []
    for item in events:
        if item.previous_hash != previous or item.event_hash != expected_audit_hash(item): broken.append(item.id)
        previous = item.event_hash
    return {"valid": not broken, "event_count": len(events), "broken_event_ids": broken}


@router.put("/audit/settings")
async def save_audit_settings(payload: AuditSettingsWrite, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> dict:
    require_admin(user)
    entity = await session.get(Entity, user.entity_id)
    settings = dict(entity.governance_settings or {})
    settings["audit"] = payload.model_dump()
    entity.governance_settings = settings
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="audit.retention_updated", target_type="entity", target_id=entity.id,
                       details={"retention_days": payload.retention_days, "legal_hold": payload.legal_hold})
    await session.commit()
    return settings["audit"]


@router.get("/audit/export")
async def export_audit(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> StreamingResponse:
    require_admin(user)
    entity = await session.get(Entity, user.entity_id)
    if (entity.governance_settings or {}).get("audit", {}).get("export_enabled") is False:
        raise HTTPException(status_code=403, detail="Audit export is disabled by workspace policy")
    events = (await session.scalars(select(AuditEvent).where(AuditEvent.entity_id == user.entity_id).order_by(AuditEvent.created_at))).all()
    output = io.StringIO(); writer = csv.writer(output); writer.writerow(["id", "timestamp", "actor_id", "action", "target_type", "target_id", "request_id", "event_hash", "details"])
    for item in events: writer.writerow([item.id, iso(item.created_at), item.actor_id, item.action, item.target_type, item.target_id, item.request_id, item.event_hash, json.dumps(item.details, sort_keys=True)])
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=workspace-audit.csv"})
