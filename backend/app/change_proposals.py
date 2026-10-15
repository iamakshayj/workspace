"""Human-reviewed, idempotent and reversible work-graph changes."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import get_current_user
from .database import (
    ChangeProposal, Notification, ObjectRelationship, OrganizationUnitMember,
    ProjectCollaborator, ProjectGroupAccess, User, get_session,
)
from .governance import can_approve_project, project_access_role, record_audit_event
from .policy_engine import PolicyContext, evaluate_policy, require_entitlement
from .work_graph import (
    OBJECT_TYPES,
    RELATIONSHIP_TYPES,
    can_edit_object,
    inherited_project,
    object_summary,
    relationship_snapshot,
    require_visible_object,
    would_create_cycle,
)


router = APIRouter(prefix="/change-proposals", tags=["governed changes"])
class GraphOperation(BaseModel):
    action: Literal["create", "update", "delete"]
    relationship_id: str | None = Field(default=None, max_length=36)
    source_type: str | None = None
    source_id: str | None = Field(default=None, max_length=80)
    target_type: str | None = None
    target_id: str | None = Field(default=None, max_length=80)
    relationship_type: str | None = None
    metadata: dict[str, Any] | None = None

    @model_validator(mode="after")
    def normalize(self) -> "GraphOperation":
        for field in ("source_type", "target_type", "relationship_type"):
            value = getattr(self, field)
            if value:
                setattr(self, field, value.strip().lower())
        if self.action == "create":
            required = (self.source_type, self.source_id, self.target_type, self.target_id, self.relationship_type)
            if not all(required):
                raise ValueError("Create operations require source, target, and relationship type")
            if self.source_type not in OBJECT_TYPES or self.target_type not in OBJECT_TYPES:
                raise ValueError("Unsupported object type")
            if self.relationship_type not in RELATIONSHIP_TYPES:
                raise ValueError("Unsupported relationship type")
            if (self.source_type, self.source_id) == (self.target_type, self.target_id):
                raise ValueError("An object cannot relate to itself")
        elif not self.relationship_id:
            raise ValueError("Update and delete operations require relationship_id")
        if self.action == "update" and not self.relationship_type and self.metadata is None:
            raise ValueError("Update operations require a relationship type or metadata change")
        if self.relationship_type and self.relationship_type not in RELATIONSHIP_TYPES:
            raise ValueError("Unsupported relationship type")
        return self


class ProposalCreate(BaseModel):
    title: str = Field(min_length=3, max_length=180)
    rationale: str = Field(default="", max_length=10_000)
    idempotency_key: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9._:-]+$")
    operations: list[GraphOperation] = Field(min_length=1, max_length=20)
    evidence: list[dict[str, Any]] = Field(default_factory=list, max_length=50)


class ProposalDecision(BaseModel):
    decision: Literal["approved", "rejected"]
    note: str = Field(default="", max_length=5000)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def fingerprint(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def relationship_state(item: ObjectRelationship | None) -> dict[str, Any] | None:
    if item is None:
        return None
    return {
        "id": item.id,
        "entity_id": item.entity_id,
        "source_type": item.source_type,
        "source_id": item.source_id,
        "target_type": item.target_type,
        "target_id": item.target_id,
        "relationship_type": item.relationship_type,
        "metadata": dict(item.metadata_json or {}),
        "created_by_id": item.created_by_id,
        "created_at": item.created_at.replace(tzinfo=item.created_at.tzinfo or timezone.utc).isoformat(),
    }


class ProposalCreate(BaseModel):
    title: str = Field(min_length=3, max_length=180)
    rationale: str = Field(default="", max_length=10_000)
    idempotency_key: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9._:-]+$")
    operations: list[GraphOperation] = Field(min_length=1, max_length=50)
    evidence: list[dict[str, Any]] = Field(default_factory=list, max_length=100)


class ProposalDecision(BaseModel):
    decision: Literal["approved", "rejected"]
    note: str = Field(default="", max_length=5000)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def fingerprint(value: Any) -> str:
    return sha256(canonical(value).encode()).hexdigest()


def relationship_state(item: ObjectRelationship) -> dict[str, Any]:
    return {
        "id": item.id,
        "entity_id": item.entity_id,
        "source_type": item.source_type,
        "source_id": item.source_id,
        "target_type": item.target_type,
        "target_id": item.target_id,
        "relationship_type": item.relationship_type,
        "metadata": dict(item.metadata_json or {}),
        "created_by_id": item.created_by_id,
        "created_at": item.created_at.replace(tzinfo=item.created_at.tzinfo or timezone.utc).isoformat(),
    }


async def operation_context(
    session: AsyncSession,
    user: User,
    operation: GraphOperation,
    *,
    require_edit: bool,
) -> tuple[dict[str, Any], Any, Any]:
    """Return a stable preview plus source and project after access checks."""
    existing: ObjectRelationship | None = None
    if operation.action in {"update", "delete"}:
        existing = await session.get(ObjectRelationship, operation.relationship_id)
        if not existing or existing.entity_id != user.entity_id:
            raise HTTPException(status_code=404, detail="Relationship not found")
        source_type, source_id = existing.source_type, existing.source_id
        target_type, target_id = existing.target_type, existing.target_id
    else:
        source_type, source_id = operation.source_type, operation.source_id
        target_type, target_id = operation.target_type, operation.target_id
        duplicate = await session.scalar(select(ObjectRelationship.id).where(
            ObjectRelationship.entity_id == user.entity_id,
            ObjectRelationship.source_type == source_type,
            ObjectRelationship.source_id == source_id,
            ObjectRelationship.target_type == target_type,
            ObjectRelationship.target_id == target_id,
            ObjectRelationship.relationship_type == operation.relationship_type,
        ))
        if duplicate:
            raise HTTPException(status_code=409, detail="This relationship already exists")

    source = await require_visible_object(session, user, source_type, source_id)
    target = await require_visible_object(session, user, target_type, target_id)
    project = await inherited_project(session, source_type, source)
    if require_edit:
        if not await can_edit_object(session, user, source_type, source):
            raise HTTPException(status_code=403, detail="Editor access to every source object is required")
        policy = await evaluate_policy(session, user, PolicyContext(
            action="edit", resource_type=source_type, resource_id=source_id,
            project_id=project.id if project else None,
        ))
        if not policy.allowed:
            raise HTTPException(status_code=403, detail="Workspace policy does not allow this graph change")

    next_type = operation.relationship_type or (existing.relationship_type if existing else None)
    if existing and operation.action == "update" and next_type != existing.relationship_type:
        collision = await session.scalar(select(ObjectRelationship.id).where(
            ObjectRelationship.entity_id == user.entity_id,
            ObjectRelationship.id != existing.id,
            ObjectRelationship.source_type == source_type,
            ObjectRelationship.source_id == source_id,
            ObjectRelationship.target_type == target_type,
            ObjectRelationship.target_id == target_id,
            ObjectRelationship.relationship_type == next_type,
        ))
        if collision:
            raise HTTPException(status_code=409, detail="That relationship type already exists between these objects")
    if await would_create_cycle(
        session, user.entity_id, (source_type, source_id), (target_type, target_id), next_type,
        excluding_id=existing.id if existing else None,
    ):
        raise HTTPException(status_code=409, detail="This change would create a circular dependency")

    before = relationship_state(existing) if existing else None
    after = None if operation.action == "delete" else {
        **(before or {}),
        "source_type": source_type,
        "source_id": source_id,
        "target_type": target_type,
        "target_id": target_id,
        "relationship_type": next_type,
        "metadata": operation.metadata if operation.metadata is not None else (before or {}).get("metadata", {}),
    }
    preview = {
        "action": operation.action,
        "relationship_id": existing.id if existing else None,
        "source": {"type": source_type, "id": source_id, "title": getattr(source, "title", None) or getattr(source, "summary", None) or getattr(source, "name", source_id)},
        "target": {"type": target_type, "id": target_id, "title": getattr(target, "title", None) or getattr(target, "summary", None) or getattr(target, "name", target_id)},
        "relationship_type": next_type,
        "before": before,
        "after": after,
        "project_id": project.id if project else None,
    }
    return preview, source, project


async def build_preview(
    session: AsyncSession, user: User, operations: list[GraphOperation], *, require_edit: bool,
) -> dict[str, Any]:
    changes = []
    project_ids = set()
    for operation in operations:
        preview, _, project = await operation_context(session, user, operation, require_edit=require_edit)
        changes.append(preview)
        if project:
            project_ids.add(project.id)
    material = [{key: value for key, value in item.items() if key != "project_id"} for item in changes]
    return {
        "changes": changes,
        "change_count": len(changes),
        "project_ids": sorted(project_ids),
        "fingerprint": fingerprint(material),
        "requires_review": True,
        "rollback_supported": True,
    }


async def can_review(session: AsyncSession, user: User, proposal: ChangeProposal) -> bool:
    if proposal.created_by_id == user.id:
        return False
    project_ids = set((proposal.preview or {}).get("project_ids", []))
    if not project_ids:
        return user.role == "admin"
    for project_id in project_ids:
        from .database import Project
        project = await session.get(Project, project_id)
        if not project or not can_approve_project(await project_access_role(session, project, user)):
            return False
        decision = await evaluate_policy(session, user, PolicyContext(
            action="approve", resource_type="project", resource_id=project.id, project_id=project.id,
        ))
        if not decision.allowed and decision.reason == "explicit_deny":
            return False
    return True


async def can_view_proposal(session: AsyncSession, user: User, proposal: ChangeProposal) -> bool:
    if proposal.entity_id != user.entity_id:
        return False
    if user.role == "admin" or proposal.created_by_id == user.id:
        return True
    for change in (proposal.preview or {}).get("changes", []):
        try:
            await require_visible_object(session, user, change["source"]["type"], change["source"]["id"])
            await require_visible_object(session, user, change["target"]["type"], change["target"]["id"])
        except HTTPException:
            return False
    return True


async def visible_evidence(session: AsyncSession, user: User, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for entry in entries:
        object_type, object_id = str(entry.get("type", "")), str(entry.get("id", ""))
        if not object_type or not object_id:
            continue
        try:
            source = await require_visible_object(session, user, object_type, object_id)
        except HTTPException:
            continue
        summary = object_summary(object_type, source)
        result.append({
            "type": object_type, "id": object_id, "title": summary["title"], "url": summary["url"],
            "observed_at": entry.get("observed_at"),
        })
    return result


async def user_names(session: AsyncSession, proposal: ChangeProposal) -> dict[str, str]:
    ids = {value for value in (
        proposal.created_by_id, proposal.reviewed_by_id, proposal.applied_by_id, proposal.rolled_back_by_id,
    ) if value}
    users = list(await session.scalars(select(User).where(User.id.in_(ids)))) if ids else []
    return {item.id: item.display_name for item in users}


async def serialize_proposal(session: AsyncSession, user: User, item: ChangeProposal) -> dict[str, Any]:
    names = await user_names(session, item)
    evidence = await visible_evidence(session, user, item.evidence or [])
    return {
        "id": item.id,
        "title": item.title,
        "rationale": item.rationale,
        "status": item.status,
        "target_type": item.target_type,
        "target_id": item.target_id,
        "idempotency_key": item.idempotency_key,
        "operations": item.operations or [],
        "preview": item.preview or {},
        "evidence": evidence,
        "before_snapshot": item.before_snapshot or [],
        "after_snapshot": item.after_snapshot or [],
        "decision_note": item.decision_note,
        "failure_reason": item.failure_reason,
        "created_by": {"id": item.created_by_id, "display_name": names.get(item.created_by_id, "Unknown")},
        "reviewed_by": {"id": item.reviewed_by_id, "display_name": names.get(item.reviewed_by_id, "Unknown")} if item.reviewed_by_id else None,
        "applied_by": {"id": item.applied_by_id, "display_name": names.get(item.applied_by_id, "Unknown")} if item.applied_by_id else None,
        "rolled_back_by": {"id": item.rolled_back_by_id, "display_name": names.get(item.rolled_back_by_id, "Unknown")} if item.rolled_back_by_id else None,
        "can_review": item.status == "pending" and await can_review(session, user, item),
        "can_apply": item.status == "approved" and await can_review(session, user, item),
        "can_rollback": item.status == "applied" and (user.role == "admin" or item.applied_by_id == user.id),
        "created_at": item.created_at.replace(tzinfo=item.created_at.tzinfo or timezone.utc).isoformat(),
        "updated_at": item.updated_at.replace(tzinfo=item.updated_at.tzinfo or timezone.utc).isoformat(),
        "reviewed_at": item.reviewed_at.replace(tzinfo=item.reviewed_at.tzinfo or timezone.utc).isoformat() if item.reviewed_at else None,
        "applied_at": item.applied_at.replace(tzinfo=item.applied_at.tzinfo or timezone.utc).isoformat() if item.applied_at else None,
        "rolled_back_at": item.rolled_back_at.replace(tzinfo=item.rolled_back_at.tzinfo or timezone.utc).isoformat() if item.rolled_back_at else None,
    }


async def notify_reviewers(session: AsyncSession, user: User, item: ChangeProposal) -> None:
    project_ids = set((item.preview or {}).get("project_ids", []))
    recipient_ids = set(await session.scalars(select(User.id).where(
        User.entity_id == user.entity_id, User.role == "admin", User.id != user.id,
    )))
    if project_ids:
        recipient_ids.update(await session.scalars(select(ProjectCollaborator.user_id).where(
            ProjectCollaborator.project_id.in_(project_ids), ProjectCollaborator.access_role == "approver",
        )))
        recipient_ids.update(await session.scalars(
            select(OrganizationUnitMember.user_id)
            .join(ProjectGroupAccess, ProjectGroupAccess.unit_id == OrganizationUnitMember.unit_id)
            .where(ProjectGroupAccess.project_id.in_(project_ids), ProjectGroupAccess.access_role == "approver")
        ))
    recipient_ids.discard(user.id)
    reviewers = list(await session.scalars(select(User).where(
        User.entity_id == user.entity_id, User.id.in_(recipient_ids), User.account_status == "active",
    ))) if recipient_ids else []
    project_id = next(iter(project_ids), None)
    for reviewer in reviewers:
        session.add(Notification(
            entity_id=user.entity_id, user_id=reviewer.id, actor_id=user.id, kind="approval",
            title=f"Graph change needs review · {item.title}",
            body=f"{len(item.operations or [])} proposed change(s) are waiting for review.",
            project_id=project_id, group_key=f"change-proposal:{item.id}",
        ))


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_proposal(
    payload: ProposalCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await require_entitlement(session, user.entity_id, "governed_changes")
    existing = await session.scalar(select(ChangeProposal).where(
        ChangeProposal.entity_id == user.entity_id,
        ChangeProposal.idempotency_key == payload.idempotency_key,
    ))
    if existing:
        if existing.operations != [item.model_dump(exclude_none=True) for item in payload.operations]:
            raise HTTPException(status_code=409, detail="That idempotency key belongs to a different proposal")
        return await serialize_proposal(session, user, existing)

    operations = [item.model_dump(exclude_none=True) for item in payload.operations]
    preview = await build_preview(session, user, payload.operations, require_edit=True)
    evidence = await visible_evidence(session, user, payload.evidence)
    if len(evidence) != len(payload.evidence):
        raise HTTPException(status_code=422, detail="Every evidence source must be a visible governed object")
    item = ChangeProposal(
        entity_id=user.entity_id, created_by_id=user.id, title=payload.title.strip(),
        rationale=payload.rationale.strip(), idempotency_key=payload.idempotency_key,
        operations=operations, preview=preview, evidence=evidence,
        target_type="relationship", target_id=preview["changes"][0].get("relationship_id"), status="pending",
    )
    session.add(item)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="That idempotency key is already in use") from exc
    await notify_reviewers(session, user, item)
    record_audit_event(
        session, entity_id=user.entity_id, actor_id=user.id, action="change_proposal.created",
        target_type="change_proposal", target_id=item.id,
        details={"fingerprint": preview["fingerprint"], "change_count": preview["change_count"], "evidence": evidence},
    )
    await session.commit()
    await session.refresh(item)
    return await serialize_proposal(session, user, item)


@router.get("")
async def list_proposals(
    proposal_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=250),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    query = select(ChangeProposal).where(ChangeProposal.entity_id == user.entity_id)
    if proposal_status:
        query = query.where(ChangeProposal.status == proposal_status)
    rows = list(await session.scalars(query.order_by(ChangeProposal.updated_at.desc()).limit(limit)))
    visible = [item for item in rows if await can_view_proposal(session, user, item)]
    return {"items": [await serialize_proposal(session, user, item) for item in visible], "count": len(visible)}


@router.get("/{proposal_id}")
async def get_proposal(
    proposal_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    item = await session.get(ChangeProposal, proposal_id)
    if not item or not await can_view_proposal(session, user, item):
        raise HTTPException(status_code=404, detail="Change proposal not found")
    return await serialize_proposal(session, user, item)


@router.post("/{proposal_id}/decision")
async def decide_proposal(
    proposal_id: str,
    payload: ProposalDecision,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    item = await session.get(ChangeProposal, proposal_id)
    if not item or item.entity_id != user.entity_id:
        raise HTTPException(status_code=404, detail="Change proposal not found")
    if item.status != "pending":
        raise HTTPException(status_code=409, detail="This proposal has already been reviewed")
    if not await can_review(session, user, item):
        if item.created_by_id == user.id:
            raise HTTPException(status_code=403, detail="A separate reviewer must approve this proposal")
        raise HTTPException(status_code=403, detail="Approver access is required")
    item.status = payload.decision
    item.reviewed_by_id = user.id
    item.reviewed_at = now_utc()
    item.decision_note = payload.note.strip()
    item.updated_at = now_utc()
    session.add(Notification(
        entity_id=user.entity_id, user_id=item.created_by_id, actor_id=user.id, kind="approval",
        title=f"Graph change {payload.decision} · {item.title}", body=item.decision_note or f"Proposal was {payload.decision}.",
        project_id=next(iter((item.preview or {}).get("project_ids", [])), None),
        group_key=f"change-proposal:{item.id}:decision",
    ))
    record_audit_event(
        session, entity_id=user.entity_id, actor_id=user.id, action=f"change_proposal.{payload.decision}",
        target_type="change_proposal", target_id=item.id,
        details={"fingerprint": (item.preview or {}).get("fingerprint"), "note": item.decision_note},
    )
    await session.commit()
    return await serialize_proposal(session, user, item)


async def require_apply_authority(session: AsyncSession, user: User, item: ChangeProposal) -> None:
    if not await can_review(session, user, item):
        raise HTTPException(status_code=403, detail="The reviewer or another authorized approver must apply this proposal")


@router.post("/{proposal_id}/apply")
async def apply_proposal(
    proposal_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    item = await session.get(ChangeProposal, proposal_id)
    if not item or item.entity_id != user.entity_id:
        raise HTTPException(status_code=404, detail="Change proposal not found")
    if item.status == "applied":
        return await serialize_proposal(session, user, item)
    if item.status != "approved":
        raise HTTPException(status_code=409, detail="Only an approved proposal can be applied")
    await require_apply_authority(session, user, item)
    operations = [GraphOperation.model_validate(value) for value in item.operations or []]
    current_preview = await build_preview(session, user, operations, require_edit=False)
    if current_preview["fingerprint"] != (item.preview or {}).get("fingerprint"):
        raise HTTPException(status_code=409, detail="The graph changed after review. Create a fresh proposal before applying.")

    before_snapshots, after_snapshots = [], []
    try:
        for operation, change in zip(operations, current_preview["changes"]):
            before_snapshots.append(change["before"])
            if operation.action == "create":
                created = ObjectRelationship(
                    entity_id=user.entity_id, created_by_id=item.created_by_id,
                    source_type=change["source"]["type"], source_id=change["source"]["id"],
                    target_type=change["target"]["type"], target_id=change["target"]["id"],
                    relationship_type=change["relationship_type"], metadata_json=change["after"]["metadata"],
                )
                session.add(created)
                await session.flush()
                session.add(relationship_snapshot(created, "created", user.id))
                after_snapshots.append(relationship_state(created))
            else:
                relationship = await session.get(ObjectRelationship, operation.relationship_id)
                if operation.action == "update":
                    relationship.relationship_type = change["after"]["relationship_type"]
                    relationship.metadata_json = change["after"]["metadata"]
                    session.add(relationship_snapshot(relationship, "updated", user.id))
                    after_snapshots.append(relationship_state(relationship))
                else:
                    session.add(relationship_snapshot(relationship, "deleted", user.id))
                    await session.delete(relationship)
                    after_snapshots.append(None)
        item.before_snapshot = before_snapshots
        item.after_snapshot = after_snapshots
        item.status = "applied"
        item.applied_by_id = user.id
        item.applied_at = now_utc()
        item.updated_at = now_utc()
        record_audit_event(
            session, entity_id=user.entity_id, actor_id=user.id, action="change_proposal.applied",
            target_type="change_proposal", target_id=item.id,
            details={"fingerprint": current_preview["fingerprint"], "before": before_snapshots, "after": after_snapshots},
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return await serialize_proposal(session, user, item)


def equivalent_relationship(item: ObjectRelationship, snapshot: dict[str, Any]) -> bool:
    return all((
        item.source_type == snapshot["source_type"], item.source_id == snapshot["source_id"],
        item.target_type == snapshot["target_type"], item.target_id == snapshot["target_id"],
        item.relationship_type == snapshot["relationship_type"], dict(item.metadata_json or {}) == snapshot["metadata"],
    ))


@router.post("/{proposal_id}/rollback")
async def rollback_proposal(
    proposal_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    item = await session.get(ChangeProposal, proposal_id)
    if not item or item.entity_id != user.entity_id:
        raise HTTPException(status_code=404, detail="Change proposal not found")
    if item.status == "rolled_back":
        return await serialize_proposal(session, user, item)
    if item.status != "applied":
        raise HTTPException(status_code=409, detail="Only an applied proposal can be rolled back")
    if user.role != "admin" and item.applied_by_id != user.id:
        raise HTTPException(status_code=403, detail="Administrator access is required to roll back this change")

    records = list(zip(item.operations or [], item.before_snapshot or [], item.after_snapshot or []))
    try:
        for raw_operation, before, after in reversed(records):
            operation = GraphOperation.model_validate(raw_operation)
            if operation.action == "create":
                relationship = await session.get(ObjectRelationship, after["id"])
                if not relationship or not equivalent_relationship(relationship, after):
                    raise HTTPException(status_code=409, detail="Rollback stopped because a created relationship changed")
                session.add(relationship_snapshot(relationship, "rolled_back", user.id))
                await session.delete(relationship)
            elif operation.action == "update":
                relationship = await session.get(ObjectRelationship, after["id"])
                if not relationship or not equivalent_relationship(relationship, after):
                    raise HTTPException(status_code=409, detail="Rollback stopped because an updated relationship changed")
                relationship.relationship_type = before["relationship_type"]
                relationship.metadata_json = before["metadata"]
                session.add(relationship_snapshot(relationship, "rolled_back", user.id))
            else:
                collision = await session.scalar(select(ObjectRelationship.id).where(
                    ObjectRelationship.entity_id == user.entity_id,
                    and_(
                        ObjectRelationship.source_type == before["source_type"],
                        ObjectRelationship.source_id == before["source_id"],
                        ObjectRelationship.target_type == before["target_type"],
                        ObjectRelationship.target_id == before["target_id"],
                        ObjectRelationship.relationship_type == before["relationship_type"],
                    ),
                ))
                if collision:
                    raise HTTPException(status_code=409, detail="Rollback stopped because the deleted relationship was recreated")
                restored = ObjectRelationship(
                    id=before["id"], entity_id=before["entity_id"], created_by_id=before["created_by_id"],
                    source_type=before["source_type"], source_id=before["source_id"],
                    target_type=before["target_type"], target_id=before["target_id"],
                    relationship_type=before["relationship_type"], metadata_json=before["metadata"],
                )
                session.add(restored)
                await session.flush()
                session.add(relationship_snapshot(restored, "rolled_back", user.id))
        item.status = "rolled_back"
        item.rolled_back_by_id = user.id
        item.rolled_back_at = now_utc()
        item.updated_at = now_utc()
        record_audit_event(
            session, entity_id=user.entity_id, actor_id=user.id, action="change_proposal.rolled_back",
            target_type="change_proposal", target_id=item.id,
            details={"applied_at": item.applied_at.isoformat() if item.applied_at else None, "operation_count": len(records)},
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return await serialize_proposal(session, user, item)
