"""Canonical, permission-aware object relationship and traversal service."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import get_current_user
from .database import (
    AgileRelease,
    AgileSprint,
    ApprovalInstance,
    AuditEvent,
    CalendarEvent,
    CalendarEventAttendee,
    KnowledgeDocument,
    KnowledgeDocumentAccess,
    ObjectRelationship,
    ObjectRelationshipHistory,
    OrganizationUnit,
    OrganizationUnitMember,
    Project,
    ProjectCollaborator,
    ProjectDecision,
    ProjectGroupAccess,
    ProjectRisk,
    User,
    WorkItem,
    WorkspaceFile,
    get_session,
)
from .governance import can_edit_project, project_access_role, record_audit_event


router = APIRouter(prefix="/work-graph", tags=["enterprise work graph"])

OBJECT_TYPES = {
    "employee", "project", "workflow", "work_item", "sprint", "release", "meeting",
    "document", "file", "decision", "risk", "approval", "unit", "team", "custom",
}
RELATIONSHIP_TYPES = {
    "parent_of", "child_of", "belongs_to", "owned_by", "assigned_to", "blocked_by",
    "blocks", "depends_on", "required_by", "related_to", "supports", "contributes_to",
    "discussed_in", "decided_in", "created_from", "approved_by", "reviewed_by",
    "mentioned_in", "documented_by", "impacts",
}
INVERSE_RELATIONSHIPS = {
    "parent_of": "child_of", "child_of": "parent_of", "belongs_to": "contains",
    "owned_by": "owns", "assigned_to": "assigned", "blocked_by": "blocks",
    "blocks": "blocked_by", "depends_on": "required_by", "required_by": "depends_on",
    "contributes_to": "has_contributor", "discussed_in": "discusses",
    "decided_in": "records_decision", "created_from": "created", "approved_by": "approved",
    "reviewed_by": "reviewed", "mentioned_in": "mentions", "documented_by": "documents",
    "impacts": "impacted_by", "supports": "supported_by", "related_to": "related_to",
}
DEPENDENCY_TYPES = {"blocks", "blocked_by", "depends_on", "required_by", "parent_of", "child_of"}

MODEL_BY_TYPE = {
    "employee": User,
    "project": Project,
    "workflow": Project,
    "work_item": WorkItem,
    "sprint": AgileSprint,
    "release": AgileRelease,
    "meeting": CalendarEvent,
    "document": KnowledgeDocument,
    "file": WorkspaceFile,
    "decision": ProjectDecision,
    "risk": ProjectRisk,
    "approval": ApprovalInstance,
    "unit": OrganizationUnit,
    "team": OrganizationUnit,
}


class RelationshipCreate(BaseModel):
    source_type: str
    source_id: str = Field(min_length=1, max_length=80)
    target_type: str
    target_id: str = Field(min_length=1, max_length=80)
    relationship_type: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_relationship(self) -> "RelationshipCreate":
        self.source_type = self.source_type.strip().lower()
        self.target_type = self.target_type.strip().lower()
        self.relationship_type = self.relationship_type.strip().lower()
        if self.source_type not in OBJECT_TYPES or self.target_type not in OBJECT_TYPES:
            raise ValueError("Unsupported object type")
        if self.relationship_type not in RELATIONSHIP_TYPES:
            raise ValueError("Unsupported relationship type")
        if (self.source_type, self.source_id) == (self.target_type, self.target_id):
            raise ValueError("An object cannot relate to itself")
        return self


class RelationshipUpdate(BaseModel):
    relationship_type: str | None = None
    metadata: dict[str, Any] | None = None


def canonical_type(object_type: str) -> str:
    value = object_type.strip().lower()
    if value not in OBJECT_TYPES:
        raise HTTPException(status_code=404, detail="Unsupported object type")
    return value


async def resolve_object(
    session: AsyncSession, entity_id: str, object_type: str, object_id: str,
) -> Any | None:
    object_type = canonical_type(object_type)
    if object_type == "custom":
        return {"id": object_id, "entity_id": entity_id, "title": object_id}
    item = await session.get(MODEL_BY_TYPE[object_type], object_id)
    if not item or getattr(item, "entity_id", None) != entity_id:
        return None
    return item


async def inherited_project(session: AsyncSession, object_type: str, item: Any) -> Project | None:
    if object_type in {"project", "workflow"}:
        return item
    project_id = getattr(item, "project_id", None)
    return await session.get(Project, project_id) if project_id else None


async def build_access_scope(session: AsyncSession, user: User) -> dict[str, Any]:
    """Preload permission grants once for bulk graph/search operations."""
    if user.role == "admin":
        return {"admin": True, "project_ids": set(), "document_ids": set(), "meeting_ids": set()}
    project_ids = set(await session.scalars(select(Project.id).where(
        Project.entity_id == user.entity_id,
        or_(Project.owner_id == user.id, Project.visibility == "workspace") if user.role != "guest" else Project.owner_id == user.id,
    )))
    project_ids.update(await session.scalars(select(ProjectCollaborator.project_id).join(
        Project, Project.id == ProjectCollaborator.project_id,
    ).where(Project.entity_id == user.entity_id, ProjectCollaborator.user_id == user.id)))
    project_ids.update(await session.scalars(select(ProjectGroupAccess.project_id).join(
        Project, Project.id == ProjectGroupAccess.project_id,
    ).join(OrganizationUnitMember, OrganizationUnitMember.unit_id == ProjectGroupAccess.unit_id).where(
        Project.entity_id == user.entity_id, OrganizationUnitMember.user_id == user.id,
    )))
    document_ids = set(await session.scalars(select(KnowledgeDocumentAccess.document_id).join(
        KnowledgeDocument, KnowledgeDocument.id == KnowledgeDocumentAccess.document_id,
    ).where(KnowledgeDocument.entity_id == user.entity_id, KnowledgeDocumentAccess.user_id == user.id)))
    meeting_ids = set(await session.scalars(select(CalendarEventAttendee.event_id).join(
        CalendarEvent, CalendarEvent.id == CalendarEventAttendee.event_id,
    ).where(CalendarEvent.entity_id == user.entity_id, CalendarEventAttendee.user_id == user.id)))
    return {"admin": False, "project_ids": project_ids, "document_ids": document_ids, "meeting_ids": meeting_ids}


async def can_view_object(
    session: AsyncSession, user: User, object_type: str, item: Any,
    access_scope: dict[str, Any] | None = None,
) -> bool:
    if item is None:
        return False
    if object_type == "custom":
        return user.role == "admin"
    if getattr(item, "entity_id", None) != user.entity_id:
        return False
    if access_scope and access_scope.get("admin"):
        return True
    inherited_project_id = item.id if object_type in {"project", "workflow"} else getattr(item, "project_id", None)
    if inherited_project_id and access_scope is not None:
        return inherited_project_id in access_scope["project_ids"]
    project = await inherited_project(session, object_type, item)
    if project:
        return bool(await project_access_role(session, project, user))
    if object_type == "document":
        if user.role == "admin" or item.owner_id == user.id:
            return True
        if item.visibility == "workspace" and user.role != "guest":
            return True
        if access_scope is not None:
            return item.id in access_scope["document_ids"]
        return bool(await session.scalar(select(KnowledgeDocumentAccess.id).where(
            KnowledgeDocumentAccess.document_id == item.id,
            KnowledgeDocumentAccess.user_id == user.id,
        )))
    if object_type == "file":
        return user.role == "admin" or item.owner_id == user.id or user.id in (item.shared_with_ids or []) or (
            item.visibility == "workspace" and user.role != "guest"
        )
    if object_type == "meeting":
        if user.role != "guest" or item.organizer_id == user.id:
            return True
        if access_scope is not None:
            return item.id in access_scope["meeting_ids"]
        return bool(await session.scalar(select(CalendarEventAttendee.id).where(
            CalendarEventAttendee.event_id == item.id,
            CalendarEventAttendee.user_id == user.id,
        )))
    if object_type == "approval":
        return user.role == "admin" or user.id in {item.requested_by_id, item.delegated_to_id}
    if object_type == "employee":
        return user.role != "guest" or item.id == user.id
    if object_type == "work_item" and user.role == "guest":
        return user.id in {item.reporter_id, item.assignee_id, item.owner_id} or user.id in (item.watcher_ids or [])
    return user.role != "guest"


async def can_edit_object(
    session: AsyncSession, user: User, object_type: str, item: Any,
) -> bool:
    if user.role == "admin":
        return True
    if user.role == "guest" or item is None:
        return False
    project = await inherited_project(session, object_type, item)
    if project:
        return can_edit_project(await project_access_role(session, project, user))
    if object_type == "document":
        if item.owner_id == user.id:
            return True
        role = await session.scalar(select(KnowledgeDocumentAccess.role).where(
            KnowledgeDocumentAccess.document_id == item.id,
            KnowledgeDocumentAccess.user_id == user.id,
        ))
        return role in {"owner", "editor"}
    if object_type == "file":
        return item.owner_id == user.id
    if object_type == "meeting":
        return item.organizer_id == user.id
    if object_type == "work_item":
        return user.id in {item.reporter_id, item.assignee_id, item.owner_id}
    return False


def object_url(object_type: str, item: Any) -> str:
    if object_type in {"project", "workflow"}:
        return f"/projects/{item.id}"
    if object_type == "work_item":
        return f"/work?item={item.id}"
    if object_type == "document":
        return f"/knowledge?document={item.id}"
    if object_type == "meeting":
        return f"/calendar?event={item.id}"
    if object_type in {"risk", "decision"}:
        return f"/operations?tab=projects&project={item.project_id}"
    if object_type in {"sprint", "release"}:
        return f"/work?tab={object_type}s&{object_type}={item.id}"
    if object_type == "file":
        return "/operations?tab=files"
    return "/operations"


def object_summary(object_type: str, item: Any) -> dict[str, Any]:
    fallback_title = item.get("title", item.get("id", "Untitled")) if isinstance(item, dict) else None
    title = (
        getattr(item, "title", None) or getattr(item, "summary", None) or
        getattr(item, "name", None) or getattr(item, "display_name", None) or
        (f"Approval · {getattr(item, 'target_type', '')}" if object_type == "approval" else fallback_title) or "Untitled"
    )
    subtitle = getattr(item, "key", None) or getattr(item, "description", "") or ""
    updated_at = getattr(item, "updated_at", None) or getattr(item, "created_at", None)
    result = {
        "type": object_type,
        "id": getattr(item, "id", None) or (item["id"] if isinstance(item, dict) else ""),
        "title": title,
        "subtitle": str(subtitle)[:240],
        "status": getattr(item, "status", None),
        "project_id": getattr(item, "project_id", None),
        "url": object_url(object_type, item) if not isinstance(item, dict) else "/operations",
        "updated_at": updated_at.isoformat() if updated_at else None,
    }
    if object_type == "work_item":
        result["key"] = item.key
        result["metadata"] = {"priority": item.priority, "item_type": item.item_type}
    elif object_type == "risk":
        result["metadata"] = {"probability": item.probability, "impact": item.impact}
    elif object_type == "document":
        result["metadata"] = {"classification": item.classification, "visibility": item.visibility}
    return result


def serialize_edge(item: ObjectRelationship, *, direction: str | None = None) -> dict[str, Any]:
    relationship_type = item.relationship_type if direction != "incoming" else INVERSE_RELATIONSHIPS.get(item.relationship_type, item.relationship_type)
    return {
        "id": item.id,
        "source_type": item.source_type,
        "source_id": item.source_id,
        "target_type": item.target_type,
        "target_id": item.target_id,
        "relationship_type": item.relationship_type,
        "display_relationship_type": relationship_type,
        "direction": direction,
        "metadata": item.metadata_json or {},
        "created_by_id": item.created_by_id,
        "created_at": item.created_at.isoformat(),
    }


def relationship_snapshot(item: ObjectRelationship, action: str, actor_id: str | None) -> ObjectRelationshipHistory:
    return ObjectRelationshipHistory(
        entity_id=item.entity_id, relationship_id=item.id, action=action,
        source_type=item.source_type, source_id=item.source_id,
        target_type=item.target_type, target_id=item.target_id,
        relationship_type=item.relationship_type, metadata_json=dict(item.metadata_json or {}),
        actor_id=actor_id,
    )


async def require_visible_object(session: AsyncSession, user: User, object_type: str, object_id: str) -> Any:
    item = await resolve_object(session, user.entity_id, object_type, object_id)
    if not await can_view_object(session, user, object_type, item):
        raise HTTPException(status_code=404, detail="Object not found")
    return item


async def would_create_cycle(
    session: AsyncSession, entity_id: str, source: tuple[str, str], target: tuple[str, str],
    relationship_type: str, excluding_id: str | None = None,
) -> bool:
    if relationship_type not in DEPENDENCY_TYPES:
        return False
    if relationship_type in {"blocked_by", "required_by", "child_of"}:
        source, target = target, source
    edges = list(await session.scalars(select(ObjectRelationship).where(
        ObjectRelationship.entity_id == entity_id,
        ObjectRelationship.relationship_type.in_(["blocks", "depends_on", "parent_of"]),
    )))
    adjacency: dict[tuple[str, str], set[tuple[str, str]]] = {}
    for edge in edges:
        if edge.id == excluding_id:
            continue
        adjacency.setdefault((edge.source_type, edge.source_id), set()).add((edge.target_type, edge.target_id))
    stack, visited = [target], set()
    while stack:
        current = stack.pop()
        if current == source:
            return True
        if current in visited:
            continue
        visited.add(current)
        stack.extend(adjacency.get(current, set()))
    return False


@router.get("/objects/{object_type}/{object_id}")
async def get_graph_object(
    object_type: str, object_id: str, user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    object_type = canonical_type(object_type)
    item = await require_visible_object(session, user, object_type, object_id)
    return object_summary(object_type, item)


@router.get("/objects/{object_type}/{object_id}/related")
async def related_objects(
    object_type: str,
    object_id: str,
    depth: int = Query(default=1, ge=1, le=5),
    direction: Literal["both", "outgoing", "incoming"] = "both",
    relationship_types: str = "",
    limit: int = Query(default=100, ge=1, le=500),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    object_type = canonical_type(object_type)
    root = await require_visible_object(session, user, object_type, object_id)
    allowed_relations = {value.strip() for value in relationship_types.split(",") if value.strip()}
    if allowed_relations - RELATIONSHIP_TYPES:
        raise HTTPException(status_code=422, detail="Unsupported relationship filter")

    root_key = (object_type, object_id)
    frontier = {root_key}
    visited = {root_key: 0}
    visible_items: dict[tuple[str, str], Any] = {root_key: root}
    included_edges: dict[str, tuple[ObjectRelationship, str]] = {}
    truncated = False

    for current_depth in range(1, depth + 1):
        if not frontier or len(visited) >= limit + 1:
            truncated = bool(frontier)
            break
        clauses = []
        if direction in {"both", "outgoing"}:
            clauses.extend(and_(ObjectRelationship.source_type == kind, ObjectRelationship.source_id == item_id) for kind, item_id in frontier)
        if direction in {"both", "incoming"}:
            clauses.extend(and_(ObjectRelationship.target_type == kind, ObjectRelationship.target_id == item_id) for kind, item_id in frontier)
        query = select(ObjectRelationship).where(ObjectRelationship.entity_id == user.entity_id, or_(*clauses))
        if allowed_relations:
            query = query.where(ObjectRelationship.relationship_type.in_(allowed_relations))
        rows = list(await session.scalars(query.order_by(ObjectRelationship.created_at.desc()).limit(limit * 4)))
        next_frontier: set[tuple[str, str]] = set()
        for edge in rows:
            source_key, target_key = (edge.source_type, edge.source_id), (edge.target_type, edge.target_id)
            if source_key in frontier:
                neighbor_key, edge_direction = target_key, "outgoing"
            else:
                neighbor_key, edge_direction = source_key, "incoming"
            if neighbor_key not in visible_items:
                neighbor = await resolve_object(session, user.entity_id, *neighbor_key)
                if not await can_view_object(session, user, neighbor_key[0], neighbor):
                    continue
                visible_items[neighbor_key] = neighbor
            included_edges.setdefault(edge.id, (edge, edge_direction))
            if neighbor_key not in visited:
                if len(visited) >= limit + 1:
                    truncated = True
                    break
                visited[neighbor_key] = current_depth
                next_frontier.add(neighbor_key)
        frontier = next_frontier

    visible_keys = set(visible_items)
    edges = [serialize_edge(edge, direction=edge_direction) for edge, edge_direction in included_edges.values()
             if (edge.source_type, edge.source_id) in visible_keys and (edge.target_type, edge.target_id) in visible_keys]
    nodes = [{**object_summary(kind, item), "depth": visited[(kind, item_id)]}
             for (kind, item_id), item in visible_items.items() if (kind, item_id) != root_key]
    nodes.sort(key=lambda value: (value["depth"], value["type"], value["title"].lower()))
    return {
        "root": object_summary(object_type, root), "nodes": nodes, "edges": edges,
        "depth": depth, "direction": direction, "truncated": truncated,
    }


@router.get("/objects/{object_type}/{object_id}/history")
async def object_history(
    object_type: str, object_id: str, limit: int = Query(default=50, ge=1, le=250),
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    object_type = canonical_type(object_type)
    await require_visible_object(session, user, object_type, object_id)
    relationships = list(await session.scalars(select(ObjectRelationshipHistory).where(
        ObjectRelationshipHistory.entity_id == user.entity_id,
        or_(
            and_(ObjectRelationshipHistory.source_type == object_type, ObjectRelationshipHistory.source_id == object_id),
            and_(ObjectRelationshipHistory.target_type == object_type, ObjectRelationshipHistory.target_id == object_id),
        ),
    ).order_by(ObjectRelationshipHistory.created_at.desc()).limit(limit)))
    audits = list(await session.scalars(select(AuditEvent).where(
        AuditEvent.entity_id == user.entity_id,
        AuditEvent.target_type == object_type,
        AuditEvent.target_id == object_id,
    ).order_by(AuditEvent.created_at.desc()).limit(limit)))
    events = [{
        "id": item.id, "kind": "relationship", "action": f"relationship.{item.action}",
        "actor_id": item.actor_id, "created_at": item.created_at.isoformat(),
        "details": {"relationship_id": item.relationship_id, "relationship_type": item.relationship_type,
                    "source_type": item.source_type, "source_id": item.source_id,
                    "target_type": item.target_type, "target_id": item.target_id,
                    "metadata": item.metadata_json or {}},
    } for item in relationships]
    events.extend({
        "id": item.id, "kind": "object", "action": item.action, "actor_id": item.actor_id,
        "created_at": item.created_at.isoformat(), "details": item.details or {},
    } for item in audits)
    events.sort(key=lambda value: value["created_at"], reverse=True)
    return {"object": {"type": object_type, "id": object_id}, "events": events[:limit]}


@router.post("/relationships", status_code=status.HTTP_201_CREATED)
async def create_graph_relationship(
    payload: RelationshipCreate, user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    source = await require_visible_object(session, user, payload.source_type, payload.source_id)
    target = await require_visible_object(session, user, payload.target_type, payload.target_id)
    if not await can_edit_object(session, user, payload.source_type, source):
        raise HTTPException(status_code=403, detail="Editor access to the source object is required")
    if await would_create_cycle(
        session, user.entity_id, (payload.source_type, payload.source_id),
        (payload.target_type, payload.target_id), payload.relationship_type,
    ):
        raise HTTPException(status_code=409, detail="This relationship would create a circular dependency")
    item = ObjectRelationship(
        entity_id=user.entity_id, created_by_id=user.id,
        source_type=payload.source_type, source_id=payload.source_id,
        target_type=payload.target_type, target_id=payload.target_id,
        relationship_type=payload.relationship_type, metadata_json=payload.metadata,
    )
    session.add(item)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="This relationship already exists") from exc
    session.add(relationship_snapshot(item, "created", user.id))
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="relationship.created",
                       target_type="relationship", target_id=item.id, details=payload.model_dump())
    await session.commit()
    await session.refresh(item)
    return serialize_edge(item)


@router.put("/relationships/{relationship_id}")
async def update_graph_relationship(
    relationship_id: str, payload: RelationshipUpdate, user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    item = await session.get(ObjectRelationship, relationship_id)
    if not item or item.entity_id != user.entity_id:
        raise HTTPException(status_code=404, detail="Relationship not found")
    source = await require_visible_object(session, user, item.source_type, item.source_id)
    if not await can_edit_object(session, user, item.source_type, source):
        raise HTTPException(status_code=403, detail="Editor access to the source object is required")
    next_type = (payload.relationship_type or item.relationship_type).strip().lower()
    if next_type not in RELATIONSHIP_TYPES:
        raise HTTPException(status_code=422, detail="Unsupported relationship type")
    if await would_create_cycle(session, user.entity_id, (item.source_type, item.source_id),
                                (item.target_type, item.target_id), next_type, excluding_id=item.id):
        raise HTTPException(status_code=409, detail="This relationship would create a circular dependency")
    item.relationship_type = next_type
    if payload.metadata is not None:
        item.metadata_json = payload.metadata
    session.add(relationship_snapshot(item, "updated", user.id))
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="relationship.updated",
                       target_type="relationship", target_id=item.id)
    await session.commit()
    await session.refresh(item)
    return serialize_edge(item)


@router.delete("/relationships/{relationship_id}", status_code=204, response_class=Response)
async def delete_graph_relationship(
    relationship_id: str, user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    item = await session.get(ObjectRelationship, relationship_id)
    if not item or item.entity_id != user.entity_id:
        raise HTTPException(status_code=404, detail="Relationship not found")
    source = await require_visible_object(session, user, item.source_type, item.source_id)
    if not await can_edit_object(session, user, item.source_type, source):
        raise HTTPException(status_code=403, detail="Editor access to the source object is required")
    session.add(relationship_snapshot(item, "deleted", user.id))
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="relationship.deleted",
                       target_type="relationship", target_id=item.id)
    await session.delete(item)
    await session.commit()
    return Response(status_code=204)
