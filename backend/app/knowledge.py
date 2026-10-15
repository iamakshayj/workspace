import re
from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import get_current_user
from .communications import communication_hub, serialize_notification
from .database import (
    KnowledgeComment,
    KnowledgeDocument,
    KnowledgeDocumentAccess,
    KnowledgeDocumentLink,
    KnowledgeDocumentRevision,
    KnowledgeSpace,
    KnowledgeSpaceMember,
    Notification,
    User,
    get_session,
)
from .governance import record_audit_event
from .identity import as_utc, user_handle, user_summary
from .policy_engine import authorize, enforce_dlp


router = APIRouter(prefix="/knowledge", tags=["knowledge"])
ACCESS_ROLES = {"viewer", "commenter", "editor"}
EDIT_ROLES = {"admin", "owner", "editor"}
COMMENT_ROLES = EDIT_ROLES | {"commenter"}
VISIBILITIES = {"workspace", "restricted"}
STATUSES = {"draft", "published", "archived"}
CLASSIFICATIONS = {"public", "internal", "confidential", "restricted"}
DOC_LINK_PATTERN = re.compile(r"\[\[doc:([0-9a-fA-F-]{36})\]\]")
MENTION_PATTERN = re.compile(r"(?<![\w@])@([a-zA-Z0-9._-]{2,80})")

TEMPLATES = [
    {"id": "blank", "name": "Blank page", "description": "Start with an empty document.", "body": ""},
    {"id": "project_brief", "name": "Project brief", "description": "Align outcomes, scope, owners, and risks.",
     "body": "# Objective\n\n## Success measures\n\n## Scope\n\n## Owners\n\n## Risks and decisions\n"},
    {"id": "sop", "name": "Standard operating procedure", "description": "Document a repeatable, governed process.",
     "body": "# Purpose\n\n## Scope\n\n## Roles\n\n## Procedure\n\n1. First step\n\n## Controls\n\n## Exceptions\n"},
    {"id": "meeting_notes", "name": "Meeting notes", "description": "Capture decisions and actions.",
     "body": "# Agenda\n\n## Notes\n\n## Decisions\n\n## Action items\n\n- [ ] Owner — action — due date\n"},
    {"id": "decision_record", "name": "Decision record", "description": "Preserve context and consequences.",
     "body": "# Decision\n\n## Status\nProposed\n\n## Context\n\n## Options considered\n\n## Outcome and consequences\n"},
    {"id": "policy", "name": "Policy", "description": "Create reviewable policy knowledge.",
     "body": "# Policy statement\n\n## Applicability\n\n## Requirements\n\n## Exceptions\n\n## Evidence and controls\n"},
    {"id": "product_requirements", "name": "Product requirements", "description": "Align a team on the problem, scope, and acceptance signals.",
     "body": "# Problem\n\n## Goals and success metrics\n\n## User stories\n\n## Requirements\n\n## Out of scope\n\n## Open questions\n"},
    {"id": "retrospective", "name": "Team retrospective", "description": "Reflect on outcomes and commit to improvements.",
     "body": "# Sprint retrospective\n\n## What went well\n\n## What was difficult\n\n## What we learned\n\n## Action items\n\n- [ ] Owner — improvement — due date\n"},
    {"id": "incident_review", "name": "Incident review", "description": "Create a blameless operational record and follow-up plan.",
     "body": "# Incident summary\n\n:::warning\nCustomer impact and current state\n:::\n\n## Timeline\n\n## Root cause\n\n## Resolution\n\n## Corrective actions\n\n- [ ] Owner — action — due date\n"},
    {"id": "how_to", "name": "How-to guide", "description": "Teach a task with prerequisites and verified steps.",
     "body": "# Outcome\n\n## Before you begin\n\n## Steps\n\n1. First step\n\n## Verification\n\n## Troubleshooting\n"},
    {"id": "team_home", "name": "Team homepage", "description": "Give a team a navigable home for goals, people, and resources.",
     "body": "# Team mission\n\n## Current priorities\n\n## People and responsibilities\n\n## Key links\n\n## Ways of working\n\n## Updates\n"},
]


class AccessEntry(BaseModel):
    user_id: str = Field(min_length=36, max_length=36)
    role: Literal["viewer", "commenter", "editor"] = "viewer"


class SpaceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=500)
    visibility: Literal["workspace", "restricted"] = "workspace"
    members: list[AccessEntry] = Field(default_factory=list, max_length=500)

    @field_validator("name", "description")
    @classmethod
    def trim_text(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed and value:
            raise ValueError("Text cannot contain only whitespace")
        return trimmed

    @field_validator("members")
    @classmethod
    def unique_space_members(cls, value: list[AccessEntry]) -> list[AccessEntry]:
        if len({item.user_id for item in value}) != len(value):
            raise ValueError("A member can appear only once")
        return value


class SpaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    visibility: Literal["workspace", "restricted"] | None = None
    members: list[AccessEntry] | None = Field(default=None, max_length=500)

    @field_validator("name", "description")
    @classmethod
    def trim_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        trimmed = value.strip()
        if not trimmed and value:
            raise ValueError("Text cannot contain only whitespace")
        return trimmed

    @field_validator("members")
    @classmethod
    def unique_updated_members(cls, value: list[AccessEntry] | None) -> list[AccessEntry] | None:
        if value is not None and len({item.user_id for item in value}) != len(value):
            raise ValueError("A member can appear only once")
        return value


class DocumentCreate(BaseModel):
    space_id: str
    parent_id: str | None = None
    title: str = Field(min_length=1, max_length=180)
    summary: str = Field(default="", max_length=500)
    body: str = Field(default="", max_length=1_000_000)
    status: Literal["draft", "published"] = "draft"
    visibility: Literal["workspace", "restricted"] = "workspace"
    classification: Literal["public", "internal", "confidential", "restricted"] = "internal"
    template: str = Field(default="blank", max_length=40)
    icon: str = Field(default="▤", min_length=1, max_length=16)
    labels: list[str] = Field(default_factory=list, max_length=30)
    owner_id: str | None = None
    review_due_at: date | None = None
    expires_at: date | None = None
    access: list[AccessEntry] = Field(default_factory=list, max_length=500)

    @field_validator("title", "summary")
    @classmethod
    def trim_document_text(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed and value:
            raise ValueError("Text cannot contain only whitespace")
        return trimmed

    @model_validator(mode="after")
    def validate_lifecycle_dates(self) -> "DocumentCreate":
        if self.review_due_at and self.expires_at and self.expires_at < self.review_due_at:
            raise ValueError("Expiry cannot be earlier than the review date")
        if self.template not in {item["id"] for item in TEMPLATES}:
            raise ValueError("Unknown document template")
        if len({item.user_id for item in self.access}) != len(self.access):
            raise ValueError("A member can appear only once")
        self.labels = list(dict.fromkeys(label.strip().lower()[:40] for label in self.labels if label.strip()))
        return self


class DocumentUpdate(BaseModel):
    expected_revision: int = Field(ge=0)
    title: str | None = Field(default=None, min_length=1, max_length=180)
    summary: str | None = Field(default=None, max_length=500)
    body: str | None = Field(default=None, max_length=1_000_000)
    space_id: str | None = None
    parent_id: str | None = None
    status: Literal["draft", "published", "archived"] | None = None
    visibility: Literal["workspace", "restricted"] | None = None
    classification: Literal["public", "internal", "confidential", "restricted"] | None = None
    icon: str | None = Field(default=None, min_length=1, max_length=16)
    labels: list[str] | None = Field(default=None, max_length=30)
    position: int | None = Field(default=None, ge=0)
    owner_id: str | None = None
    review_due_at: date | None = None
    expires_at: date | None = None
    change_summary: str = Field(default="Saved changes", max_length=240)


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=10_000)
    parent_id: str | None = None

    @field_validator("body")
    @classmethod
    def trim_body(cls, value: str) -> str:
        return value.strip()


class AccessUpdate(BaseModel):
    entries: list[AccessEntry] = Field(default_factory=list, max_length=500)

    @field_validator("entries")
    @classmethod
    def unique_access_entries(cls, value: list[AccessEntry]) -> list[AccessEntry]:
        if len({item.user_id for item in value}) != len(value):
            raise ValueError("A member can appear only once")
        return value


class RestoreRequest(BaseModel):
    expected_revision: int = Field(ge=0)


class FollowRequest(BaseModel):
    following: bool


class DuplicateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=180)
    space_id: str | None = None
    parent_id: str | None = None


def slug_base(title: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return value[:180] or "document"


async def unique_slug(session: AsyncSession, entity_id: str, title: str) -> str:
    base = slug_base(title)
    candidate = base
    suffix = 2
    while await session.scalar(select(KnowledgeDocument.id).where(
        KnowledgeDocument.entity_id == entity_id, KnowledgeDocument.slug == candidate
    )):
        candidate = f"{base[:170]}-{suffix}"
        suffix += 1
    return candidate


async def same_entity_users(session: AsyncSession, entity_id: str, ids: set[str]) -> dict[str, User]:
    if not ids:
        return {}
    users = (await session.scalars(select(User).where(User.entity_id == entity_id, User.id.in_(ids)))).all()
    if len(users) != len(ids):
        raise HTTPException(status_code=400, detail="Every selected member must belong to this workspace")
    return {item.id: item for item in users}


async def space_role(session: AsyncSession, space: KnowledgeSpace, user: User) -> str | None:
    if space.entity_id != user.entity_id:
        return None
    if user.role == "admin":
        return "admin"
    if space.created_by_id == user.id:
        return "owner"
    role = await session.scalar(select(KnowledgeSpaceMember.role).where(
        KnowledgeSpaceMember.space_id == space.id, KnowledgeSpaceMember.user_id == user.id
    ))
    return role or ("viewer" if user.role != "guest" and space.visibility == "workspace" else None)


async def document_role(session: AsyncSession, document: KnowledgeDocument, user: User) -> str | None:
    if document.entity_id != user.entity_id:
        return None
    if user.role == "admin":
        return "admin"
    if document.owner_id == user.id:
        return "owner"
    explicit = await session.scalar(select(KnowledgeDocumentAccess.role).where(
        KnowledgeDocumentAccess.document_id == document.id, KnowledgeDocumentAccess.user_id == user.id
    ))
    if explicit:
        return explicit
    if document.visibility == "workspace":
        space = await session.get(KnowledgeSpace, document.space_id)
        if space and await space_role(session, space, user):
            return "viewer"
    return None


async def require_space(session: AsyncSession, space_id: str, user: User, editable: bool = False) -> tuple[KnowledgeSpace, str]:
    space = await session.get(KnowledgeSpace, space_id)
    role = await space_role(session, space, user) if space else None
    if not space or not role:
        raise HTTPException(status_code=404, detail="Knowledge space not found")
    if editable and role not in EDIT_ROLES:
        raise HTTPException(status_code=403, detail="Editor access to this space is required")
    return space, role


async def require_document(session: AsyncSession, document_id: str, user: User) -> tuple[KnowledgeDocument, str]:
    document = await session.get(KnowledgeDocument, document_id)
    role = await document_role(session, document, user) if document else None
    if not document or not role:
        raise HTTPException(status_code=404, detail="Document not found")
    await authorize(
        session, user, action="read", resource_type="document", resource_id=document.id,
        classification=document.classification, source_type="document", preauthorized=True,
    )
    return document, role


async def validate_document_parent(
    session: AsyncSession, parent_id: str | None, entity_id: str, space_id: str,
    document_id: str | None = None,
) -> KnowledgeDocument | None:
    if not parent_id:
        return None
    parent = await session.get(KnowledgeDocument, parent_id)
    if not parent or parent.entity_id != entity_id or parent.space_id != space_id:
        raise HTTPException(status_code=400, detail="Parent page must belong to the same knowledge space")
    if parent.id == document_id:
        raise HTTPException(status_code=400, detail="A page cannot be its own parent")
    visited: set[str] = set()
    cursor = parent
    while cursor and cursor.id not in visited:
        if cursor.id == document_id:
            raise HTTPException(status_code=400, detail="Moving this page would create a circular page tree")
        visited.add(cursor.id)
        cursor = await session.get(KnowledgeDocument, cursor.parent_id) if cursor.parent_id else None
    return parent


async def next_sibling_position(session: AsyncSession, space_id: str, parent_id: str | None) -> int:
    query = select(func.max(KnowledgeDocument.position)).where(KnowledgeDocument.space_id == space_id)
    query = query.where(
        KnowledgeDocument.parent_id == parent_id if parent_id else KnowledgeDocument.parent_id.is_(None)
    )
    return (await session.scalar(query) or 0) + 1024


async def snapshot_document(session: AsyncSession, document: KnowledgeDocument, actor_id: str, summary: str) -> KnowledgeDocumentRevision:
    version = (await session.scalar(select(func.max(KnowledgeDocumentRevision.version)).where(
        KnowledgeDocumentRevision.document_id == document.id
    )) or 0) + 1
    revision = KnowledgeDocumentRevision(
        document_id=document.id, version=version, title=document.title, summary=document.summary,
        body=document.body, status=document.status, classification=document.classification,
        change_summary=summary.strip()[:240] or "Saved changes", created_by_id=actor_id,
    )
    session.add(revision)
    await session.flush()
    return revision


async def sync_links(session: AsyncSession, document: KnowledgeDocument) -> None:
    target_ids = {item for item in DOC_LINK_PATTERN.findall(document.body or "") if item != document.id}
    await session.execute(delete(KnowledgeDocumentLink).where(KnowledgeDocumentLink.source_document_id == document.id))
    if not target_ids:
        return
    targets = (await session.scalars(select(KnowledgeDocument.id).where(
        KnowledgeDocument.entity_id == document.entity_id, KnowledgeDocument.id.in_(target_ids)
    ))).all()
    session.add_all([KnowledgeDocumentLink(source_document_id=document.id, target_document_id=target) for target in targets])


def document_summary(document: KnowledgeDocument, owner: User | None, space: KnowledgeSpace | None) -> dict:
    today = date.today()
    return {
        "id": document.id, "space_id": document.space_id, "space_name": space.name if space else "",
        "parent_id": document.parent_id, "position": document.position,
        "owner": user_summary(owner) if owner else None, "title": document.title, "slug": document.slug,
        "summary": document.summary, "status": document.status, "visibility": document.visibility,
        "classification": document.classification, "template": document.template,
        "icon": document.icon or "▤", "labels": document.labels or [],
        "review_due_at": document.review_due_at.isoformat() if document.review_due_at else None,
        "expires_at": document.expires_at.isoformat() if document.expires_at else None,
        "review_overdue": bool(document.review_due_at and document.review_due_at < today),
        "expired": bool(document.expires_at and document.expires_at < today),
        "revision": document.revision, "updated_at": as_utc(document.updated_at).isoformat(),
    }


async def serialize_space(session: AsyncSession, space: KnowledgeSpace, user: User) -> dict:
    role = await space_role(session, space, user)
    count = await session.scalar(select(func.count(KnowledgeDocument.id)).where(
        KnowledgeDocument.space_id == space.id, KnowledgeDocument.status != "archived"
    ))
    return {"id": space.id, "name": space.name, "description": space.description,
            "visibility": space.visibility, "current_user_access": role, "document_count": count or 0,
            "created_by_id": space.created_by_id, "updated_at": as_utc(space.updated_at).isoformat()}


@router.get("/templates")
async def list_templates(_: User = Depends(get_current_user)) -> list[dict]:
    return TEMPLATES


@router.get("/overview")
async def knowledge_overview(
    search: str = "", space_id: str | None = None, include_archived: bool = False,
    session: AsyncSession = Depends(get_session), user: User = Depends(get_current_user),
) -> dict:
    spaces = (await session.scalars(select(KnowledgeSpace).where(
        KnowledgeSpace.entity_id == user.entity_id
    ).order_by(KnowledgeSpace.name.asc()))).all()
    visible_spaces = [item for item in spaces if await space_role(session, item, user)]
    space_map = {item.id: item for item in spaces}
    query = select(KnowledgeDocument).where(KnowledgeDocument.entity_id == user.entity_id)
    if space_id:
        query = query.where(KnowledgeDocument.space_id == space_id)
    if not include_archived:
        query = query.where(KnowledgeDocument.status != "archived")
    if search.strip():
        term = f"%{search.strip()}%"
        query = query.where(or_(KnowledgeDocument.title.ilike(term), KnowledgeDocument.summary.ilike(term), KnowledgeDocument.body.ilike(term)))
    if user.role != "admin":
        granted_document_ids = select(KnowledgeDocumentAccess.document_id).where(
            KnowledgeDocumentAccess.user_id == user.id
        )
        query = query.where(or_(
            KnowledgeDocument.owner_id == user.id,
            KnowledgeDocument.id.in_(granted_document_ids),
            (KnowledgeDocument.visibility == "workspace")
            & KnowledgeDocument.space_id.in_([item.id for item in visible_spaces]),
        ))
    documents = (await session.scalars(query.order_by(KnowledgeDocument.updated_at.desc()).limit(2_000))).all()
    owners = await same_entity_users(session, user.entity_id, {item.owner_id for item in documents}) if documents else {}
    serialized = [document_summary(item, owners.get(item.owner_id), space_map.get(item.space_id)) for item in documents]
    return {
        "spaces": [await serialize_space(session, item, user) for item in visible_spaces],
        "documents": serialized, "templates": TEMPLATES,
        "counts": {"documents": len(serialized), "needs_review": sum(item["review_overdue"] for item in serialized),
                   "expired": sum(item["expired"] for item in serialized),
                   "drafts": sum(item["status"] == "draft" for item in serialized),
                   "published": sum(item["status"] == "published" for item in serialized)},
    }


@router.post("/spaces", status_code=status.HTTP_201_CREATED)
async def create_space(
    payload: SpaceCreate, session: AsyncSession = Depends(get_session), user: User = Depends(get_current_user),
) -> dict:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only workspace admins can create knowledge spaces")
    members = await same_entity_users(session, user.entity_id, {item.user_id for item in payload.members})
    space = KnowledgeSpace(entity_id=user.entity_id, name=payload.name, description=payload.description,
                           visibility=payload.visibility, created_by_id=user.id)
    session.add(space)
    await session.flush()
    session.add_all([KnowledgeSpaceMember(space_id=space.id, user_id=item.user_id, role=item.role)
                     for item in payload.members if item.user_id in members and item.user_id != user.id])
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="knowledge.space.created",
                       target_type="knowledge_space", target_id=space.id, details={"name": space.name})
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise HTTPException(status_code=409, detail="A knowledge space with this name already exists") from error
    await session.refresh(space)
    return await serialize_space(session, space, user)


@router.put("/spaces/{space_id}")
async def update_space(
    space_id: str, payload: SpaceUpdate, session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict:
    space, role = await require_space(session, space_id, user)
    if role not in {"admin", "owner"}:
        raise HTTPException(status_code=403, detail="Only the space owner or an admin can manage this space")
    changes = payload.model_dump(exclude_none=True, exclude={"members"})
    for key, value in changes.items():
        setattr(space, key, value.strip() if isinstance(value, str) else value)
    if payload.members is not None:
        users = await same_entity_users(session, user.entity_id, {item.user_id for item in payload.members})
        await session.execute(delete(KnowledgeSpaceMember).where(KnowledgeSpaceMember.space_id == space.id))
        session.add_all([KnowledgeSpaceMember(space_id=space.id, user_id=item.user_id, role=item.role)
                         for item in payload.members if item.user_id in users and item.user_id != space.created_by_id])
    space.updated_at = datetime.now(timezone.utc)
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="knowledge.space.updated",
                       target_type="knowledge_space", target_id=space.id)
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise HTTPException(status_code=409, detail="A knowledge space with this name already exists") from error
    await session.refresh(space)
    return await serialize_space(session, space, user)


@router.post("/documents", status_code=status.HTTP_201_CREATED)
async def create_document(
    payload: DocumentCreate, session: AsyncSession = Depends(get_session), user: User = Depends(get_current_user),
) -> dict:
    await require_space(session, payload.space_id, user, editable=True)
    await authorize(session, user, action="create", resource_type="document", classification=payload.classification, source_type="document", preauthorized=True)
    await enforce_dlp(session, user, content=f"{payload.title}\n{payload.summary}\n{payload.body}", source_type="document", action="create", classification=payload.classification)
    await validate_document_parent(session, payload.parent_id, user.entity_id, payload.space_id)
    owner_id = payload.owner_id or user.id
    await same_entity_users(session, user.entity_id, {owner_id} | {item.user_id for item in payload.access})
    template = next(item for item in TEMPLATES if item["id"] == payload.template)
    position = await next_sibling_position(session, payload.space_id, payload.parent_id)
    document = KnowledgeDocument(
        entity_id=user.entity_id, space_id=payload.space_id, parent_id=payload.parent_id,
        owner_id=owner_id, title=payload.title,
        slug=await unique_slug(session, user.entity_id, payload.title), summary=payload.summary,
        body=payload.body or template["body"], status=payload.status, visibility=payload.visibility,
        classification=payload.classification, template=payload.template, icon=payload.icon,
        labels=payload.labels, watcher_ids=[user.id], position=position,
        review_due_at=payload.review_due_at, expires_at=payload.expires_at, revision=1,
    )
    session.add(document)
    await session.flush()
    session.add_all([KnowledgeDocumentAccess(document_id=document.id, user_id=item.user_id, role=item.role)
                     for item in payload.access if item.user_id != owner_id])
    await sync_links(session, document)
    await snapshot_document(session, document, user.id, "Document created")
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="knowledge.document.created",
                       target_type="knowledge_document", target_id=document.id, details={"classification": document.classification})
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise HTTPException(status_code=409, detail="A document with this title was created at the same time; retry the request") from error
    return await get_document(document.id, session, user)


@router.get("/documents/{document_id}")
async def get_document(
    document_id: str, session: AsyncSession = Depends(get_session), user: User = Depends(get_current_user),
) -> dict:
    document, role = await require_document(session, document_id, user)
    space = await session.get(KnowledgeSpace, document.space_id)
    ids = {document.owner_id} | set(document.watcher_ids or [])
    access = (await session.scalars(select(KnowledgeDocumentAccess).where(
        KnowledgeDocumentAccess.document_id == document.id
    ))).all()
    comments = (await session.scalars(select(KnowledgeComment).where(
        KnowledgeComment.document_id == document.id
    ).order_by(KnowledgeComment.created_at.asc()))).all()
    revisions = (await session.scalars(select(KnowledgeDocumentRevision).where(
        KnowledgeDocumentRevision.document_id == document.id
    ).order_by(KnowledgeDocumentRevision.version.desc()).limit(100))).all()
    ids |= {item.user_id for item in access} | {item.author_id for item in comments} | {item.created_by_id for item in revisions}
    users = await same_entity_users(session, user.entity_id, ids)
    outbound_ids = (await session.scalars(select(KnowledgeDocumentLink.target_document_id).where(
        KnowledgeDocumentLink.source_document_id == document.id
    ))).all()
    inbound_ids = (await session.scalars(select(KnowledgeDocumentLink.source_document_id).where(
        KnowledgeDocumentLink.target_document_id == document.id
    ))).all()
    linked_docs = (await session.scalars(select(KnowledgeDocument).where(
        KnowledgeDocument.id.in_(set(outbound_ids) | set(inbound_ids))
    ))).all() if outbound_ids or inbound_ids else []
    linked = {item.id: item for item in linked_docs if await document_role(session, item, user)}
    result = document_summary(document, users.get(document.owner_id), space)
    result.update({
        "body": document.body, "current_user_access": role, "can_edit": role in EDIT_ROLES,
        "can_comment": role in COMMENT_ROLES, "can_manage": role in {"admin", "owner"},
        "following": user.id in (document.watcher_ids or []),
        "watchers": [user_summary(users[item]) for item in (document.watcher_ids or []) if item in users],
        "access": [{"user": user_summary(users[item.user_id]), "role": item.role} for item in access],
        "comments": [{"id": item.id, "body": item.body, "parent_id": item.parent_id,
                      "resolved": item.resolved, "resolved_at": as_utc(item.resolved_at).isoformat() if item.resolved_at else None,
                      "created_at": as_utc(item.created_at).isoformat(), "author": user_summary(users[item.author_id])}
                     for item in comments],
        "revisions": [{"id": item.id, "version": item.version, "change_summary": item.change_summary,
                       "created_at": as_utc(item.created_at).isoformat(), "created_by": user_summary(users[item.created_by_id])}
                      for item in revisions],
        "outbound_links": [{"id": item, "title": linked[item].title} for item in outbound_ids if item in linked],
        "backlinks": [{"id": item, "title": linked[item].title} for item in inbound_ids if item in linked],
    })
    return result


@router.put("/documents/{document_id}")
async def update_document(
    document_id: str, payload: DocumentUpdate, session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict:
    document, role = await require_document(session, document_id, user)
    if role not in EDIT_ROLES:
        raise HTTPException(status_code=403, detail="Editor access is required")
    if document.revision != payload.expected_revision:
        raise HTTPException(status_code=409, detail={"message": "This document changed since you opened it", "current_revision": document.revision})
    changes = payload.model_dump(exclude_unset=True, exclude={"expected_revision", "change_summary"})
    await authorize(
        session, user, action="edit", resource_type="document", resource_id=document.id,
        fields=changes.keys(), classification=str(changes.get("classification") or document.classification),
        source_type="document", preauthorized=True,
    )
    proposed_content = "\n".join(str(changes.get(key, getattr(document, key))) for key in ("title", "summary", "body"))
    await enforce_dlp(
        session, user, content=proposed_content, source_type="document", action="edit",
        classification=str(changes.get("classification") or document.classification),
    )
    if "labels" in changes and changes["labels"] is not None:
        changes["labels"] = list(dict.fromkeys(label.strip().lower()[:40] for label in changes["labels"] if label.strip()))
    destination_space_id = changes.get("space_id", document.space_id)
    if "space_id" in changes:
        await require_space(session, destination_space_id, user, editable=True)
    destination_parent_id = changes.get("parent_id", document.parent_id)
    await validate_document_parent(session, destination_parent_id, user.entity_id, destination_space_id, document.id)
    if "owner_id" in changes:
        await same_entity_users(session, user.entity_id, {changes["owner_id"]})
    for key, value in changes.items():
        setattr(document, key, value.strip() if isinstance(value, str) else value)
    if document.review_due_at and document.expires_at and document.expires_at < document.review_due_at:
        raise HTTPException(status_code=422, detail="Expiry cannot be earlier than the review date")
    document.revision += 1
    document.updated_at = datetime.now(timezone.utc)
    await sync_links(session, document)
    await snapshot_document(session, document, user.id, payload.change_summary)
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="knowledge.document.updated",
                       target_type="knowledge_document", target_id=document.id,
                       details={"revision": document.revision, "status": document.status})
    follower_ids = set(document.watcher_ids or []) - {user.id}
    followers = (await session.scalars(select(User).where(
        User.entity_id == user.entity_id, User.id.in_(follower_ids)
    ))).all() if follower_ids else []
    notifications = [Notification(
        entity_id=user.entity_id, user_id=member.id, actor_id=user.id,
        kind="document_updated", title=f"{document.title} was updated",
        body=payload.change_summary or "Saved changes", document_id=document.id,
    ) for member in followers]
    session.add_all(notifications)
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        current = await session.get(KnowledgeDocument, document_id)
        raise HTTPException(status_code=409, detail={
            "message": "This document changed while it was being saved",
            "current_revision": current.revision if current else None,
        }) from error
    for notification, member in zip(notifications, followers):
        await session.refresh(notification)
        await communication_hub.publish(member.id, {
            "type": "notification", "notification": serialize_notification(notification, user),
        })
    return await get_document(document.id, session, user)


@router.put("/documents/{document_id}/follow")
async def follow_document(
    document_id: str, payload: FollowRequest, session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict:
    document, _ = await require_document(session, document_id, user)
    watcher_ids = list(dict.fromkeys(document.watcher_ids or []))
    if payload.following and user.id not in watcher_ids:
        watcher_ids.append(user.id)
    elif not payload.following:
        watcher_ids = [item for item in watcher_ids if item != user.id]
    document.watcher_ids = watcher_ids
    record_audit_event(
        session, entity_id=user.entity_id, actor_id=user.id,
        action="knowledge.document.followed" if payload.following else "knowledge.document.unfollowed",
        target_type="knowledge_document", target_id=document.id,
    )
    await session.commit()
    return await get_document(document.id, session, user)


@router.post("/documents/{document_id}/duplicate", status_code=status.HTTP_201_CREATED)
async def duplicate_document(
    document_id: str, payload: DuplicateRequest, session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict:
    source, _ = await require_document(session, document_id, user)
    destination_space_id = payload.space_id or source.space_id
    await require_space(session, destination_space_id, user, editable=True)
    parent_id = payload.parent_id if "parent_id" in payload.model_fields_set else source.parent_id
    await validate_document_parent(session, parent_id, user.entity_id, destination_space_id)
    title = (payload.title or f"{source.title} (copy)").strip()
    position = await next_sibling_position(session, destination_space_id, parent_id)
    duplicate = KnowledgeDocument(
        entity_id=user.entity_id, space_id=destination_space_id, parent_id=parent_id,
        owner_id=user.id, title=title, slug=await unique_slug(session, user.entity_id, title),
        summary=source.summary, body=source.body, status="draft", visibility=source.visibility,
        classification=source.classification, template=source.template, icon=source.icon or "▤",
        labels=list(source.labels or []), watcher_ids=[user.id], position=position,
        review_due_at=source.review_due_at, expires_at=None, revision=1,
    )
    session.add(duplicate)
    await session.flush()
    await sync_links(session, duplicate)
    await snapshot_document(session, duplicate, user.id, f"Copied from {source.title}")
    record_audit_event(
        session, entity_id=user.entity_id, actor_id=user.id, action="knowledge.document.duplicated",
        target_type="knowledge_document", target_id=duplicate.id, details={"source_id": source.id},
    )
    await session.commit()
    return await get_document(duplicate.id, session, user)


@router.get("/documents/{document_id}/revisions/{revision_id}")
async def get_document_revision(
    document_id: str, revision_id: str, session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict:
    await require_document(session, document_id, user)
    revision = await session.get(KnowledgeDocumentRevision, revision_id)
    if not revision or revision.document_id != document_id:
        raise HTTPException(status_code=404, detail="Revision not found")
    creator = await session.get(User, revision.created_by_id)
    return {
        "id": revision.id, "version": revision.version, "title": revision.title,
        "summary": revision.summary, "body": revision.body, "status": revision.status,
        "classification": revision.classification, "change_summary": revision.change_summary,
        "created_at": as_utc(revision.created_at).isoformat(),
        "created_by": user_summary(creator) if creator else None,
    }


@router.put("/documents/{document_id}/access")
async def update_document_access(
    document_id: str, payload: AccessUpdate, session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict:
    document, role = await require_document(session, document_id, user)
    if role not in {"admin", "owner"}:
        raise HTTPException(status_code=403, detail="Only the owner or an admin can manage document access")
    await authorize(session, user, action="share", resource_type="document", resource_id=document.id, classification=document.classification, source_type="document", preauthorized=True)
    users = await same_entity_users(session, user.entity_id, {item.user_id for item in payload.entries})
    await session.execute(delete(KnowledgeDocumentAccess).where(KnowledgeDocumentAccess.document_id == document.id))
    session.add_all([KnowledgeDocumentAccess(document_id=document.id, user_id=item.user_id, role=item.role)
                     for item in payload.entries if item.user_id in users and item.user_id != document.owner_id])
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="knowledge.document.access_updated",
                       target_type="knowledge_document", target_id=document.id, details={"member_count": len(payload.entries)})
    await session.commit()
    return await get_document(document.id, session, user)


@router.post("/documents/{document_id}/comments", status_code=status.HTTP_201_CREATED)
async def create_comment(
    document_id: str, payload: CommentCreate, session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict:
    document, role = await require_document(session, document_id, user)
    if role not in COMMENT_ROLES:
        raise HTTPException(status_code=403, detail="Comment access is required")
    await authorize(session, user, action="comment", resource_type="document", resource_id=document.id, classification=document.classification, source_type="document", preauthorized=True)
    await enforce_dlp(session, user, content=payload.body, source_type="document", action="comment", classification=document.classification)
    if payload.parent_id:
        parent = await session.get(KnowledgeComment, payload.parent_id)
        if not parent or parent.document_id != document.id:
            raise HTTPException(status_code=400, detail="Reply target is not part of this document")
    comment = KnowledgeComment(document_id=document.id, author_id=user.id, parent_id=payload.parent_id, body=payload.body)
    session.add(comment)
    handles = set(MENTION_PATTERN.findall(payload.body.lower()))
    members = (await session.scalars(select(User).where(User.entity_id == user.entity_id, User.id != user.id))).all()
    mentioned = [item for item in members if user_handle(item).lower() in handles]
    recipients = {item.id: item for item in mentioned}
    follower_ids = set(document.watcher_ids or []) - {user.id} - set(recipients)
    followers = [item for item in members if item.id in follower_ids]
    recipients.update({item.id: item for item in followers})
    mentioned_ids = {item.id for item in mentioned}
    notifications = [Notification(
        entity_id=user.entity_id, user_id=item.id, actor_id=user.id,
        kind="document_mention" if item.id in mentioned_ids else "document_comment",
        title=f"{user.display_name} mentioned you" if item.id in mentioned_ids else f"New comment on {document.title}",
        body=f"In {document.title}: {payload.body[:180]}", document_id=document.id,
    ) for item in recipients.values()]
    session.add_all(notifications)
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="knowledge.comment.created",
                       target_type="knowledge_document", target_id=document.id, details={"mentions": len(mentioned)})
    await session.commit()
    await session.refresh(comment)
    for notification, member in zip(notifications, recipients.values()):
        await session.refresh(notification)
        await communication_hub.publish(member.id, {"type": "notification", "notification": serialize_notification(notification, user)})
    return {"id": comment.id, "body": comment.body, "parent_id": comment.parent_id, "resolved": False,
            "created_at": as_utc(comment.created_at).isoformat(), "author": user_summary(user)}


@router.put("/documents/{document_id}/comments/{comment_id}/resolve")
async def resolve_comment(
    document_id: str, comment_id: str, session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict:
    document, role = await require_document(session, document_id, user)
    comment = await session.get(KnowledgeComment, comment_id)
    if not comment or comment.document_id != document.id:
        raise HTTPException(status_code=404, detail="Comment not found")
    if role not in EDIT_ROLES and comment.author_id != user.id:
        raise HTTPException(status_code=403, detail="Only the author or an editor can resolve this comment")
    comment.resolved = not comment.resolved
    comment.resolved_at = datetime.now(timezone.utc) if comment.resolved else None
    await session.commit()
    return {"id": comment.id, "resolved": comment.resolved,
            "resolved_at": as_utc(comment.resolved_at).isoformat() if comment.resolved_at else None}


@router.post("/documents/{document_id}/restore/{revision_id}")
async def restore_revision(
    document_id: str, revision_id: str, payload: RestoreRequest,
    session: AsyncSession = Depends(get_session), user: User = Depends(get_current_user),
) -> dict:
    document, role = await require_document(session, document_id, user)
    if role not in EDIT_ROLES:
        raise HTTPException(status_code=403, detail="Editor access is required")
    if document.revision != payload.expected_revision:
        raise HTTPException(status_code=409, detail={"message": "This document changed since you opened it", "current_revision": document.revision})
    revision = await session.get(KnowledgeDocumentRevision, revision_id)
    if not revision or revision.document_id != document.id:
        raise HTTPException(status_code=404, detail="Revision not found")
    document.title, document.summary, document.body = revision.title, revision.summary, revision.body
    document.status, document.classification = revision.status, revision.classification
    document.revision += 1
    document.updated_at = datetime.now(timezone.utc)
    await sync_links(session, document)
    await snapshot_document(session, document, user.id, f"Restored version {revision.version}")
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="knowledge.document.restored",
                       target_type="knowledge_document", target_id=document.id, details={"version": revision.version})
    await session.commit()
    return await get_document(document.id, session, user)
