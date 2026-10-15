import asyncio
import re
from datetime import date, datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import get_current_user
from .config import Settings, get_settings
from .database import (
    AgileRelease,
    AgileSprint,
    Entity,
    NodePlanningBinding,
    Notification,
    Project,
    ProjectCollaborator,
    SavedWorkspaceView,
    User,
    WorkItem,
    WorkItemActivity,
    WorkItemComment,
    WorkItemLink,
    get_session,
)
from .governance import can_edit_project, project_access_role, record_audit_event
from .identity import as_utc, user_handle, user_summary
from .job_service import notify_background_job, stage_webhook_event
from .policy_engine import authorize, enforce_dlp, is_held


router = APIRouter(prefix="/work", tags=["work management"])
PRIORITIES = {"lowest", "low", "medium", "high", "highest"}
SPRINT_STATUSES = {"planned", "active", "completed", "cancelled"}
RELEASE_STATUSES = {"planned", "in_progress", "released", "cancelled"}
LINK_TYPES = {
    "blocks", "depends_on", "relates_to", "duplicates", "supports", "contributes_to", "impacts"
}
HANDLE_PATTERN = re.compile(r"(?<![\w@])@([a-z0-9._-]+-[a-f0-9]{4})\b", re.IGNORECASE)
DEFAULT_WORK_COLUMNS = [
    {"id": "backlog", "label": "Backlog", "hint": "Ideas and unscheduled work", "color": "#8792A3", "category": "queue", "progress": 0, "wip_limit": None},
    {"id": "selected", "label": "Ready", "hint": "Committed and ready to start", "color": "#4B84D8", "category": "queue", "progress": 10, "wip_limit": None},
    {"id": "in_progress", "label": "In progress", "hint": "Work actively underway", "color": "#E09A34", "category": "active", "progress": 40, "wip_limit": 8},
    {"id": "ready_for_qa", "label": "Ready for QA", "hint": "Implementation ready to test", "color": "#B46BD7", "category": "qa", "progress": 65, "wip_limit": 6},
    {"id": "in_qa", "label": "In QA", "hint": "Testing and verification", "color": "#7A62D5", "category": "qa", "progress": 80, "wip_limit": 5},
    {"id": "review", "label": "Review / approval", "hint": "Final validation or sign-off", "color": "#536ED8", "category": "review", "progress": 90, "wip_limit": 5},
    {"id": "blocked", "label": "Blocked", "hint": "Waiting on a dependency", "color": "#D3586C", "category": "blocked", "progress": 40, "wip_limit": None},
    {"id": "done", "label": "Done", "hint": "Delivered and verified", "color": "#2A9A70", "category": "done", "progress": 100, "wip_limit": None},
]
DEFAULT_WORK_ITEM_TYPES = [
    {"id": "initiative", "label": "Initiative", "icon": "◆", "parent_types": [], "child_type": "epic"},
    {"id": "epic", "label": "Epic", "icon": "⚡", "parent_types": ["initiative"], "child_type": "story"},
    {"id": "feature", "label": "Feature", "icon": "◈", "parent_types": ["initiative", "epic"], "child_type": "story"},
    {"id": "story", "label": "Story", "icon": "▤", "parent_types": ["epic", "feature"], "child_type": "subtask"},
    {"id": "subtask", "label": "Subtask", "icon": "↳", "parent_types": ["story", "task"], "child_type": None},
    {"id": "task", "label": "Task", "icon": "✓", "parent_types": ["epic", "story"], "child_type": "subtask"},
    {"id": "bug", "label": "Defect", "icon": "◆", "parent_types": ["epic", "story"], "child_type": None},
    {"id": "spike", "label": "Spike", "icon": "⌁", "parent_types": ["epic", "story"], "child_type": None},
    {"id": "improvement", "label": "Improvement", "icon": "↑", "parent_types": ["epic", "story"], "child_type": "subtask"},
    {"id": "technical_debt", "label": "Technical debt", "icon": "⚙", "parent_types": ["epic", "story"], "child_type": "subtask"},
    {"id": "milestone", "label": "Milestone", "icon": "◇", "parent_types": [], "child_type": None},
    {"id": "request", "label": "Request", "icon": "→", "parent_types": [], "child_type": None},
    {"id": "deliverable", "label": "Deliverable", "icon": "□", "parent_types": [], "child_type": None},
    {"id": "approval", "label": "Approval", "icon": "◎", "parent_types": [], "child_type": None},
]


async def enforce_work_policy(
    session: AsyncSession,
    user: User,
    *,
    action: str,
    item: WorkItem | None = None,
    project_id: str | None = None,
    fields: set[str] | None = None,
    content: str = "",
) -> None:
    linked_project_id = project_id or (item.project_id if item else None)
    classification = "internal"
    if linked_project_id:
        project = await session.get(Project, linked_project_id)
        if project and project.entity_id == user.entity_id:
            classification = str((project.profile or {}).get("classification") or "internal")
    await authorize(
        session, user, action=action, resource_type="work_item",
        resource_id=item.id if item else None, project_id=linked_project_id,
        fields=fields or (), classification=classification, source_type="work",
        preauthorized=True,
    )
    if content:
        await enforce_dlp(
            session, user, content=content, source_type="work", action=action,
            classification=classification,
        )


class ChecklistEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=36, pattern=r"^[a-zA-Z0-9_-]+$")
    title: str = Field(min_length=1, max_length=240)
    done: bool = False


class WorkItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=180)
    item_type: str = Field(default="task", min_length=1, max_length=40, pattern=r"^[a-z][a-z0-9_]*$")
    description: str = Field(default="", max_length=20_000)
    acceptance_criteria: str = Field(default="", max_length=20_000)
    status: str = Field(default="backlog", min_length=1, max_length=40, pattern=r"^[a-z][a-z0-9_]*$")
    priority: Literal["lowest", "low", "medium", "high", "highest"] = "medium"
    assignee_id: str | None = None
    owner_id: str | None = None
    sprint_id: str | None = None
    release_id: str | None = None
    project_id: str | None = None
    parent_id: str | None = None
    node_id: str | None = Field(default=None, max_length=80)
    story_points: int | None = Field(default=None, ge=0, le=1_000)
    estimate_minutes: int | None = Field(default=None, ge=0, le=5_256_000)
    actual_minutes: int | None = Field(default=None, ge=0, le=5_256_000)
    severity: Literal["none", "minor", "major", "critical", "blocker"] = "none"
    component: str = Field(default="", max_length=120)
    team: str = Field(default="", max_length=120)
    labels: list[str] = Field(default_factory=list, max_length=20)
    checklist: list[ChecklistEntry] = Field(default_factory=list, max_length=100)
    watcher_ids: list[str] = Field(default_factory=list, max_length=100)
    custom_fields: dict[str, Any] = Field(default_factory=dict)
    archived: bool = False
    start_date: date | None = None
    due_date: date | None = None

    @model_validator(mode="after")
    def dates_are_ordered(self) -> "WorkItemCreate":
        if self.start_date and self.due_date and self.start_date > self.due_date:
            raise ValueError("Start date must be on or before due date")
        self.summary = self.summary.strip()
        self.component = self.component.strip()
        self.team = self.team.strip()
        self.labels = list(dict.fromkeys(label.strip()[:40] for label in self.labels if label.strip()))
        self.watcher_ids = list(dict.fromkeys(self.watcher_ids))
        return self


class WorkItemUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)
    summary: str | None = Field(default=None, min_length=1, max_length=180)
    item_type: str | None = Field(default=None, min_length=1, max_length=40, pattern=r"^[a-z][a-z0-9_]*$")
    description: str | None = Field(default=None, max_length=20_000)
    acceptance_criteria: str | None = Field(default=None, max_length=20_000)
    status: str | None = Field(default=None, min_length=1, max_length=40, pattern=r"^[a-z][a-z0-9_]*$")
    priority: Literal["lowest", "low", "medium", "high", "highest"] | None = None
    assignee_id: str | None = None
    owner_id: str | None = None
    sprint_id: str | None = None
    release_id: str | None = None
    project_id: str | None = None
    parent_id: str | None = None
    node_id: str | None = Field(default=None, max_length=80)
    story_points: int | None = Field(default=None, ge=0, le=1_000)
    estimate_minutes: int | None = Field(default=None, ge=0, le=5_256_000)
    actual_minutes: int | None = Field(default=None, ge=0, le=5_256_000)
    severity: Literal["none", "minor", "major", "critical", "blocker"] | None = None
    component: str | None = Field(default=None, max_length=120)
    team: str | None = Field(default=None, max_length=120)
    labels: list[str] | None = Field(default=None, max_length=20)
    checklist: list[ChecklistEntry] | None = Field(default=None, max_length=100)
    watcher_ids: list[str] | None = Field(default=None, max_length=100)
    custom_fields: dict[str, Any] | None = None
    archived: bool | None = None
    start_date: date | None = None
    due_date: date | None = None
    rank: float | None = Field(default=None, ge=0)


class CommentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str = Field(min_length=1, max_length=10_000)
    parent_id: str | None = None
    attachments: list[dict[str, str]] = Field(default_factory=list, max_length=20)


class CommentReaction(BaseModel):
    emoji: str = Field(min_length=1, max_length=16)


class WorkItemSplit(BaseModel):
    parts: list[str] = Field(min_length=2, max_length=50)

    @model_validator(mode="after")
    def normalize_parts(self) -> "WorkItemSplit":
        self.parts = [part.strip()[:180] for part in self.parts if part.strip()]
        if len(self.parts) < 2:
            raise ValueError("Provide at least two named parts")
        return self


class WorkItemMerge(BaseModel):
    source_ids: list[str] = Field(min_length=1, max_length=50)


class WorkLinkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_id: str
    link_type: Literal[
        "blocks", "depends_on", "relates_to", "duplicates", "supports", "contributes_to", "impacts"
    ] = "relates_to"


class WorkItemBulkUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_ids: list[str] = Field(min_length=1, max_length=100)
    assignee_id: str | None = None
    owner_id: str | None = None
    status: str | None = Field(default=None, min_length=1, max_length=40, pattern=r"^[a-z][a-z0-9_]*$")
    priority: Literal["lowest", "low", "medium", "high", "highest"] | None = None
    severity: Literal["none", "minor", "major", "critical", "blocker"] | None = None
    item_type: str | None = Field(default=None, min_length=1, max_length=40, pattern=r"^[a-z][a-z0-9_]*$")
    project_id: str | None = None
    sprint_id: str | None = None
    release_id: str | None = None
    story_points: int | None = Field(default=None, ge=0, le=1_000)
    component: str | None = Field(default=None, max_length=120)
    team: str | None = Field(default=None, max_length=120)
    add_labels: list[str] = Field(default_factory=list, max_length=20)
    start_date: date | None = None
    due_date: date | None = None
    archived: bool | None = None


class SprintCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    goal: str = Field(default="", max_length=5_000)
    start_date: date | None = None
    end_date: date | None = None
    capacity_points: int | None = Field(default=None, ge=0, le=1_000_000)

    @model_validator(mode="after")
    def dates_are_ordered(self) -> "SprintCreate":
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("Sprint start date must be on or before its end date")
        self.name = self.name.strip()
        return self


class SprintUpdate(SprintCreate):
    expected_revision: int = Field(ge=0)
    status: Literal["planned", "active", "completed", "cancelled"] = "planned"


class ReleaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=5_000)
    start_date: date | None = None
    target_date: date | None = None
    scenario: Literal["committed", "optimistic", "conservative"] = "committed"
    baseline: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def dates_are_ordered(self) -> "ReleaseCreate":
        if self.start_date and self.target_date and self.start_date > self.target_date:
            raise ValueError("Release start date must be on or before its target date")
        self.name = self.name.strip()
        return self


class ReleaseUpdate(ReleaseCreate):
    expected_revision: int = Field(ge=0)
    status: Literal["planned", "in_progress", "released", "cancelled"] = "planned"
    scenario: Literal["committed", "optimistic", "conservative"] | None = None
    baseline: dict[str, Any] | None = None


class NodePlanUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int | None = Field(default=None, ge=0)
    primary_work_item_id: str | None = None
    sprint_id: str | None = None
    subflow_project_id: str | None = None


class NodeWorkItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(min_length=1, max_length=180)
    item_type: str = Field(default="story", min_length=1, max_length=40, pattern=r"^[a-z][a-z0-9_]*$")
    description: str = Field(default="", max_length=20_000)
    acceptance_criteria: str = Field(default="", max_length=20_000)
    priority: Literal["lowest", "low", "medium", "high", "highest"] = "medium"
    assignee_id: str | None = None
    parent_id: str | None = None
    story_points: int | None = Field(default=None, ge=0, le=1_000)
    due_date: date | None = None
    set_primary: bool = True


class WorkflowColumn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=40, pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1, max_length=60)
    hint: str = Field(default="", max_length=160)
    color: str = Field(default="#8792A3", pattern=r"^#[0-9A-Fa-f]{6}$")
    category: Literal["queue", "active", "qa", "review", "blocked", "done"] = "active"
    progress: int = Field(default=0, ge=0, le=100)
    wip_limit: int | None = Field(default=None, ge=1, le=10_000)


class WorkflowItemType(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=40, pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1, max_length=60)
    icon: str = Field(default="✓", min_length=1, max_length=8)
    parent_types: list[str] = Field(default_factory=list, max_length=10)
    child_type: str | None = Field(default=None, max_length=40)


class WorkWorkflowUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    columns: list[WorkflowColumn] = Field(min_length=2, max_length=12)
    item_types: list[WorkflowItemType] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def workflow_is_coherent(self) -> "WorkWorkflowUpdate":
        column_ids = [column.id for column in self.columns]
        type_ids = [item_type.id for item_type in self.item_types]
        if len(column_ids) != len(set(column_ids)):
            raise ValueError("Workflow column IDs must be unique")
        if len(type_ids) != len(set(type_ids)):
            raise ValueError("Work type IDs must be unique")
        if not any(column.category == "done" for column in self.columns):
            raise ValueError("A workflow needs at least one completed column")
        known_types = set(type_ids)
        for column in self.columns:
            column.label = column.label.strip()
            column.hint = column.hint.strip()
            if not column.label:
                raise ValueError("Workflow stage labels cannot be blank")
        for item_type in self.item_types:
            item_type.label = item_type.label.strip()
            item_type.icon = item_type.icon.strip()
            item_type.parent_types = list(dict.fromkeys(item_type.parent_types))
            if not item_type.label or not item_type.icon:
                raise ValueError("Work type labels and icons cannot be blank")
            if any(parent not in known_types for parent in item_type.parent_types):
                raise ValueError(f"{item_type.label} references an unknown parent type")
            if item_type.child_type and item_type.child_type not in known_types:
                raise ValueError(f"{item_type.label} references an unknown child type")
            if item_type.id in item_type.parent_types or item_type.child_type == item_type.id:
                raise ValueError(f"{item_type.label} cannot reference itself")
        return self


def require_admin(user: User) -> None:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator privileges are required")


def work_workflow(entity: Entity) -> dict[str, list[dict[str, Any]]]:
    columns = entity.work_columns if isinstance(entity.work_columns, list) else DEFAULT_WORK_COLUMNS
    item_types = entity.work_item_types if isinstance(entity.work_item_types, list) else DEFAULT_WORK_ITEM_TYPES
    return {
        "columns": [dict(column) for column in columns],
        "item_types": [dict(item_type) for item_type in item_types],
    }


def workflow_statuses(workflow: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    return {column["id"]: column for column in workflow["columns"]}


def work_progress(item: WorkItem, workflow: dict[str, list[dict[str, Any]]]) -> int:
    return int(workflow_statuses(workflow).get(item.status, {}).get("progress", 0))


def weighted_progress(items: list[WorkItem], workflow: dict[str, list[dict[str, Any]]]) -> int:
    if not items:
        return 0
    weights = [item.story_points if item.story_points and item.story_points > 0 else 1 for item in items]
    return round(sum(work_progress(item, workflow) * weight for item, weight in zip(items, weights)) / sum(weights))


async def validate_work_configuration(
    session: AsyncSession,
    user: User,
    data: dict[str, Any],
    *,
    current_status: str | None = None,
    current_item_type: str | None = None,
) -> None:
    entity = await session.get(Entity, user.entity_id)
    workflow = work_workflow(entity)
    status_id = data.get("status", current_status or "backlog")
    item_type_id = data.get("item_type", current_item_type or "task")
    if status_id not in {column["id"] for column in workflow["columns"]}:
        raise HTTPException(status_code=400, detail="Status is not part of this workspace workflow")
    if item_type_id not in {item_type["id"] for item_type in workflow["item_types"]}:
        raise HTTPException(status_code=400, detail="Work type is not enabled for this workspace")


def iso(value: datetime | None) -> str | None:
    return as_utc(value).isoformat() if value else None


def date_iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def work_prefix(entity_name: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", entity_name.upper())
    prefix = "".join(word[0] for word in words[:4])
    if len(prefix) < 2 and words:
        prefix = words[0][:4]
    return (prefix or "WORK")[:6]


def serialize_item(item: WorkItem, users: dict[str, User]) -> dict[str, Any]:
    return {
        "id": item.id, "key": item.key, "sequence_number": item.sequence_number,
        "summary": item.summary, "item_type": item.item_type, "description": item.description,
        "acceptance_criteria": item.acceptance_criteria, "status": item.status,
        "priority": item.priority, "story_points": item.story_points,
        "severity": item.severity or "none", "estimate_minutes": item.estimate_minutes,
        "actual_minutes": item.actual_minutes, "component": item.component or "",
        "team": item.team or "", "labels": item.labels or [],
        "checklist": item.checklist or [], "watcher_ids": item.watcher_ids or [],
        "custom_fields": item.custom_fields or {},
        "watchers": [user_summary(users[user_id]) for user_id in (item.watcher_ids or []) if user_id in users],
        "archived": bool(item.archived),
        "assignee": user_summary(users[item.assignee_id]) if item.assignee_id in users else None,
        "owner": user_summary(users[item.owner_id]) if item.owner_id in users else None,
        "reporter": user_summary(users[item.reporter_id]), "sprint_id": item.sprint_id,
        "release_id": item.release_id, "project_id": item.project_id,
        "parent_id": item.parent_id, "node_id": item.node_id,
        "start_date": date_iso(item.start_date), "due_date": date_iso(item.due_date),
        "rank": item.rank, "revision": item.revision,
        "created_at": iso(item.created_at), "updated_at": iso(item.updated_at),
    }


def serialize_sprint(sprint: AgileSprint) -> dict[str, Any]:
    return {
        "id": sprint.id, "name": sprint.name, "goal": sprint.goal, "status": sprint.status,
        "start_date": date_iso(sprint.start_date), "end_date": date_iso(sprint.end_date),
        "capacity_points": sprint.capacity_points, "revision": sprint.revision,
        "created_at": iso(sprint.created_at), "updated_at": iso(sprint.updated_at),
    }


def serialize_release(release: AgileRelease) -> dict[str, Any]:
    return {
        "id": release.id, "name": release.name, "description": release.description,
        "status": release.status, "start_date": date_iso(release.start_date),
        "target_date": date_iso(release.target_date), "released_at": iso(release.released_at),
        "scenario": release.scenario, "baseline": release.baseline or {},
        "revision": release.revision, "created_at": iso(release.created_at),
        "updated_at": iso(release.updated_at),
    }


async def tenant_reference(session: AsyncSession, model: Any, value: str | None, user: User, label: str) -> Any | None:
    if not value:
        return None
    record = await session.get(model, value)
    if not record or record.entity_id != user.entity_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{label} is not in your workspace")
    return record


async def validate_item_references(
    session: AsyncSession, data: dict[str, Any], user: User,
    item_id: str | None = None, current_project_id: str | None = None,
    current_node_id: str | None = None, current_parent_id: str | None = None,
    current_item_type: str | None = None,
) -> None:
    parent: WorkItem | None = None
    for field, model, label in (
        ("assignee_id", User, "Assignee"), ("owner_id", User, "Owner"),
        ("sprint_id", AgileSprint, "Sprint"),
        ("release_id", AgileRelease, "Release"), ("project_id", Project, "Flowchart"),
        ("parent_id", WorkItem, "Parent work item"),
    ):
        if field not in data or data[field] is None:
            continue
        record = await session.get(model, data[field])
        if not record or record.entity_id != user.entity_id:
            raise HTTPException(status_code=400, detail=f"{label} is not in your workspace")
        if field == "parent_id" and data[field] == item_id:
            raise HTTPException(status_code=400, detail="A work item cannot be its own parent")
        if field == "parent_id":
            parent = record

    effective_item_type = data.get("item_type", current_item_type or "task")
    if "watcher_ids" in data and data["watcher_ids"] is not None:
        watcher_ids = list(dict.fromkeys(data["watcher_ids"]))
        watcher_count = await session.scalar(select(func.count(User.id)).where(
            User.id.in_(watcher_ids), User.entity_id == user.entity_id,
        )) if watcher_ids else 0
        if watcher_count != len(watcher_ids):
            raise HTTPException(status_code=400, detail="Every follower must belong to this workspace")
    effective_parent_id = data.get("parent_id", current_parent_id)
    if effective_parent_id and parent is None:
        parent = await tenant_reference(session, WorkItem, effective_parent_id, user, "Parent work item")
    entity = await session.get(Entity, user.entity_id)
    workflow = work_workflow(entity)
    allowed_parent_types = {
        item_type["id"]: set(item_type.get("parent_types") or [])
        for item_type in workflow["item_types"]
    }
    if effective_item_type == "subtask" and not parent:
        raise HTTPException(status_code=400, detail="A subtask must belong to a story or task")
    if parent and parent.item_type not in allowed_parent_types.get(effective_item_type, set()):
        allowed = " or ".join(sorted(allowed_parent_types.get(effective_item_type, set()))) or "no parent"
        raise HTTPException(
            status_code=400,
            detail=f"A {effective_item_type} can only belong to {allowed}",
        )
    if parent and item_id:
        cursor = parent
        visited: set[str] = set()
        while cursor and cursor.id not in visited:
            if cursor.id == item_id:
                raise HTTPException(status_code=400, detail="A work item hierarchy cannot contain a cycle")
            visited.add(cursor.id)
            cursor = await session.get(WorkItem, cursor.parent_id) if cursor.parent_id else None
    effective_project_id = data.get("project_id", current_project_id)
    effective_node_id = data.get("node_id", current_node_id)
    if effective_node_id and not effective_project_id:
        raise HTTPException(status_code=400, detail="A flowchart node requires a flowchart link")


async def enforce_item_field_permissions(
    session: AsyncSession, user: User, item: WorkItem, changed_fields: set[str],
) -> None:
    if user.role == "admin" or not item.project_id:
        return
    project = await session.get(Project, item.project_id)
    rules = ((project.settings or {}).get("permissions", {}).get("field_rules", {}) if project else {})
    actor_roles = {"member"}
    if item.reporter_id == user.id: actor_roles.add("reporter")
    if item.assignee_id == user.id: actor_roles.add("assignee")
    if item.owner_id == user.id: actor_roles.add("owner")
    for field in changed_fields:
        allowed = set(rules.get(field, []))
        if allowed and not actor_roles.intersection(allowed):
            raise HTTPException(status_code=403, detail=f"You do not have permission to update {field.replace('_', ' ')}")


def add_activity(session: AsyncSession, item: WorkItem, user: User, action: str, changes: dict[str, Any]) -> None:
    session.add(WorkItemActivity(
        entity_id=user.entity_id, work_item_id=item.id, actor_id=user.id,
        action=action, changes={key: json_value(value) for key, value in changes.items()},
    ))
    record_audit_event(
        session, entity_id=user.entity_id, actor_id=user.id, action=f"work_item.{action}",
        project_id=item.project_id, target_type="work_item", target_id=item.id,
        details={"key": item.key, **{key: json_value(value) for key, value in changes.items()}},
    )


def assignment_notification(session: AsyncSession, item: WorkItem, user: User) -> None:
    if not item.assignee_id or item.assignee_id == user.id:
        return
    session.add(Notification(
        entity_id=user.entity_id, user_id=item.assignee_id, actor_id=user.id,
        kind="work_item_assigned", title=f"{item.key} assigned to you",
        body=item.summary, project_id=item.project_id, work_item_id=item.id,
    ))


def follower_notifications(session: AsyncSession, item: WorkItem, user: User, title: str) -> None:
    recipients = set(item.watcher_ids or []) - {user.id, item.assignee_id}
    for recipient_id in recipients:
        session.add(Notification(
            entity_id=user.entity_id, user_id=recipient_id, actor_id=user.id,
            kind="work_item_updated", title=title, body=item.summary,
            project_id=item.project_id, work_item_id=item.id,
        ))


async def planning_project(
    project_id: str,
    user: User,
    session: AsyncSession,
    *,
    edit: bool = False,
) -> Project:
    project = await session.get(Project, project_id)
    access = await project_access_role(session, project, user) if project else None
    if not project or project.entity_id != user.entity_id or not access:
        raise HTTPException(status_code=404, detail="Flowchart not found")
    if edit and not can_edit_project(access):
        raise HTTPException(status_code=403, detail="Editor access is required to plan flowchart nodes")
    return project


def require_node(project: Project, node_id: str) -> dict[str, Any]:
    node = next((candidate for candidate in (project.graph or {}).get("nodes", []) if candidate.get("id") == node_id), None)
    if not node:
        raise HTTPException(status_code=404, detail="Flowchart node not found")
    return node


async def project_planning_payload(
    project: Project,
    user: User,
    session: AsyncSession,
) -> dict[str, Any]:
    entity = await session.get(Entity, user.entity_id)
    workflow = work_workflow(entity)
    statuses = workflow_statuses(workflow)
    done_statuses = {status_id for status_id, column in statuses.items() if column.get("category") == "done"}
    members = (await session.scalars(
        select(User).where(User.entity_id == user.entity_id).order_by(User.display_name)
    )).all()
    users = {member.id: member for member in members}
    all_items = (await session.scalars(
        select(WorkItem).where(WorkItem.entity_id == user.entity_id)
        .order_by(WorkItem.rank, WorkItem.created_at).limit(2_000)
    )).all()
    items_by_id = {item.id: item for item in all_items}
    sprints = (await session.scalars(
        select(AgileSprint).where(AgileSprint.entity_id == user.entity_id)
        .order_by(AgileSprint.created_at.desc()).limit(200)
    )).all()
    sprints_by_id = {sprint.id: sprint for sprint in sprints}
    bindings = (await session.scalars(
        select(NodePlanningBinding).where(NodePlanningBinding.project_id == project.id)
    )).all()
    bindings_by_node = {binding.node_id: binding for binding in bindings}
    entity_projects = (await session.scalars(
        select(Project).where(Project.entity_id == user.entity_id).order_by(Project.title).limit(1_000)
    )).all()
    accessible_projects = []
    for candidate in entity_projects:
        if await project_access_role(session, candidate, user):
            accessible_projects.append(candidate)
    projects_by_id = {candidate.id: candidate for candidate in accessible_projects}

    sprint_payloads: dict[str, dict[str, Any]] = {}
    for sprint in sprints:
        sprint_items = [item for item in all_items if item.sprint_id == sprint.id]
        sprint_points = sum(item.story_points or 0 for item in sprint_items)
        done_points = sum(item.story_points or 0 for item in sprint_items if item.status in done_statuses)
        sprint_payloads[sprint.id] = {
            **serialize_sprint(sprint),
            "item_count": len(sprint_items),
            "done_count": sum(item.status in done_statuses for item in sprint_items),
            "committed_points": sprint_points,
            "done_points": done_points,
            "progress": weighted_progress(sprint_items, workflow),
        }

    node_plans: dict[str, dict[str, Any]] = {}
    for node in (project.graph or {}).get("nodes", []):
        node_id = node.get("id")
        binding = bindings_by_node.get(node_id)
        directly_linked = [
            item for item in all_items if item.project_id == project.id and item.node_id == node_id
        ]
        primary = items_by_id.get(binding.primary_work_item_id) if binding and binding.primary_work_item_id else None
        if not binding and not primary and directly_linked:
            primary = next((item for item in directly_linked if item.item_type == "epic"), directly_linked[0])
        related_ids = {item.id for item in directly_linked}
        if primary:
            related_ids.add(primary.id)
            changed = True
            while changed:
                changed = False
                for item in all_items:
                    if (item.parent_id in related_ids and item.id not in related_ids
                            and item.project_id == project.id and item.node_id == node_id):
                        related_ids.add(item.id)
                        changed = True
        related = [item for item in all_items if item.id in related_ids]
        delivery_items = [item for item in related if item.id != primary.id] if primary and primary.item_type == "epic" else related
        if not delivery_items and primary:
            delivery_items = [primary]
        done_count = sum(item.status in done_statuses for item in delivery_items)
        total_points = sum(item.story_points or 0 for item in delivery_items)
        done_points = sum(item.story_points or 0 for item in delivery_items if item.status in done_statuses)
        sprint = sprints_by_id.get(binding.sprint_id) if binding and binding.sprint_id else None
        subflow = projects_by_id.get(binding.subflow_project_id) if binding and binding.subflow_project_id else None
        if not delivery_items and sprint:
            sprint_summary = sprint_payloads[sprint.id]
            done_count = sprint_summary["done_count"]
            total_points = sprint_summary["committed_points"]
            done_points = sprint_summary["done_points"]
            item_count = sprint_summary["item_count"]
            progress = sprint_summary["progress"]
        else:
            item_count = len(delivery_items)
            progress = weighted_progress(delivery_items, workflow)
        node_plans[node_id] = {
            "node_id": node_id,
            "node_label": node.get("label", "Untitled step"),
            "binding_id": binding.id if binding else None,
            "revision": binding.revision if binding else 0,
            "primary_item": serialize_item(primary, users) if primary else None,
            "items": [serialize_item(item, users) for item in related],
            "sprint": sprint_payloads.get(sprint.id) if sprint else None,
            "subflow": {"id": subflow.id, "title": subflow.title, "status": subflow.status} if subflow else None,
            "progress": progress,
            "done_count": done_count,
            "item_count": item_count,
            "total_points": total_points,
            "done_points": done_points,
            "planning_kind": primary.item_type if primary else "sprint" if sprint else "subflow" if subflow else None,
        }
    return {
        "project": {"id": project.id, "title": project.title},
        "nodes": node_plans,
        "items": [serialize_item(item, users) for item in all_items],
        "sprints": list(sprint_payloads.values()),
        "projects": [{"id": candidate.id, "title": candidate.title, "status": candidate.status}
                     for candidate in accessible_projects if candidate.id != project.id],
        "members": [user_summary(member) for member in members],
        "workflow": workflow,
    }


@router.get("/projects/{project_id}/planning")
async def get_project_planning(
    project_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    project = await planning_project(project_id, user, session)
    return await project_planning_payload(project, user, session)


@router.put("/projects/{project_id}/nodes/{node_id}/planning")
async def update_node_planning(
    project_id: str,
    node_id: str,
    payload: NodePlanUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    project = await planning_project(project_id, user, session, edit=True)
    require_node(project, node_id)
    binding = await session.scalar(select(NodePlanningBinding).where(
        NodePlanningBinding.project_id == project.id,
        NodePlanningBinding.node_id == node_id,
    ))
    if binding and payload.expected_revision is not None and binding.revision != payload.expected_revision:
        raise HTTPException(status_code=409, detail="This node plan changed. Refresh it before saving again")
    if not binding:
        binding = NodePlanningBinding(
            entity_id=user.entity_id, project_id=project.id, node_id=node_id,
            created_by_id=user.id,
        )
        session.add(binding)
        await session.flush()

    changes: dict[str, Any] = {}
    submitted = payload.model_dump(exclude_unset=True)
    submitted.pop("expected_revision", None)
    if "primary_work_item_id" in submitted and submitted["primary_work_item_id"]:
        item = await tenant_reference(session, WorkItem, submitted["primary_work_item_id"], user, "Work item")
        old_context = {"project_id": item.project_id, "node_id": item.node_id}
        item.project_id = project.id
        item.node_id = node_id
        item.revision += 1
        item.updated_at = datetime.now(timezone.utc)
        add_activity(session, item, user, "linked_to_node", {
            "from": old_context, "project_id": project.id, "node_id": node_id,
        })
    if "sprint_id" in submitted and submitted["sprint_id"]:
        await tenant_reference(session, AgileSprint, submitted["sprint_id"], user, "Sprint")
    if "subflow_project_id" in submitted and submitted["subflow_project_id"]:
        subflow = await tenant_reference(session, Project, submitted["subflow_project_id"], user, "Sub-flowchart")
        if subflow.id == project.id:
            raise HTTPException(status_code=400, detail="A flowchart cannot be its own sub-flowchart")
        if not await project_access_role(session, subflow, user):
            raise HTTPException(status_code=400, detail="You do not have access to that sub-flowchart")
    for field, value in submitted.items():
        previous = getattr(binding, field)
        if previous != value:
            setattr(binding, field, value)
            changes[field] = {"from": previous, "to": value}
    if changes:
        binding.revision += 1
        binding.updated_at = datetime.now(timezone.utc)
        record_audit_event(
            session, entity_id=user.entity_id, actor_id=user.id,
            action="node_planning.updated", project_id=project.id,
            target_type="flowchart_node", target_id=node_id, details=changes,
        )
    await session.commit()
    return await project_planning_payload(project, user, session)


@router.post("/projects/{project_id}/nodes/{node_id}/work-items", status_code=status.HTTP_201_CREATED)
async def create_node_work_item(
    project_id: str,
    node_id: str,
    payload: NodeWorkItemCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    project = await planning_project(project_id, user, session, edit=True)
    require_node(project, node_id)
    data = payload.model_dump()
    set_primary = data.pop("set_primary")
    entity = await session.scalar(select(Entity).where(Entity.id == user.entity_id).with_for_update())
    workflow = work_workflow(entity)
    initial_status = workflow["columns"][0]["id"]
    await validate_work_configuration(session, user, {**data, "status": initial_status})
    await validate_item_references(
        session, {**data, "project_id": project.id, "node_id": node_id}, user,
    )
    if data.get("parent_id"):
        parent = await tenant_reference(session, WorkItem, data["parent_id"], user, "Parent work item")
        if parent.project_id != project.id or parent.node_id != node_id:
            raise HTTPException(status_code=400, detail="Parent work item must belong to this flowchart node")
    binding = await session.scalar(select(NodePlanningBinding).where(
        NodePlanningBinding.project_id == project.id,
        NodePlanningBinding.node_id == node_id,
    ))
    sequence = (await session.scalar(
        select(func.max(WorkItem.sequence_number)).where(WorkItem.entity_id == user.entity_id)
    ) or 0) + 1
    rank = (await session.scalar(
        select(func.max(WorkItem.rank)).where(WorkItem.entity_id == user.entity_id)
    ) or 0) + 1024
    item = WorkItem(
        entity_id=user.entity_id, sequence_number=sequence,
        key=f"{work_prefix(entity.name)}-{sequence}", reporter_id=user.id,
        project_id=project.id, node_id=node_id, rank=rank, status=initial_status,
        start_date=None, sprint_id=binding.sprint_id if binding else None, release_id=None, estimate_minutes=None,
        labels=[], **data,
    )
    session.add(item)
    await session.flush()
    add_activity(session, item, user, "created_from_node", {"project_id": project.id, "node_id": node_id})
    assignment_notification(session, item, user)
    if not binding:
        binding = NodePlanningBinding(
            entity_id=user.entity_id, project_id=project.id, node_id=node_id,
            created_by_id=user.id,
        )
        session.add(binding)
        await session.flush()
    if set_primary or not binding.primary_work_item_id:
        binding.primary_work_item_id = item.id
        binding.revision += 1
        binding.updated_at = datetime.now(timezone.utc)
    record_audit_event(
        session, entity_id=user.entity_id, actor_id=user.id,
        action="node_planning.work_item_created", project_id=project.id,
        target_type="flowchart_node", target_id=node_id,
        details={"work_item_id": item.id, "key": item.key, "item_type": item.item_type},
    )
    await session.commit()
    return await project_planning_payload(project, user, session)


@router.get("/overview")
async def work_overview(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    entity = await session.get(Entity, user.entity_id)
    member_rows = (await session.scalars(select(User).where(User.entity_id == user.entity_id).order_by(User.display_name))).all()
    users = {member.id: member for member in member_rows}
    guest_projects = select(ProjectCollaborator.project_id).where(ProjectCollaborator.user_id == user.id)
    item_scope = WorkItem.entity_id == user.entity_id
    if user.role == "guest":
        item_scope = item_scope & or_(WorkItem.project_id.in_(guest_projects), WorkItem.assignee_id == user.id, WorkItem.reporter_id == user.id)
    items = (await session.scalars(
        select(WorkItem).where(item_scope)
        .order_by(WorkItem.rank, WorkItem.created_at).limit(2_000)
    )).all()
    sprints = (await session.scalars(
        select(AgileSprint).where(AgileSprint.entity_id == user.entity_id)
        .order_by(AgileSprint.created_at.desc()).limit(200)
    )).all()
    releases = (await session.scalars(
        select(AgileRelease).where(AgileRelease.entity_id == user.entity_id)
        .order_by(AgileRelease.target_date, AgileRelease.created_at).limit(200)
    )).all()
    project_scope = Project.entity_id == user.entity_id
    if user.role == "guest":
        project_scope = project_scope & or_(Project.id.in_(guest_projects), Project.owner_id == user.id)
    projects = (await session.scalars(
        select(Project).where(project_scope).order_by(Project.title).limit(1_000)
    )).all()
    saved_views = (await session.scalars(select(SavedWorkspaceView).where(
        SavedWorkspaceView.entity_id == user.entity_id,
        SavedWorkspaceView.view_type == "board",
    ).order_by(SavedWorkspaceView.updated_at.desc()).limit(100))).all()
    comments = (await session.scalars(
        select(WorkItemComment).where(WorkItemComment.entity_id == user.entity_id)
        .order_by(WorkItemComment.created_at).limit(5_000)
    )).all()
    links = (await session.scalars(
        select(WorkItemLink).where(WorkItemLink.entity_id == user.entity_id).limit(5_000)
    )).all()
    activity = (await session.scalars(
        select(WorkItemActivity).where(WorkItemActivity.entity_id == user.entity_id)
        .order_by(WorkItemActivity.created_at.desc()).limit(5_000)
    )).all()
    comments_by_item: dict[str, list[dict[str, Any]]] = {}
    for comment in comments:
        comments_by_item.setdefault(comment.work_item_id, []).append({
            "id": comment.id, "body": comment.body, "created_at": iso(comment.created_at),
            "parent_id": comment.parent_id, "attachments": comment.attachments or [],
            "reactions": [{"emoji": emoji, "count": len(user_ids), "reacted_by_me": user.id in user_ids}
                          for emoji, user_ids in (comment.reactions or {}).items()],
            "author": user_summary(users[comment.author_id]),
        })
    activity_by_item: dict[str, list[dict[str, Any]]] = {}
    for event in activity:
        activity_by_item.setdefault(event.work_item_id, []).append({
            "id": event.id, "action": event.action, "changes": event.changes,
            "created_at": iso(event.created_at), "actor": user_summary(users[event.actor_id]),
        })
    item_payload = []
    for item in items:
        payload = serialize_item(item, users)
        payload["comments"] = comments_by_item.get(item.id, [])
        payload["activity"] = activity_by_item.get(item.id, [])
        payload["links"] = [
            {"id": link.id, "source_id": link.source_id, "target_id": link.target_id, "link_type": link.link_type}
            for link in links if item.id in {link.source_id, link.target_id}
        ]
        item_payload.append(payload)
    return {
        "current_user_role": user.role,
        "workflow": work_workflow(entity),
        "members": [user_summary(member) for member in member_rows],
        "items": item_payload,
        "sprints": [serialize_sprint(sprint) for sprint in sprints],
        "releases": [serialize_release(release) for release in releases],
        "projects": [{
            "id": project.id, "title": project.title,
            "settings": project.settings or {},
            "nodes": [{"id": node.get("id"), "label": node.get("label", "Untitled step")}
                      for node in (project.graph or {}).get("nodes", [])],
        } for project in projects],
        "saved_views": [{"id": view.id, "name": view.name, "config": view.config,
                         "shared": view.shared, "is_default": view.is_default} for view in saved_views
                        if view.owner_id == user.id or view.shared],
    }


@router.put("/workflow")
async def update_work_workflow(
    payload: WorkWorkflowUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, list[dict[str, Any]]]:
    require_admin(user)
    entity = await session.scalar(
        select(Entity).where(Entity.id == user.entity_id).with_for_update()
    )
    columns = [column.model_dump() for column in payload.columns]
    item_types = [item_type.model_dump() for item_type in payload.item_types]
    used_statuses = set((await session.scalars(
        select(WorkItem.status).where(WorkItem.entity_id == user.entity_id).distinct()
    )).all())
    used_item_types = set((await session.scalars(
        select(WorkItem.item_type).where(WorkItem.entity_id == user.entity_id).distinct()
    )).all())
    missing_statuses = sorted(used_statuses - {column["id"] for column in columns})
    missing_item_types = sorted(used_item_types - {item_type["id"] for item_type in item_types})
    if missing_statuses or missing_item_types:
        details = []
        if missing_statuses:
            details.append(f"stages in use: {', '.join(missing_statuses)}")
        if missing_item_types:
            details.append(f"work types in use: {', '.join(missing_item_types)}")
        raise HTTPException(
            status_code=409,
            detail=f"Move or reclassify existing work before removing {'; '.join(details)}",
        )
    entity.work_columns = columns
    entity.work_item_types = item_types
    record_audit_event(
        session, entity_id=user.entity_id, actor_id=user.id,
        action="work.workflow_updated", target_type="entity", target_id=entity.id,
        details={"column_ids": [column["id"] for column in columns],
                 "item_type_ids": [item_type["id"] for item_type in item_types]},
    )
    await session.commit()
    return work_workflow(entity)


@router.post("/items", status_code=status.HTTP_201_CREATED)
async def create_work_item(
    payload: WorkItemCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    data = payload.model_dump()
    await enforce_work_policy(
        session, user, action="create", project_id=data.get("project_id"), fields=set(data),
        content=f"{data.get('summary', '')}\n{data.get('description', '')}\n{data.get('acceptance_criteria', '')}",
    )
    data["watcher_ids"] = list(dict.fromkeys([*data.get("watcher_ids", []), user.id]))
    await validate_work_configuration(session, user, data)
    await validate_item_references(session, data, user)
    entity = await session.scalar(select(Entity).where(Entity.id == user.entity_id).with_for_update())
    sequence = (await session.scalar(
        select(func.max(WorkItem.sequence_number)).where(WorkItem.entity_id == user.entity_id)
    ) or 0) + 1
    rank = (await session.scalar(select(func.max(WorkItem.rank)).where(WorkItem.entity_id == user.entity_id)) or 0) + 1024
    item = WorkItem(
        entity_id=user.entity_id, sequence_number=sequence,
        key=f"{work_prefix(entity.name)}-{sequence}", reporter_id=user.id, rank=rank, **data,
    )
    session.add(item)
    await session.flush()
    add_activity(session, item, user, "created", {"status": item.status})
    assignment_notification(session, item, user)
    webhook_jobs = await stage_webhook_event(
        session,
        entity_id=user.entity_id,
        actor_id=user.id,
        event_type="work_item.created",
        data={"work_item_id": item.id, "key": item.key, "status": item.status, "project_id": item.project_id},
        settings=settings,
    )
    await session.commit()
    await asyncio.gather(*(notify_background_job(job.id) for job in webhook_jobs))
    users = {member.id: member for member in (await session.scalars(select(User).where(User.entity_id == user.entity_id))).all()}
    return serialize_item(item, users)


@router.put("/items/{item_id}")
async def update_work_item(
    item_id: str,
    payload: WorkItemUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    item = await tenant_reference(session, WorkItem, item_id, user, "Work item")
    if user.role != "admin" and user.id not in {item.reporter_id, item.assignee_id}:
        raise HTTPException(status_code=403, detail="Only the reporter, assignee, or an administrator can update this work item")
    if payload.expected_revision != item.revision:
        raise HTTPException(status_code=409, detail="This work item changed. Refresh it before saving again")
    data = payload.model_dump(exclude_unset=True)
    data.pop("expected_revision", None)
    await enforce_work_policy(
        session, user, action="edit", item=item, fields=set(data),
        content="\n".join(str(data.get(key) or "") for key in ("summary", "description", "acceptance_criteria")),
    )
    await enforce_item_field_permissions(session, user, item, set(data))
    await validate_work_configuration(
        session, user, data, current_status=item.status, current_item_type=item.item_type,
    )
    for required_field in ("summary", "item_type", "description", "acceptance_criteria", "status", "priority", "severity", "component", "team", "labels", "checklist", "watcher_ids", "archived"):
        if required_field in data and data[required_field] is None:
            raise HTTPException(status_code=400, detail=f"{required_field.replace('_', ' ').title()} cannot be empty")
    await validate_item_references(
        session, data, user, item.id, item.project_id, item.node_id,
        item.parent_id, item.item_type,
    )
    changes: dict[str, Any] = {}
    for field, value in data.items():
        if field == "summary" and value is not None:
            value = value.strip()
        if field == "labels" and value is not None:
            value = list(dict.fromkeys(label.strip()[:40] for label in value if label.strip()))
        if field in {"component", "team"} and value is not None:
            value = value.strip()
        if field == "checklist" and value is not None:
            value = [entry.model_dump() if isinstance(entry, ChecklistEntry) else entry for entry in value]
        if field == "watcher_ids" and value is not None:
            value = list(dict.fromkeys(value))
        previous = getattr(item, field)
        if previous != value:
            changes[field] = {"from": json_value(previous), "to": json_value(value)}
            setattr(item, field, value)
    effective_start = data.get("start_date", item.start_date)
    effective_due = data.get("due_date", item.due_date)
    if effective_start and effective_due and effective_start > effective_due:
        raise HTTPException(status_code=400, detail="Start date must be on or before due date")
    if changes:
        item.revision += 1
        item.updated_at = datetime.now(timezone.utc)
        add_activity(session, item, user, "updated", changes)
        if "assignee_id" in changes:
            assignment_notification(session, item, user)
        follower_notifications(session, item, user, f"{item.key} was updated")
    webhook_jobs = await stage_webhook_event(
        session,
        entity_id=user.entity_id,
        actor_id=user.id,
        event_type="work_item.updated",
        data={
            "work_item_id": item.id,
            "key": item.key,
            "status": item.status,
            "project_id": item.project_id,
            "changed_fields": sorted(changes),
        },
        settings=settings,
    ) if changes else []
    await session.commit()
    await asyncio.gather(*(notify_background_job(job.id) for job in webhook_jobs))
    users = {member.id: member for member in (await session.scalars(select(User).where(User.entity_id == user.entity_id))).all()}
    return serialize_item(item, users)


@router.post("/items/{item_id}/duplicate", status_code=status.HTTP_201_CREATED)
async def duplicate_work_item(
    item_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    source = await tenant_reference(session, WorkItem, item_id, user, "Work item")
    await enforce_work_policy(session, user, action="create", item=source)
    entity = await session.scalar(select(Entity).where(Entity.id == user.entity_id).with_for_update())
    sequence = (await session.scalar(
        select(func.max(WorkItem.sequence_number)).where(WorkItem.entity_id == user.entity_id)
    ) or 0) + 1
    rank = (await session.scalar(
        select(func.max(WorkItem.rank)).where(WorkItem.entity_id == user.entity_id)
    ) or 0) + 1024
    duplicate = WorkItem(
        entity_id=user.entity_id, sequence_number=sequence,
        key=f"{work_prefix(entity.name)}-{sequence}", reporter_id=user.id,
        assignee_id=source.assignee_id, owner_id=source.owner_id,
        sprint_id=None, release_id=source.release_id, project_id=source.project_id,
        parent_id=source.parent_id, node_id=source.node_id, item_type=source.item_type,
        summary=f"Copy of {source.summary}"[:180], description=source.description,
        acceptance_criteria=source.acceptance_criteria, status=work_workflow(entity)["columns"][0]["id"],
        priority=source.priority, severity=source.severity, story_points=source.story_points,
        estimate_minutes=source.estimate_minutes, actual_minutes=None,
        component=source.component or "", team=source.team or "", labels=list(source.labels or []),
        checklist=[{**entry, "done": False} for entry in (source.checklist or [])],
        watcher_ids=[user.id], custom_fields=dict(source.custom_fields or {}), start_date=None, due_date=source.due_date,
        archived=False, rank=rank,
    )
    session.add(duplicate)
    await session.flush()
    add_activity(session, duplicate, user, "duplicated", {"source_id": source.id, "source_key": source.key})
    assignment_notification(session, duplicate, user)
    await session.commit()
    users = {member.id: member for member in (await session.scalars(
        select(User).where(User.entity_id == user.entity_id)
    )).all()}
    return serialize_item(duplicate, users)


@router.post("/items/{item_id}/split", status_code=status.HTTP_201_CREATED)
async def split_work_item(
    item_id: str, payload: WorkItemSplit,
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    parent = await tenant_reference(session, WorkItem, item_id, user, "Work item")
    await enforce_work_policy(session, user, action="edit", item=parent, fields={"summary", "parent_id"}, content="\n".join(payload.parts))
    if user.role != "admin" and user.id not in {parent.reporter_id, parent.assignee_id}:
        raise HTTPException(status_code=403, detail="Only the reporter, assignee, or an administrator can split this work item")
    entity = await session.scalar(select(Entity).where(Entity.id == user.entity_id).with_for_update())
    workflow = work_workflow(entity)
    configured_type = next((entry.get("child_type") for entry in workflow["item_types"] if entry["id"] == parent.item_type), None)
    child_type = configured_type or ("subtask" if parent.item_type in {"story", "task"} else "task")
    sequence = (await session.scalar(select(func.max(WorkItem.sequence_number)).where(WorkItem.entity_id == user.entity_id)) or 0)
    rank = parent.rank
    children = []
    points_each = parent.story_points // len(payload.parts) if parent.story_points else None
    for offset, summary in enumerate(payload.parts, 1):
        sequence += 1
        child = WorkItem(
            entity_id=user.entity_id, sequence_number=sequence,
            key=f"{work_prefix(entity.name)}-{sequence}", reporter_id=user.id,
            assignee_id=parent.assignee_id, owner_id=parent.owner_id,
            sprint_id=parent.sprint_id, release_id=parent.release_id,
            project_id=parent.project_id, parent_id=parent.id, node_id=parent.node_id,
            item_type=child_type, summary=summary, description="",
            acceptance_criteria="", status=parent.status, priority=parent.priority,
            story_points=points_each, component=parent.component, team=parent.team,
            labels=list(parent.labels or []), watcher_ids=[user.id],
            custom_fields=dict(parent.custom_fields or {}), start_date=parent.start_date,
            due_date=parent.due_date, rank=rank + offset,
        )
        session.add(child); children.append(child)
    await session.flush()
    add_activity(session, parent, user, "split", {"child_ids": [child.id for child in children]})
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="work_item.split",
                       project_id=parent.project_id, target_type="work_item", target_id=parent.id,
                       details={"child_ids": [child.id for child in children]})
    await session.commit()
    users = {member.id: member for member in (await session.scalars(select(User).where(User.entity_id == user.entity_id))).all()}
    return [serialize_item(child, users) for child in children]


@router.post("/items/{item_id}/merge")
async def merge_work_items(
    item_id: str, payload: WorkItemMerge,
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    target = await tenant_reference(session, WorkItem, item_id, user, "Target work item")
    await enforce_work_policy(session, user, action="edit", item=target, fields={"description", "labels", "story_points", "archived"})
    if user.role != "admin" and user.id not in {target.reporter_id, target.assignee_id}:
        raise HTTPException(status_code=403, detail="Only the reporter, assignee, or an administrator can merge work")
    source_ids = list(dict.fromkeys(value for value in payload.source_ids if value != target.id))
    sources = []
    for source_id in source_ids:
        source = await tenant_reference(session, WorkItem, source_id, user, "Source work item")
        if source.archived:
            raise HTTPException(status_code=409, detail=f"{source.key} is already archived")
        sources.append(source)
    target.description = "\n\n".join(filter(None, [target.description, *[f"Merged from {source.key}: {source.summary}\n{source.description}".strip() for source in sources]]))
    target.labels = list(dict.fromkeys([*(target.labels or []), *[label for source in sources for label in (source.labels or [])]]))
    target.story_points = sum(value or 0 for value in [target.story_points, *[source.story_points for source in sources]]) or None
    target.revision += 1; target.updated_at = datetime.now(timezone.utc)
    for source in sources:
        source.archived = True; source.revision += 1; source.updated_at = target.updated_at
    add_activity(session, target, user, "merged", {"source_ids": source_ids})
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="work_item.merged",
                       project_id=target.project_id, target_type="work_item", target_id=target.id,
                       details={"source_ids": source_ids})
    await session.commit()
    users = {member.id: member for member in (await session.scalars(select(User).where(User.entity_id == user.entity_id))).all()}
    return serialize_item(target, users)


class FollowUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    following: bool = True


@router.put("/items/{item_id}/follow")
async def follow_work_item(
    item_id: str,
    payload: FollowUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    item = await tenant_reference(session, WorkItem, item_id, user, "Work item")
    await enforce_work_policy(session, user, action="edit", item=item, fields={"watcher_ids"})
    watcher_ids = list(dict.fromkeys(item.watcher_ids or []))
    if payload.following and user.id not in watcher_ids:
        watcher_ids.append(user.id)
    if not payload.following:
        watcher_ids = [watcher_id for watcher_id in watcher_ids if watcher_id != user.id]
    if watcher_ids != (item.watcher_ids or []):
        item.watcher_ids = watcher_ids
        item.revision += 1
        item.updated_at = datetime.now(timezone.utc)
        add_activity(session, item, user, "followed" if payload.following else "unfollowed", {})
    await session.commit()
    users = {member.id: member for member in (await session.scalars(
        select(User).where(User.entity_id == user.entity_id)
    )).all()}
    return serialize_item(item, users)


@router.put("/bulk/items")
async def bulk_update_work_items(
    payload: WorkItemBulkUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    item_ids = list(dict.fromkeys(payload.item_ids))
    items = list(await session.scalars(select(WorkItem).where(
        WorkItem.id.in_(item_ids), WorkItem.entity_id == user.entity_id,
    )))
    if len(items) != len(item_ids):
        raise HTTPException(status_code=404, detail="One or more work items were not found")
    if user.role != "admin" and any(user.id not in {item.reporter_id, item.assignee_id} for item in items):
        raise HTTPException(status_code=403, detail="You cannot update every selected work item")
    changes = payload.model_dump(exclude_unset=True)
    changes.pop("item_ids", None)
    add_labels = changes.pop("add_labels", [])
    if not changes and not add_labels:
        raise HTTPException(status_code=400, detail="Choose at least one bulk change")
    for required_field in ("item_type", "status", "priority", "severity", "component", "team", "archived"):
        if required_field in changes and changes[required_field] is None:
            raise HTTPException(status_code=400, detail=f"{required_field.replace('_', ' ').title()} cannot be empty")
    for text_field in ("component", "team"):
        if text_field in changes:
            changes[text_field] = changes[text_field].strip()
    if "status" in changes:
        entity = await session.get(Entity, user.entity_id)
        if changes["status"] not in {column["id"] for column in work_workflow(entity)["columns"]}:
            raise HTTPException(status_code=400, detail="Status is not part of this workspace workflow")
    await validate_work_configuration(session, user, changes)
    await validate_item_references(session, changes, user)
    for item in items:
        await enforce_work_policy(
            session, user, action="edit", item=item,
            fields=set(changes) | ({"labels"} if add_labels else set()),
        )
        await enforce_item_field_permissions(
            session, user, item, set(changes) | ({"labels"} if add_labels else set()),
        )
        item_changes: dict[str, Any] = {}
        for field, value in changes.items():
            previous = getattr(item, field)
            if previous != value:
                setattr(item, field, value)
                item_changes[field] = {"from": json_value(previous), "to": json_value(value)}
        if add_labels:
            labels = list(dict.fromkeys([*(item.labels or []), *(label.strip()[:40] for label in add_labels if label.strip())]))
            if labels != (item.labels or []):
                item_changes["labels"] = {"from": item.labels or [], "to": labels}
                item.labels = labels
        if item.start_date and item.due_date and item.start_date > item.due_date:
            raise HTTPException(status_code=400, detail=f"{item.key} would start after its due date")
        if item_changes:
            item.revision += 1
            item.updated_at = datetime.now(timezone.utc)
            add_activity(session, item, user, "bulk_updated", item_changes)
            if "assignee_id" in item_changes:
                assignment_notification(session, item, user)
            follower_notifications(session, item, user, f"{item.key} was updated")
    await session.commit()
    users = {member.id: member for member in (await session.scalars(
        select(User).where(User.entity_id == user.entity_id)
    )).all()}
    return [serialize_item(item, users) for item in items]


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_work_item(
    item_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> None:
    require_admin(user)
    item = await tenant_reference(session, WorkItem, item_id, user, "Work item")
    if await is_held(session, user.entity_id, "work_item", item.id) or (
        item.project_id and await is_held(session, user.entity_id, "project", item.project_id)
    ):
        raise HTTPException(status_code=409, detail={"message": "This work item is preserved by an active legal hold", "code": "legal_hold"})
    await enforce_work_policy(session, user, action="delete", item=item)
    record_audit_event(
        session, entity_id=user.entity_id, actor_id=user.id, action="work_item.deleted",
        project_id=item.project_id, target_type="work_item", target_id=item.id,
        details={"key": item.key, "summary": item.summary},
    )
    webhook_jobs = await stage_webhook_event(
        session,
        entity_id=user.entity_id,
        actor_id=user.id,
        event_type="work_item.deleted",
        data={"work_item_id": item.id, "key": item.key, "project_id": item.project_id},
        settings=settings,
    )
    await session.delete(item)
    await session.commit()
    await asyncio.gather(*(notify_background_job(job.id) for job in webhook_jobs))


@router.post("/items/{item_id}/comments", status_code=status.HTTP_201_CREATED)
async def create_comment(
    item_id: str,
    payload: CommentCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    item = await tenant_reference(session, WorkItem, item_id, user, "Work item")
    body = payload.body.strip()
    await enforce_work_policy(session, user, action="comment", item=item, fields={"comments"}, content=body)
    if payload.parent_id:
        parent = await tenant_reference(session, WorkItemComment, payload.parent_id, user, "Parent comment")
        if parent.work_item_id != item.id:
            raise HTTPException(status_code=400, detail="Reply target belongs to a different work item")
    attachments = [{"name": str(entry.get("name", ""))[:240], "url": str(entry.get("url", ""))[:1000]}
                   for entry in payload.attachments if str(entry.get("name", "")).strip() and str(entry.get("url", "")).startswith("https://")]
    comment = WorkItemComment(entity_id=user.entity_id, work_item_id=item.id, author_id=user.id,
                              body=body, parent_id=payload.parent_id, attachments=attachments)
    session.add(comment)
    await session.flush()
    add_activity(session, item, user, "commented", {"comment_id": comment.id})
    members = (await session.scalars(select(User).where(User.entity_id == user.entity_id))).all()
    handles = {match.lower() for match in HANDLE_PATTERN.findall(body)}
    recipients = {member.id for member in members if user_handle(member).lower() in handles}
    recipients.update(item.watcher_ids or [])
    if item.assignee_id and item.assignee_id != user.id:
        recipients.add(item.assignee_id)
    for recipient_id in recipients - {user.id}:
        session.add(Notification(
            entity_id=user.entity_id, user_id=recipient_id, actor_id=user.id,
            kind="work_item_comment", title=f"New comment on {item.key}",
            body=body[:500], project_id=item.project_id, work_item_id=item.id,
        ))
    webhook_jobs = await stage_webhook_event(
        session,
        entity_id=user.entity_id,
        actor_id=user.id,
        event_type="work_item.comment.created",
        data={"work_item_id": item.id, "comment_id": comment.id, "project_id": item.project_id},
        settings=settings,
    )
    await session.commit()
    await asyncio.gather(*(notify_background_job(job.id) for job in webhook_jobs))
    return {"id": comment.id, "body": comment.body, "parent_id": comment.parent_id,
            "attachments": comment.attachments, "reactions": [],
            "created_at": iso(comment.created_at), "author": user_summary(user)}


@router.put("/items/{item_id}/comments/{comment_id}/reaction")
async def react_to_comment(
    item_id: str, comment_id: str, payload: CommentReaction,
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    item = await tenant_reference(session, WorkItem, item_id, user, "Work item")
    comment = await tenant_reference(session, WorkItemComment, comment_id, user, "Comment")
    if comment.work_item_id != item.id:
        raise HTTPException(status_code=404, detail="Comment not found")
    reactions = dict(comment.reactions or {})
    participants = list(reactions.get(payload.emoji, []))
    if user.id in participants: participants.remove(user.id)
    else: participants.append(user.id)
    if participants: reactions[payload.emoji] = participants
    else: reactions.pop(payload.emoji, None)
    comment.reactions = reactions
    await session.commit()
    return {"comment_id": comment.id, "reactions": [{"emoji": emoji, "count": len(ids), "reacted_by_me": user.id in ids} for emoji, ids in reactions.items()]}


@router.post("/items/{item_id}/links", status_code=status.HTTP_201_CREATED)
async def create_link(
    item_id: str,
    payload: WorkLinkCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    source = await tenant_reference(session, WorkItem, item_id, user, "Work item")
    target = await tenant_reference(session, WorkItem, payload.target_id, user, "Linked work item")
    if source.id == target.id:
        raise HTTPException(status_code=400, detail="A work item cannot link to itself")
    existing = await session.scalar(select(WorkItemLink).where(
        WorkItemLink.source_id == source.id, WorkItemLink.target_id == target.id,
        WorkItemLink.link_type == payload.link_type,
    ))
    if existing:
        raise HTTPException(status_code=409, detail="That dependency already exists")
    link = WorkItemLink(
        entity_id=user.entity_id, source_id=source.id, target_id=target.id,
        link_type=payload.link_type, created_by_id=user.id,
    )
    session.add(link)
    await session.flush()
    add_activity(session, source, user, "linked", {"target_key": target.key, "link_type": link.link_type})
    await session.commit()
    return {"id": link.id, "source_id": link.source_id, "target_id": link.target_id, "link_type": link.link_type}


@router.delete("/links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_link(
    link_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    link = await tenant_reference(session, WorkItemLink, link_id, user, "Dependency")
    source = await tenant_reference(session, WorkItem, link.source_id, user, "Work item")
    if user.role != "admin" and user.id not in {source.reporter_id, source.assignee_id}:
        raise HTTPException(status_code=403, detail="Only the reporter, assignee, or an administrator can remove this dependency")
    await session.delete(link)
    await session.commit()


@router.post("/sprints", status_code=status.HTTP_201_CREATED)
async def create_sprint(
    payload: SprintCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    require_admin(user)
    sprint = AgileSprint(entity_id=user.entity_id, created_by_id=user.id, **payload.model_dump())
    session.add(sprint)
    await session.flush()
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="sprint.created", target_type="sprint", target_id=sprint.id, details={"name": sprint.name})
    await session.commit()
    return serialize_sprint(sprint)


@router.put("/sprints/{sprint_id}")
async def update_sprint(
    sprint_id: str,
    payload: SprintUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    require_admin(user)
    sprint = await tenant_reference(session, AgileSprint, sprint_id, user, "Sprint")
    if payload.expected_revision != sprint.revision:
        raise HTTPException(status_code=409, detail="This sprint changed. Refresh it before saving again")
    data = payload.model_dump()
    data.pop("expected_revision")
    if data["status"] == "active":
        another = await session.scalar(select(AgileSprint).where(
            AgileSprint.entity_id == user.entity_id, AgileSprint.status == "active", AgileSprint.id != sprint.id
        ))
        if another:
            raise HTTPException(status_code=409, detail="Complete the active sprint before starting another")
    for field, value in data.items():
        setattr(sprint, field, value)
    sprint.revision += 1
    sprint.updated_at = datetime.now(timezone.utc)
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="sprint.updated", target_type="sprint", target_id=sprint.id, details={"status": sprint.status})
    await session.commit()
    return serialize_sprint(sprint)


@router.post("/releases", status_code=status.HTTP_201_CREATED)
async def create_release(
    payload: ReleaseCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    require_admin(user)
    data = payload.model_dump()
    if not data["baseline"]:
        data["baseline"] = {"start_date": date_iso(payload.start_date), "target_date": date_iso(payload.target_date)}
    release = AgileRelease(entity_id=user.entity_id, created_by_id=user.id, **data)
    session.add(release)
    await session.flush()
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="release.created", target_type="release", target_id=release.id, details={"name": release.name})
    await session.commit()
    return serialize_release(release)


@router.put("/releases/{release_id}")
async def update_release(
    release_id: str,
    payload: ReleaseUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    require_admin(user)
    release = await tenant_reference(session, AgileRelease, release_id, user, "Release")
    if payload.expected_revision != release.revision:
        raise HTTPException(status_code=409, detail="This release changed. Refresh it before saving again")
    data = payload.model_dump()
    data.pop("expected_revision")
    for field, value in data.items():
        if field in {"scenario", "baseline"} and value is None:
            continue
        setattr(release, field, value)
    release.released_at = datetime.now(timezone.utc) if release.status == "released" else None
    release.revision += 1
    release.updated_at = datetime.now(timezone.utc)
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="release.updated", target_type="release", target_id=release.id, details={"status": release.status})
    await session.commit()
    return serialize_release(release)
