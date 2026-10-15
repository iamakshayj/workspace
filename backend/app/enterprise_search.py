"""One permission-filtered search surface across the enterprise workspace."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import re
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import get_current_user
from .database import (
    AgileRelease,
    AgileSprint,
    CalendarEvent,
    KnowledgeDocument,
    Project,
    ProjectDecision,
    ProjectRisk,
    RecentSearch,
    SavedSearch,
    ServiceTicket,
    User,
    WorkItem,
    WorkspaceFile,
    get_session,
)
from .work_graph import build_access_scope, can_view_object, object_summary
from .policy_engine import PolicyContext, evaluate_policy, load_policy_snapshot


router = APIRouter(prefix="/search", tags=["enterprise search"])
SEARCH_TYPES = {"project", "work_item", "document", "meeting", "decision", "risk", "release", "sprint", "file", "service_ticket"}
TYPE_MODELS = {
    "project": Project,
    "work_item": WorkItem,
    "document": KnowledgeDocument,
    "meeting": CalendarEvent,
    "decision": ProjectDecision,
    "risk": ProjectRisk,
    "release": AgileRelease,
    "sprint": AgileSprint,
    "file": WorkspaceFile,
    "service_ticket": ServiceTicket,
}
TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]+")
SEMANTIC_GROUPS = (
    {"launch", "release", "deploy", "deployment", "rollout", "ship"},
    {"bug", "defect", "issue", "incident", "failure", "error"},
    {"meeting", "call", "sync", "standup", "workshop", "review"},
    {"document", "doc", "spec", "policy", "guide", "knowledge"},
    {"task", "story", "work", "ticket", "item", "deliverable"},
    {"risk", "threat", "exposure", "hazard", "concern"},
    {"decision", "choice", "resolution", "approval", "signoff"},
    {"customer", "client", "buyer", "account", "user"},
    {"security", "compliance", "audit", "control", "governance"},
    {"schedule", "timeline", "deadline", "milestone", "date"},
)
SYNONYMS = {token: group - {token} for group in SEMANTIC_GROUPS for token in group}


class SavedSearchWrite(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    query: str = Field(default="", max_length=500)
    mode: Literal["keyword", "semantic", "hybrid"] = "keyword"
    filters: dict[str, Any] = Field(default_factory=dict)
    shared: bool = False

    @field_validator("name", "query")
    @classmethod
    def trim_text(cls, value: str) -> str:
        return value.strip()


def tokens(text: str, *, semantic: bool = False) -> list[str]:
    result = TOKEN_PATTERN.findall((text or "").lower())
    if semantic:
        expanded = list(result)
        for token in result:
            expanded.extend(SYNONYMS.get(token, ()))
        return expanded
    return result


def semantic_score(query: str, text: str) -> float:
    """Local concept matching with synonym expansion and no external data transfer."""
    query_terms = set(tokens(query))
    if not query_terms:
        return 0.0
    document_terms = set(tokens(text))
    matched = 0.0
    for term in query_terms:
        if term in document_terms:
            matched += 1.0
        elif SYNONYMS.get(term, set()) & document_terms:
            matched += 0.82
    return matched / len(query_terms)


def text_fields(object_type: str, item: Any) -> tuple[str, str, str]:
    if object_type == "project":
        return item.title, item.description or "", f"{item.status} {(item.profile or {}).get('key', '')}"
    if object_type == "work_item":
        return item.summary, f"{item.description or ''} {item.acceptance_criteria or ''}", f"{item.key} {item.item_type} {item.status} {item.priority} {item.component} {item.team} {' '.join(item.labels or [])}"
    if object_type == "document":
        return item.title, f"{item.summary or ''} {item.body or ''}", f"{item.status} {item.classification} {item.template}"
    if object_type == "meeting":
        return item.title, f"{item.description or ''} {item.agenda or ''} {item.notes or ''} {item.transcript or ''}", f"{item.event_type} {item.status} {item.location}"
    if object_type == "decision":
        return item.title, f"{item.context or ''} {item.decision or ''} {' '.join(item.alternatives or [])} {item.consequences or ''}", item.status
    if object_type == "risk":
        return item.title, f"{item.description or ''} {item.mitigation or ''}", f"{item.status} probability {item.probability} impact {item.impact}"
    if object_type == "release":
        return item.name, item.description or "", f"{item.status} {item.scenario}"
    if object_type == "sprint":
        return item.name, item.goal or "", item.status
    if object_type == "file":
        return item.name, f"{item.description or ''} {item.content_text or ''}", f"{item.provider} {item.classification} {' '.join(item.tags or [])}"
    if object_type == "service_ticket":
        return item.title, item.description or "", f"{item.ticket_type} {item.status} {item.severity} {item.priority} {item.service} {' '.join(item.tags or [])}"
    return "", "", ""


def keyword_score(query: str, title: str, body: str, metadata: str) -> float:
    query_lower = query.lower().strip()
    if not query_lower:
        return 1.0
    query_tokens = tokens(query_lower)
    title_lower, body_lower, metadata_lower = title.lower(), body.lower(), metadata.lower()
    score = 0.0
    if query_lower == title_lower:
        score += 30
    elif query_lower in title_lower:
        score += 14
    if query_lower in metadata_lower:
        score += 7
    if query_lower in body_lower:
        score += 4
    for token in query_tokens:
        score += title_lower.count(token) * 5
        score += metadata_lower.count(token) * 2.5
        score += min(body_lower.count(token), 5)
    return score


def result_snippet(query: str, title: str, body: str) -> str:
    clean = " ".join((body or "").split())
    if not clean:
        return title
    query_tokens = tokens(query)
    lower = clean.lower()
    positions = [lower.find(token) for token in query_tokens if lower.find(token) >= 0]
    start = max(0, (min(positions) if positions else 0) - 70)
    end = min(len(clean), start + 260)
    prefix, suffix = ("…" if start else ""), ("…" if end < len(clean) else "")
    return f"{prefix}{clean[start:end]}{suffix}"


def comparable_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def permitted_documents(session: AsyncSession, user: User, object_types: set[str]) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    access_scope = await build_access_scope(session, user)
    policy_snapshot = await load_policy_snapshot(session, user)
    for object_type in object_types:
        model = TYPE_MODELS[object_type]
        query = select(model).where(model.entity_id == user.entity_id)
        if object_type == "work_item":
            query = query.where(WorkItem.archived.is_(False))
        if object_type == "document":
            query = query.where(KnowledgeDocument.status != "archived")
        rows = list(await session.scalars(query.order_by(getattr(model, "updated_at", getattr(model, "created_at")).desc()).limit(10_000)))
        for item in rows:
            if not await can_view_object(session, user, object_type, item, access_scope):
                continue
            project_id = item.id if object_type == "project" else getattr(item, "project_id", None)
            policy = await evaluate_policy(session, user, PolicyContext(
                action="search", resource_type=object_type, resource_id=item.id,
                project_id=project_id, classification=getattr(item, "classification", "internal") or "internal",
                source_type=object_type, preauthorized=True,
            ), snapshot=policy_snapshot)
            if not policy.allowed:
                continue
            title, body, metadata = text_fields(object_type, item)
            summary = object_summary(object_type, item)
            documents.append({
                **summary,
                "title": title,
                "body": body,
                "search_metadata": metadata,
                "owner_id": getattr(item, "owner_id", None) or getattr(item, "organizer_id", None) or getattr(item, "created_by_id", None),
            })
    return documents


def facet_values(documents: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    def entries(values: list[tuple[str, int]]) -> list[dict[str, Any]]:
        return [{"value": value, "count": count} for value, count in values]
    type_counts = Counter(item["type"] for item in documents)
    status_counts = Counter(item["status"] for item in documents if item.get("status"))
    project_counts = Counter(item["project_id"] for item in documents if item.get("project_id"))
    return {
        "types": entries(type_counts.most_common()),
        "statuses": entries(status_counts.most_common()),
        "projects": entries(project_counts.most_common()),
    }


def serialize_saved(item: SavedSearch, current_user_id: str) -> dict[str, Any]:
    return {
        "id": item.id, "name": item.name, "query": item.query, "mode": item.mode,
        "filters": item.filters or {}, "shared": item.shared, "owner_id": item.owner_id,
        "can_edit": item.owner_id == current_user_id,
        "updated_at": item.updated_at.isoformat(),
    }


async def remember_search(
    session: AsyncSession, user: User, query: str, mode: str, filters: dict[str, Any], result_count: int,
) -> None:
    if not query:
        return
    existing = await session.scalar(select(RecentSearch).where(
        RecentSearch.user_id == user.id, RecentSearch.query == query, RecentSearch.mode == mode,
    ).order_by(RecentSearch.searched_at.desc()).limit(1))
    if existing and (existing.filters or {}) == filters:
        existing.result_count = result_count
        existing.searched_at = datetime.now(timezone.utc)
    else:
        session.add(RecentSearch(entity_id=user.entity_id, user_id=user.id, query=query, mode=mode,
                                 filters=filters, result_count=result_count))
    await session.flush()
    keep_ids = list(await session.scalars(select(RecentSearch.id).where(
        RecentSearch.user_id == user.id,
    ).order_by(RecentSearch.searched_at.desc()).limit(20)))
    if keep_ids:
        await session.execute(delete(RecentSearch).where(RecentSearch.user_id == user.id, RecentSearch.id.not_in(keep_ids)))


@router.get("")
async def enterprise_search(
    q: str = Query(default="", max_length=500),
    mode: Literal["keyword", "semantic", "hybrid"] = "keyword",
    types: str = "",
    statuses: str = "",
    project_id: str | None = None,
    owner_id: str | None = None,
    updated_from: datetime | None = None,
    updated_to: datetime | None = None,
    offset: int = Query(default=0, ge=0, le=100_000),
    limit: int = Query(default=40, ge=1, le=100),
    remember: bool = True,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    query = q.strip()
    selected_types = {value.strip() for value in types.split(",") if value.strip()} or set(SEARCH_TYPES)
    if selected_types - SEARCH_TYPES:
        raise HTTPException(status_code=422, detail="Unsupported search object type")
    status_filter = {value.strip() for value in statuses.split(",") if value.strip()}
    filters = {"types": sorted(selected_types), "statuses": sorted(status_filter),
               "project_id": project_id, "owner_id": owner_id}
    documents = await permitted_documents(session, user, selected_types)
    ranked = []
    for document in documents:
        if status_filter and document.get("status") not in status_filter:
            continue
        if project_id and document.get("project_id") != project_id and not (
            document["type"] == "project" and document["id"] == project_id
        ):
            continue
        if owner_id and document.get("owner_id") != owner_id:
            continue
        updated_at = comparable_datetime(datetime.fromisoformat(document["updated_at"])) if document.get("updated_at") else None
        if updated_from and updated_at and updated_at < comparable_datetime(updated_from):
            continue
        if updated_to and updated_at and updated_at > comparable_datetime(updated_to):
            continue
        keyword = keyword_score(query, document["title"], document["body"], document["search_metadata"])
        semantic = semantic_score(query, f"{document['title']} {document['body']} {document['search_metadata']}") if query and mode in {"semantic", "hybrid"} else 0.0
        if query:
            if mode == "keyword" and keyword <= 0:
                continue
            if mode == "semantic" and semantic <= 0:
                continue
            if mode == "hybrid" and keyword <= 0 and semantic <= 0:
                continue
        score = keyword if mode == "keyword" else semantic * 100 if mode == "semantic" else keyword * 0.72 + max(semantic, 0) * 28
        ranked.append({
            **{key: value for key, value in document.items() if key not in {"body", "search_metadata"}},
            "score": round(score, 4),
            "snippet": result_snippet(query, document["title"], document["body"]),
            "matched_by": mode,
        })
    ranked.sort(key=lambda value: (value["score"], value.get("updated_at") or ""), reverse=True)
    facets = facet_values(ranked)
    total = len(ranked)
    if remember:
        await remember_search(session, user, query, mode, filters, total)
        await session.commit()
    return {"query": query, "mode": mode, "total": total, "offset": offset, "limit": limit,
            "results": ranked[offset:offset + limit], "facets": facets}


@router.get("/recent")
async def recent_searches(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    rows = list(await session.scalars(select(RecentSearch).where(
        RecentSearch.user_id == user.id,
    ).order_by(RecentSearch.searched_at.desc()).limit(20)))
    return [{"id": item.id, "query": item.query, "mode": item.mode, "filters": item.filters or {},
             "result_count": item.result_count, "searched_at": item.searched_at.isoformat()} for item in rows]


@router.delete("/recent", status_code=204, response_class=Response)
async def clear_recent_searches(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session),
) -> Response:
    await session.execute(delete(RecentSearch).where(RecentSearch.user_id == user.id))
    await session.commit()
    return Response(status_code=204)


@router.get("/saved")
async def saved_searches(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    rows = list(await session.scalars(select(SavedSearch).where(
        SavedSearch.entity_id == user.entity_id,
        or_(SavedSearch.owner_id == user.id, SavedSearch.shared.is_(True)),
    ).order_by(SavedSearch.updated_at.desc())))
    return [serialize_saved(item, user.id) for item in rows]


@router.post("/saved", status_code=status.HTTP_201_CREATED)
async def create_saved_search(
    payload: SavedSearchWrite, user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    duplicate = await session.scalar(select(SavedSearch.id).where(
        SavedSearch.owner_id == user.id, SavedSearch.name == payload.name,
    ))
    if duplicate:
        raise HTTPException(status_code=409, detail="You already have a saved search with this name")
    item = SavedSearch(entity_id=user.entity_id, owner_id=user.id, **payload.model_dump())
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return serialize_saved(item, user.id)


@router.put("/saved/{search_id}")
async def update_saved_search(
    search_id: str, payload: SavedSearchWrite, user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    item = await session.get(SavedSearch, search_id)
    if not item or item.entity_id != user.entity_id:
        raise HTTPException(status_code=404, detail="Saved search not found")
    if item.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Only the owner can update this saved search")
    for key, value in payload.model_dump().items():
        setattr(item, key, value)
    await session.commit()
    await session.refresh(item)
    return serialize_saved(item, user.id)


@router.delete("/saved/{search_id}", status_code=204, response_class=Response)
async def delete_saved_search(
    search_id: str, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session),
) -> Response:
    item = await session.get(SavedSearch, search_id)
    if not item or item.entity_id != user.entity_id:
        raise HTTPException(status_code=404, detail="Saved search not found")
    if item.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Only the owner can delete this saved search")
    await session.delete(item)
    await session.commit()
    return Response(status_code=204)
