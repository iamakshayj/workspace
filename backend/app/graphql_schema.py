import asyncio
import base64
import binascii
from calendar import monthrange
import json
import logging
import re
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from urllib.parse import urlparse
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import strawberry
from fastapi import Depends
from graphql import GraphQLError
from pydantic import ValidationError
from sqlalchemy import and_, case, delete, func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from strawberry.fastapi import BaseContext, GraphQLRouter
from strawberry.types import Info

from .auth import create_invitation_token, get_current_user, hash_invitation_token
from .artifact_service import delete_project_objects
from .calendar_reminders import REMINDER_MINUTES, dispatch_due_calendar_reminders
from .config import Settings, get_settings
from .communications import (
    communication_hub,
    serialize_channel_message,
    serialize_direct_message,
    serialize_notification,
)
from .database import (
    AuditEvent,
    CalendarEvent,
    CalendarEventAttendee,
    CalendarEventExternalAttendee,
    CommunicationChannel,
    CommunicationChannelMember,
    CommunicationChannelMessage,
    DirectMessage,
    Entity,
    Invitation,
    Notification,
    NotificationPreference,
    Project,
    ProjectApproval,
    ProjectCollaborator,
    ProjectGroupAccess,
    OrganizationUnitMember,
    ProjectDeliverable,
    ProjectRevision,
    ProjectTask,
    User,
    get_session,
)
from .governance import (
    can_approve_project,
    can_edit_project,
    can_manage_project,
    default_project_role,
    latest_revision,
    normalize_project_role,
    normalize_visibility,
    project_access_role,
    record_audit_event,
    snapshot_project,
)
from .identity import as_utc, user_summary
from .job_service import (
    INVITATION_EMAIL_JOB,
    MEETING_EMAIL_JOB,
    new_background_job,
    notify_background_job,
)
from .object_storage import ObjectStorageError, object_storage
from .policy_engine import PolicyContext, evaluate_dlp, evaluate_policy, is_held, load_policy_snapshot
from .quota_service import (
    QuotaExceededError,
    ensure_project_capacity,
    ensure_user_capacity,
)
from .schemas import ProjectProfile, ProjectWrite
from .secret_box import SecretBox
from .telemetry import metrics


logger = logging.getLogger("flowforge.graphql")


async def enforce_message_policies(info: "GraphQLInfo", body: str, action: str = "create") -> None:
    decision = await evaluate_policy(info.context.session, info.context.user, PolicyContext(
        action=action, resource_type="message", source_type="message", preauthorized=True,
    ))
    if not decision.allowed:
        raise GraphQLError(
            "Workspace policy does not permit this message action",
            extensions={"code": "POLICY_DENIED", "reason": decision.reason, "ruleIds": decision.matched_rule_ids},
        )
    dlp = await evaluate_dlp(
        info.context.session, info.context.user, content=body,
        source_type="message", action="webhook.send",
    )
    if not dlp.allowed:
        raise GraphQLError(
            "Data protection policy blocked this message",
            extensions={"code": "DLP_BLOCKED", "classification": dlp.classification, "findings": dlp.findings},
        )


async def enforce_calendar_policy(
    info: "GraphQLInfo",
    *,
    action: str,
    event: CalendarEvent | None = None,
    content: str = "",
    fields: set[str] | None = None,
) -> None:
    decision = await evaluate_policy(info.context.session, info.context.user, PolicyContext(
        action=action, resource_type="meeting", resource_id=event.id if event else None,
        fields=fields or set(), source_type="calendar", preauthorized=True,
    ))
    if not decision.allowed:
        raise GraphQLError(
            "Workspace policy does not permit this calendar action",
            extensions={"code": "POLICY_DENIED", "reason": decision.reason, "ruleIds": decision.matched_rule_ids},
        )
    if content:
        dlp = await evaluate_dlp(
            info.context.session, info.context.user, content=content,
            source_type="calendar", action=action,
        )
        if not dlp.allowed:
            raise GraphQLError(
                "Data protection policy blocked this calendar content",
                extensions={"code": "DLP_BLOCKED", "classification": dlp.classification, "findings": dlp.findings},
            )
@strawberry.type(name="GraphWarning")
class GraphWarningType:
    code: str
    message: str
    node_ids: list[strawberry.ID]


@strawberry.type(name="FlowNode")
class FlowNodeType:
    id: strawberry.ID
    label: str
    type: str
    x: float
    y: float
    owner: str | None = None
    description: str | None = None
    color: str | None = None
    shape: str = "rounded"
    symbol: str | None = None
    width: float = 180
    height: float = 76
    backup_owner: str | None = None
    system: str | None = None
    vendor: str | None = None
    control_id: str | None = None
    policy_reference: str | None = None
    evidence_requirement: str | None = None
    segregation_rule: str | None = None
    risk_level: str = "none"
    data_classification: str = "internal"
    sla_minutes: int | None = None
    review_date: str | None = None
    required: bool = False
    layer: str = "Default"
    parent_id: strawberry.ID | None = None


@strawberry.type(name="FlowEdge")
class FlowEdgeType:
    source: strawberry.ID
    target: strawberry.ID
    label: str
    is_loop: bool
    bidirectional: bool


@strawberry.type(name="FlowchartGraph")
class FlowchartGraphType:
    title: str
    nodes: list[FlowNodeType]
    edges: list[FlowEdgeType]
    questions: list[str]
    warnings: list[GraphWarningType]


@strawberry.type(name="ProjectMember")
class ProjectMemberType:
    id: strawberry.ID
    display_name: str
    email: str
    role: str
    color: str


@strawberry.type(name="ProjectProfile")
class ProjectProfileType:
    key: str
    sponsor_id: strawberry.ID | None
    department: str
    team: str
    program: str
    priority: str
    health: str
    start_date: date | None
    target_date: date | None
    progress: int | None
    classification: str
    tags: list[str]
    template: str


@strawberry.type(name="Project")
class ProjectType:
    id: strawberry.ID
    title: str
    description: str
    status: str
    visibility: str
    approval_status: str
    current_user_access: str
    revision_number: int
    document_revision: int
    owner: ProjectMemberType | None
    collaborators: list[ProjectMemberType]
    profile: ProjectProfileType
    source_text: str
    graph: FlowchartGraphType
    created_at: datetime
    updated_at: datetime


@strawberry.type(name="ProjectSummary")
class ProjectSummaryType:
    id: strawberry.ID
    title: str
    description: str
    status: str
    visibility: str
    approval_status: str
    current_user_access: str
    profile: ProjectProfileType
    owner: ProjectMemberType | None
    collaborators: list[ProjectMemberType]
    collaborator_count: int
    deliverable_count: int
    completed_deliverable_count: int
    task_count: int
    completed_task_count: int
    plan_progress: int
    created_at: datetime
    updated_at: datetime
    node_count: int
    edge_count: int


@strawberry.type(name="ProjectPage")
class ProjectPageType:
    items: list[ProjectSummaryType]
    next_cursor: str | None
    total_count: int


@strawberry.type(name="ProjectAccess")
class ProjectAccessType:
    user: ProjectMemberType
    access_role: str


@strawberry.type(name="ProjectRevision")
class ProjectRevisionType:
    id: strawberry.ID
    version: int
    change_summary: str
    created_by: ProjectMemberType
    created_at: datetime
    title: str
    status: str
    node_count: int
    edge_count: int


@strawberry.type(name="ProjectApproval")
class ProjectApprovalType:
    id: strawberry.ID
    revision_id: strawberry.ID
    revision_version: int
    status: str
    request_note: str
    decision_note: str
    requested_by: ProjectMemberType
    reviewer: ProjectMemberType | None
    requested_at: datetime
    decided_at: datetime | None


@strawberry.type(name="ProjectAuditEvent")
class ProjectAuditEventType:
    id: strawberry.ID
    action: str
    actor: ProjectMemberType | None
    details: strawberry.scalars.JSON
    created_at: datetime


@strawberry.type(name="ProjectGovernance")
class ProjectGovernanceType:
    project_id: strawberry.ID
    visibility: str
    approval_status: str
    current_user_access: str
    current_revision: int
    access_entries: list[ProjectAccessType]
    revisions: list[ProjectRevisionType]
    approval: ProjectApprovalType | None
    audit_events: list[ProjectAuditEventType]


@strawberry.type(name="Workspace")
class WorkspaceType:
    id: strawberry.ID
    name: str
    member_count: int


@strawberry.type(name="WorkspaceMember")
class WorkspaceMemberType:
    id: strawberry.ID
    display_name: str
    email: str
    role: str
    created_at: datetime
    is_current_user: bool


@strawberry.type(name="CommunicationUser")
class CommunicationUserType:
    id: strawberry.ID
    display_name: str
    email: str
    role: str
    handle: str
    color: str


@strawberry.type(name="MessageReaction")
class MessageReactionType:
    emoji: str
    count: int
    reacted_by_me: bool


@strawberry.type(name="MessageAttachment")
class MessageAttachmentType:
    name: str
    url: str


@strawberry.input(name="MessageAttachmentInput")
class MessageAttachmentInput:
    name: str
    url: str


@strawberry.type(name="DirectMessage")
class DirectMessageType:
    id: strawberry.ID
    body: str
    read: bool
    created_at: datetime
    parent_id: strawberry.ID | None
    reactions: list[MessageReactionType]
    pinned: bool
    bookmarked: bool
    attachments: list[MessageAttachmentType]
    edited_at: datetime | None
    deleted_at: datetime | None
    can_edit: bool
    sender: CommunicationUserType
    recipient: CommunicationUserType


@strawberry.type(name="CommunicationContact")
class CommunicationContactType:
    user: CommunicationUserType
    unread_count: int
    latest_message: str | None
    latest_message_at: datetime | None


@strawberry.type(name="ChannelMessage")
class ChannelMessageType:
    id: strawberry.ID
    channel_id: strawberry.ID
    body: str
    created_at: datetime
    parent_id: strawberry.ID | None
    reactions: list[MessageReactionType]
    pinned: bool
    bookmarked: bool
    attachments: list[MessageAttachmentType]
    edited_at: datetime | None
    deleted_at: datetime | None
    can_edit: bool
    sender: CommunicationUserType


@strawberry.type(name="MessageSearchResult")
class MessageSearchResultType:
    kind: str
    context_id: strawberry.ID
    context_title: str
    message_id: strawberry.ID
    body: str
    created_at: datetime
    sender: CommunicationUserType


@strawberry.type(name="CommunicationChannel")
class CommunicationChannelType:
    id: strawberry.ID
    name: str
    description: str
    channel_type: str
    visibility: str
    unread_count: int
    latest_message: str | None
    latest_message_at: datetime | None
    member_count: int
    members: list[CommunicationUserType]
    created_by_id: strawberry.ID
    can_manage: bool


@strawberry.type(name="Notification")
class NotificationType:
    id: strawberry.ID
    kind: str
    title: str
    body: str
    project_id: strawberry.ID | None
    contact_id: strawberry.ID | None
    calendar_event_id: strawberry.ID | None
    work_item_id: strawberry.ID | None
    communication_channel_id: strawberry.ID | None
    communication_message_id: strawberry.ID | None
    document_id: strawberry.ID | None
    group_key: str | None
    snoozed_until: datetime | None
    read: bool
    created_at: datetime
    actor: CommunicationUserType | None


@strawberry.type(name="CalendarAttendee")
class CalendarAttendeeType:
    user: CommunicationUserType
    response: str
    is_organizer: bool


@strawberry.type(name="CalendarExternalAttendee")
class CalendarExternalAttendeeType:
    email: str
    response: str
    delivery_status: str


@strawberry.type(name="CalendarEvent")
class CalendarEventType:
    id: strawberry.ID
    title: str
    description: str
    event_type: str
    starts_at: datetime
    ends_at: datetime
    timezone: str
    all_day: bool
    location: str
    meeting_url: str
    status: str
    series_id: strawberry.ID | None
    recurrence_frequency: str | None
    recurrence_interval: int
    recurrence_ends_at: date | None
    recurrence_count: int | None
    occurrence_index: int
    organizer: CommunicationUserType
    attendees: list[CalendarAttendeeType]
    external_attendees: list[CalendarExternalAttendeeType]
    my_response: str
    reminder_minutes: int | None
    can_manage: bool
    created_at: datetime
    updated_at: datetime


@strawberry.type(name="CalendarBusyBlock")
class CalendarBusyBlockType:
    starts_at: datetime
    ends_at: datetime


@strawberry.type(name="CalendarAvailabilityUser")
class CalendarAvailabilityUserType:
    user: CommunicationUserType
    busy: list[CalendarBusyBlockType]


@strawberry.type(name="MeetingTimeSuggestion")
class MeetingTimeSuggestionType:
    starts_at: datetime
    ends_at: datetime
    available_user_ids: list[strawberry.ID]
    unavailable_user_ids: list[strawberry.ID]
    attendance_count: int
    total_count: int
    score: int


@strawberry.type(name="CalendarAvailability")
class CalendarAvailabilityType:
    timezone: str
    range_start: datetime
    range_end: datetime
    users: list[CalendarAvailabilityUserType]
    suggestions: list[MeetingTimeSuggestionType]


@strawberry.input(name="CalendarEventInput")
class CalendarEventInput:
    title: str
    event_type: str
    starts_at: datetime
    ends_at: datetime
    description: str = ""
    timezone: str = "UTC"
    all_day: bool = False
    location: str = ""
    meeting_url: str = ""
    reminder_minutes: int | None = 15
    recurrence_frequency: str = "none"
    recurrence_interval: int = 1
    recurrence_ends_at: date | None = None
    recurrence_count: int | None = None
    attendee_ids: list[strawberry.ID] = strawberry.field(default_factory=list)
    external_attendee_emails: list[str] = strawberry.field(default_factory=list)


@strawberry.input(name="CalendarAvailabilityInput")
class CalendarAvailabilityInput:
    user_ids: list[strawberry.ID]
    starts_after: datetime
    starts_before: datetime
    timezone: str = "UTC"
    duration_minutes: int = 30
    workday_starts_at: str = "09:00"
    workday_ends_at: str = "17:00"
    interval_minutes: int = 15
    include_weekends: bool = False
    max_suggestions: int = 12


@strawberry.type(name="WorkspaceInvitation")
class WorkspaceInvitationType:
    id: strawberry.ID
    display_name: str
    email: str
    job_title: str | None
    role: str
    status: str
    delivery_status: str
    expires_at: datetime
    created_at: datetime
    setup_url: str | None = None


@strawberry.input(name="GraphWarningInput")
class GraphWarningInput:
    code: str
    message: str
    node_ids: list[strawberry.ID] = strawberry.field(default_factory=list)


@strawberry.input(name="FlowNodeInput")
class FlowNodeInput:
    id: strawberry.ID
    label: str
    type: str
    x: float
    y: float
    owner: str | None = None
    description: str | None = None
    color: str | None = None
    shape: str = "rounded"
    symbol: str | None = None
    width: float = 180
    height: float = 76
    backup_owner: str | None = None
    system: str | None = None
    vendor: str | None = None
    control_id: str | None = None
    policy_reference: str | None = None
    evidence_requirement: str | None = None
    segregation_rule: str | None = None
    risk_level: str = "none"
    data_classification: str = "internal"
    sla_minutes: int | None = None
    review_date: str | None = None
    required: bool = False
    layer: str = "Default"
    parent_id: strawberry.ID | None = None


@strawberry.input(name="FlowEdgeInput")
class FlowEdgeInput:
    source: strawberry.ID
    target: strawberry.ID
    label: str = ""
    is_loop: bool = False
    bidirectional: bool = False


@strawberry.input(name="FlowchartGraphInput")
class FlowchartGraphInput:
    title: str
    nodes: list[FlowNodeInput]
    edges: list[FlowEdgeInput]
    questions: list[str]
    warnings: list[GraphWarningInput]


@strawberry.input(name="ProjectInput")
class ProjectInput:
    title: str
    source_text: str
    graph: FlowchartGraphInput
    description: str = ""
    status: str = "active"
    owner_id: strawberry.ID | None = None
    collaborator_ids: list[strawberry.ID] = strawberry.field(default_factory=list)
    profile: strawberry.scalars.JSON = strawberry.field(default_factory=dict)


@strawberry.input(name="ProjectAccessInput")
class ProjectAccessInput:
    user_id: strawberry.ID
    access_role: str


@strawberry.input(name="InviteMemberInput")
class InviteMemberInput:
    display_name: str
    email: str
    role: str = "basic"
    job_title: str | None = None


class GraphQLContext(BaseContext):
    def __init__(self, session: AsyncSession, user: User, settings: Settings) -> None:
        self.session = session
        self.user = user
        self.settings = settings


GraphQLInfo = Info[GraphQLContext, None]


async def get_graphql_context(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> GraphQLContext:
    return GraphQLContext(session=session, user=user, settings=settings)


def serialize_graph(graph: dict) -> FlowchartGraphType:
    return FlowchartGraphType(
        title=graph["title"],
        nodes=[FlowNodeType(**node) for node in graph.get("nodes", [])],
        edges=[FlowEdgeType(**edge) for edge in graph.get("edges", [])],
        questions=graph.get("questions", []),
        warnings=[
            GraphWarningType(
                code=warning["code"],
                message=warning["message"],
                node_ids=[strawberry.ID(node_id) for node_id in warning.get("node_ids", [])],
            )
            for warning in graph.get("warnings", [])
        ],
    )


def project_member_type(user: User) -> ProjectMemberType:
    return ProjectMemberType(
        id=strawberry.ID(user.id),
        display_name=user.display_name,
        email=user.email,
        role=user.role,
        color=user_summary(user)["color"],
    )


async def load_project_people(
    session: AsyncSession,
    projects: list[Project],
) -> dict[str, tuple[User | None, list[User]]]:
    if not projects:
        return {}
    project_ids = [project.id for project in projects]
    rows = (
        await session.execute(
            select(ProjectCollaborator.project_id, User)
            .join(User, User.id == ProjectCollaborator.user_id)
            .where(ProjectCollaborator.project_id.in_(project_ids))
            .order_by(User.display_name.asc())
        )
    ).all()
    collaborators: dict[str, list[User]] = {project_id: [] for project_id in project_ids}
    users_by_id: dict[str, User] = {}
    for project_id, member in rows:
        collaborators[project_id].append(member)
        users_by_id[member.id] = member

    missing_owner_ids = {
        project.owner_id
        for project in projects
        if project.owner_id and project.owner_id not in users_by_id
    }
    if missing_owner_ids:
        owners = await session.scalars(select(User).where(User.id.in_(missing_owner_ids)))
        users_by_id.update({owner.id: owner for owner in owners})
    return {
        project.id: (users_by_id.get(project.owner_id), collaborators[project.id])
        for project in projects
    }


def serialize_project(
    project: Project,
    owner: User | None,
    collaborators: list[User],
    current_user_access: str = "viewer",
    revision_number: int = 0,
) -> ProjectType:
    return ProjectType(
        id=strawberry.ID(project.id),
        title=project.title,
        description=project.description or "",
        status=project.status or "active",
        visibility=project.visibility or "workspace",
        approval_status=project.approval_status or "draft",
        current_user_access=current_user_access,
        revision_number=revision_number,
        document_revision=project.revision or 0,
        owner=project_member_type(owner) if owner else None,
        collaborators=[project_member_type(member) for member in collaborators],
        profile=project_profile_type(project.profile),
        source_text=project.source_text,
        graph=serialize_graph(project.graph),
        created_at=as_utc(project.created_at),
        updated_at=as_utc(project.updated_at),
    )


def project_profile_type(value: dict | None) -> ProjectProfileType:
    profile = ProjectProfile.model_validate(value or {})
    return ProjectProfileType(
        key=profile.key,
        sponsor_id=strawberry.ID(profile.sponsor_id) if profile.sponsor_id else None,
        department=profile.department,
        team=profile.team,
        program=profile.program,
        priority=profile.priority,
        health=profile.health,
        start_date=profile.start_date,
        target_date=profile.target_date,
        progress=profile.progress,
        classification=profile.classification,
        tags=profile.tags,
        template=profile.template,
    )


def graph_input_to_dict(graph: FlowchartGraphInput) -> dict:
    return {
        "title": graph.title,
        "nodes": [
            {
                "id": str(node.id),
                "label": node.label,
                "type": node.type,
                "owner": node.owner,
                "description": node.description,
                "color": node.color,
                "shape": node.shape,
                "symbol": node.symbol,
                "width": node.width,
                "height": node.height,
                "backup_owner": node.backup_owner,
                "system": node.system,
                "vendor": node.vendor,
                "control_id": node.control_id,
                "policy_reference": node.policy_reference,
                "evidence_requirement": node.evidence_requirement,
                "segregation_rule": node.segregation_rule,
                "risk_level": node.risk_level,
                "data_classification": node.data_classification,
                "sla_minutes": node.sla_minutes,
                "review_date": node.review_date,
                "required": node.required,
                "layer": node.layer,
                "parent_id": str(node.parent_id) if node.parent_id else None,
                "x": node.x,
                "y": node.y,
            }
            for node in graph.nodes
        ],
        "edges": [
            {
                "source": str(edge.source),
                "target": str(edge.target),
                "label": edge.label,
                "is_loop": edge.is_loop,
                "bidirectional": edge.bidirectional,
            }
            for edge in graph.edges
        ],
        "questions": graph.questions,
        "warnings": [
            {
                "code": warning.code,
                "message": warning.message,
                "node_ids": [str(node_id) for node_id in warning.node_ids],
            }
            for warning in graph.warnings
        ],
    }


def validate_project_input(input: ProjectInput) -> ProjectWrite:
    try:
        return ProjectWrite.model_validate(
            {
                "title": input.title,
                "source_text": input.source_text,
                "graph": graph_input_to_dict(input.graph),
                "description": input.description,
                "status": input.status,
                "owner_id": str(input.owner_id) if input.owner_id else None,
                "collaborator_ids": [str(user_id) for user_id in input.collaborator_ids],
                "profile": input.profile,
            }
        )
    except ValidationError as error:
        raise GraphQLError(
            "Invalid project graph",
            extensions={"code": "BAD_USER_INPUT", "fieldCount": error.error_count()},
        ) from error


async def validate_project_people(
    info: GraphQLInfo,
    validated: ProjectWrite,
    fallback_owner_id: str,
) -> tuple[str, list[str]]:
    owner_id = validated.owner_id or fallback_owner_id
    collaborator_ids = list(dict.fromkeys([*validated.collaborator_ids, owner_id]))
    if len(collaborator_ids) > 50:
        raise GraphQLError(
            "A project can have at most 50 collaborators",
            extensions={"code": "BAD_USER_INPUT"},
        )
    members = list(
        await info.context.session.scalars(
            select(User).where(
                User.id.in_(collaborator_ids),
                User.entity_id == info.context.user.entity_id,
            )
        )
    )
    if len(members) != len(collaborator_ids):
        raise GraphQLError(
            "Project owners and collaborators must belong to this workspace",
            extensions={"code": "BAD_USER_INPUT"},
        )
    if validated.profile.sponsor_id:
        sponsor = await info.context.session.get(User, validated.profile.sponsor_id)
        if not sponsor or sponsor.entity_id != info.context.user.entity_id:
            raise GraphQLError(
                "Project sponsor must belong to this workspace",
                extensions={"code": "BAD_USER_INPUT"},
            )
    return owner_id, collaborator_ids


async def replace_project_collaborators(
    session: AsyncSession,
    project_id: str,
    collaborator_ids: list[str],
) -> None:
    existing_rows = list(
        await session.scalars(
            select(ProjectCollaborator).where(
                ProjectCollaborator.project_id == project_id
            )
        )
    )
    existing_roles = {row.user_id: row.access_role for row in existing_rows}
    users = list(await session.scalars(select(User).where(User.id.in_(collaborator_ids))))
    users_by_id = {user.id: user for user in users}
    await session.execute(
        delete(ProjectCollaborator).where(ProjectCollaborator.project_id == project_id)
    )
    session.add_all(
        ProjectCollaborator(
            project_id=project_id,
            user_id=user_id,
            access_role=existing_roles.get(
                user_id,
                default_project_role(users_by_id[user_id]),
            ),
        )
        for user_id in collaborator_ids
    )


def require_admin(info: GraphQLInfo) -> None:
    if info.context.user.role != "admin":
        raise GraphQLError(
            "Administrator privileges are required",
            extensions={"code": "FORBIDDEN"},
        )


def validated_role(role: str) -> str:
    normalized = role.strip().lower()
    if normalized not in {"admin", "basic", "guest"}:
        raise GraphQLError(
            "Role must be admin, basic, or guest",
            extensions={"code": "BAD_USER_INPUT"},
        )
    return normalized


def normalized_email(email: str) -> str:
    normalized = email.strip().lower()
    if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
        raise GraphQLError("Enter a valid email address", extensions={"code": "BAD_USER_INPUT"})
    return normalized


def normalized_job_title(job_title: str | None) -> str | None:
    normalized = job_title.strip() if job_title else ""
    if len(normalized) > 120:
        raise GraphQLError(
            "Job title must be at most 120 characters",
            extensions={"code": "BAD_USER_INPUT"},
        )
    return normalized or None


async def entity_project(info: GraphQLInfo, project_id: str) -> Project:
    project = await info.context.session.get(Project, project_id)
    if (
        not project
        or project.entity_id != info.context.user.entity_id
        or not await project_access_role(info.context.session, project, info.context.user)
    ):
        raise GraphQLError("Project not found", extensions={"code": "NOT_FOUND"})
    return project


async def serialize_project_for_user(info: GraphQLInfo, project: Project) -> ProjectType:
    people = await load_project_people(info.context.session, [project])
    access = await project_access_role(info.context.session, project, info.context.user)
    revision = await latest_revision(info.context.session, project.id)
    return serialize_project(
        project,
        *people[project.id],
        current_user_access=access or "viewer",
        revision_number=revision.version if revision else 0,
    )


def invitation_type(invitation: Invitation, setup_url: str | None = None) -> WorkspaceInvitationType:
    return WorkspaceInvitationType(
        id=strawberry.ID(invitation.id),
        display_name=invitation.display_name,
        email=invitation.email,
        job_title=invitation.job_title,
        role=invitation.role,
        status=invitation.status,
        delivery_status=invitation.delivery_status,
        expires_at=as_utc(invitation.expires_at),
        created_at=as_utc(invitation.created_at),
        setup_url=setup_url,
    )


def communication_user_type(user: User) -> CommunicationUserType:
    summary = user_summary(user)
    return CommunicationUserType(
        id=strawberry.ID(user.id),
        display_name=user.display_name,
        email=user.email,
        role=user.role,
        handle=summary["handle"],
        color=summary["color"],
    )


def message_reaction_types(message: DirectMessage | CommunicationChannelMessage, user_id: str) -> list[MessageReactionType]:
    return [
        MessageReactionType(
            emoji=emoji,
            count=len(user_ids),
            reacted_by_me=user_id in user_ids,
        )
        for emoji, user_ids in sorted((message.reactions or {}).items())
        if isinstance(user_ids, list) and user_ids
    ]


def message_attachment_types(message: DirectMessage | CommunicationChannelMessage) -> list[MessageAttachmentType]:
    return [
        MessageAttachmentType(name=str(item.get("name") or "Attachment"), url=str(item.get("url") or ""))
        for item in (message.attachments or [])
        if isinstance(item, dict) and item.get("url")
    ]


def direct_message_type(
    message: DirectMessage,
    sender: User,
    recipient: User,
    current_user_id: str | None = None,
) -> DirectMessageType:
    viewer_id = current_user_id or sender.id
    return DirectMessageType(
        id=strawberry.ID(message.id),
        body="" if message.deleted_at else message.body,
        read=message.read_at is not None,
        created_at=as_utc(message.created_at),
        parent_id=strawberry.ID(message.parent_id) if message.parent_id else None,
        reactions=message_reaction_types(message, viewer_id),
        pinned=message.pinned,
        bookmarked=viewer_id in (message.bookmark_user_ids or []),
        attachments=message_attachment_types(message),
        edited_at=as_utc(message.edited_at) if message.edited_at else None,
        deleted_at=as_utc(message.deleted_at) if message.deleted_at else None,
        can_edit=message.sender_id == viewer_id and message.deleted_at is None,
        sender=communication_user_type(sender),
        recipient=communication_user_type(recipient),
    )


def channel_message_type(
    message: CommunicationChannelMessage,
    sender: User,
    current_user_id: str | None = None,
) -> ChannelMessageType:
    viewer_id = current_user_id or sender.id
    return ChannelMessageType(
        id=strawberry.ID(message.id),
        channel_id=strawberry.ID(message.channel_id),
        body="" if message.deleted_at else message.body,
        created_at=as_utc(message.created_at),
        parent_id=strawberry.ID(message.parent_id) if message.parent_id else None,
        reactions=message_reaction_types(message, viewer_id),
        pinned=message.pinned,
        bookmarked=viewer_id in (message.bookmark_user_ids or []),
        attachments=message_attachment_types(message),
        edited_at=as_utc(message.edited_at) if message.edited_at else None,
        deleted_at=as_utc(message.deleted_at) if message.deleted_at else None,
        can_edit=message.sender_id == viewer_id and message.deleted_at is None,
        sender=communication_user_type(sender),
    )


def normalize_message_attachments(items: list[MessageAttachmentInput]) -> list[dict[str, str]]:
    if len(items) > 5:
        raise GraphQLError("Messages support at most five attachments", extensions={"code": "BAD_USER_INPUT"})
    attachments: list[dict[str, str]] = []
    for item in items:
        name = " ".join(item.name.strip().split())[:160]
        url = item.url.strip()
        parsed = urlparse(url)
        if not name or parsed.scheme not in {"http", "https"} or not parsed.netloc or len(url) > 2_000:
            raise GraphQLError("Attachment links must have a name and a valid HTTP(S) URL", extensions={"code": "BAD_USER_INPUT"})
        attachments.append({"name": name, "url": url})
    return attachments


def communication_channel_type(
    channel: CommunicationChannel,
    members: list[User],
    latest: CommunicationChannelMessage | None,
    unread_count: int,
    current_user: User,
) -> CommunicationChannelType:
    return CommunicationChannelType(
        id=strawberry.ID(channel.id),
        name=channel.name,
        description=channel.description or "",
        channel_type=channel.channel_type,
        visibility=channel.visibility,
        unread_count=unread_count,
        latest_message=latest.body if latest else None,
        latest_message_at=as_utc(latest.created_at) if latest else None,
        member_count=len(members),
        members=[communication_user_type(member) for member in members],
        created_by_id=strawberry.ID(channel.created_by_id),
        can_manage=current_user.role == "admin" or channel.created_by_id == current_user.id,
    )


def normalized_channel_name(value: str) -> str:
    name = " ".join(value.strip().split())
    if len(name) < 2 or len(name) > 80:
        raise GraphQLError(
            "Channel names must be between 2 and 80 characters",
            extensions={"code": "BAD_USER_INPUT"},
        )
    return name


def normalized_calendar_event(input: CalendarEventInput) -> dict:
    title = " ".join(input.title.strip().split())
    description = input.description.strip()
    location = " ".join(input.location.strip().split())
    meeting_url = input.meeting_url.strip()
    event_type = input.event_type.strip().lower()
    timezone_name = input.timezone.strip() or "UTC"
    if not title or len(title) > 160:
        raise GraphQLError("Event titles must be between 1 and 160 characters", extensions={"code": "BAD_USER_INPUT"})
    if len(description) > 2_000:
        raise GraphQLError("Event descriptions must be at most 2,000 characters", extensions={"code": "BAD_USER_INPUT"})
    if len(location) > 240:
        raise GraphQLError("Event locations must be at most 240 characters", extensions={"code": "BAD_USER_INPUT"})
    if event_type not in {"personal", "meeting"}:
        raise GraphQLError("Event type must be personal or meeting", extensions={"code": "BAD_USER_INPUT"})
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as error:
        raise GraphQLError("Event timezone is invalid", extensions={"code": "BAD_USER_INPUT"}) from error
    if meeting_url:
        parsed_url = urlparse(meeting_url)
        if len(meeting_url) > 500 or parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise GraphQLError("Meeting link must be a valid HTTP or HTTPS URL", extensions={"code": "BAD_USER_INPUT"})
    starts_at = as_utc(input.starts_at)
    ends_at = as_utc(input.ends_at)
    duration = ends_at - starts_at
    if duration <= timedelta(0) or duration > timedelta(days=31):
        raise GraphQLError("Events must end after they start and last no more than 31 days", extensions={"code": "BAD_USER_INPUT"})
    attendee_ids = {str(attendee_id) for attendee_id in input.attendee_ids}
    external_attendee_emails = {normalized_email(email) for email in input.external_attendee_emails}
    if any(len(email) > 320 for email in external_attendee_emails):
        raise GraphQLError("Email addresses must be at most 320 characters", extensions={"code": "BAD_USER_INPUT"})
    if len(attendee_ids) + len(external_attendee_emails) > 100:
        raise GraphQLError("Meetings support at most 100 attendees", extensions={"code": "BAD_USER_INPUT"})
    if input.reminder_minutes not in REMINDER_MINUTES:
        raise GraphQLError(
            "Reminder must be off, at the start time, or 5 minutes to 1 day before the event",
            extensions={"code": "BAD_USER_INPUT"},
        )
    recurrence_frequency = input.recurrence_frequency.strip().lower() or "none"
    if recurrence_frequency not in {"none", "daily", "weekdays", "weekly", "monthly"}:
        raise GraphQLError(
            "Repeat frequency must be daily, weekdays, weekly, monthly, or none",
            extensions={"code": "BAD_USER_INPUT"},
        )
    recurrence_interval = input.recurrence_interval
    recurrence_ends_at = input.recurrence_ends_at
    recurrence_count = input.recurrence_count
    if recurrence_frequency == "none":
        recurrence_interval = 1
        recurrence_ends_at = None
        recurrence_count = None
    else:
        if recurrence_interval < 1 or recurrence_interval > 30:
            raise GraphQLError(
                "Repeat interval must be between 1 and 30",
                extensions={"code": "BAD_USER_INPUT"},
            )
        if (recurrence_count is None) == (recurrence_ends_at is None):
            raise GraphQLError(
                "Recurring events must end after a number of occurrences or on a date",
                extensions={"code": "BAD_USER_INPUT"},
            )
        if recurrence_count is not None and not 2 <= recurrence_count <= 100:
            raise GraphQLError(
                "Recurring events must contain between 2 and 100 occurrences",
                extensions={"code": "BAD_USER_INPUT"},
            )
        local_start_date = starts_at.astimezone(ZoneInfo(timezone_name)).date()
        if recurrence_ends_at is not None and (
            recurrence_ends_at <= local_start_date
            or recurrence_ends_at > local_start_date + timedelta(days=370)
        ):
            raise GraphQLError(
                "Repeat end date must be after the first event and within one year",
                extensions={"code": "BAD_USER_INPUT"},
            )
    return {
        "title": title,
        "description": description,
        "event_type": event_type,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "timezone": timezone_name,
        "all_day": input.all_day,
        "location": location,
        "meeting_url": meeting_url,
        "reminder_minutes": input.reminder_minutes,
        "recurrence_frequency": recurrence_frequency,
        "recurrence_interval": recurrence_interval,
        "recurrence_ends_at": recurrence_ends_at,
        "recurrence_count": recurrence_count,
        "attendee_ids": attendee_ids,
        "external_attendee_emails": external_attendee_emails,
    }


def recurring_local_start(
    first_start: datetime,
    frequency: str,
    interval: int,
    occurrence_index: int,
) -> datetime:
    if frequency == "daily":
        return first_start + timedelta(days=interval * occurrence_index)
    if frequency == "weekly":
        return first_start + timedelta(weeks=interval * occurrence_index)
    if frequency == "weekdays":
        result = first_start
        weekdays_to_add = interval * occurrence_index
        while weekdays_to_add:
            result += timedelta(days=1)
            if result.weekday() < 5:
                weekdays_to_add -= 1
        return result
    if frequency == "monthly":
        month_offset = interval * occurrence_index
        absolute_month = first_start.year * 12 + first_start.month - 1 + month_offset
        year, zero_based_month = divmod(absolute_month, 12)
        month = zero_based_month + 1
        day = min(first_start.day, monthrange(year, month)[1])
        return first_start.replace(year=year, month=month, day=day)
    return first_start


def calendar_occurrence_times(values: dict) -> list[tuple[datetime, datetime]]:
    frequency = values["recurrence_frequency"]
    if frequency == "none":
        return [(values["starts_at"], values["ends_at"])]
    timezone_value = ZoneInfo(values["timezone"])
    first_start = values["starts_at"].astimezone(timezone_value)
    first_end = values["ends_at"].astimezone(timezone_value)
    duration = first_end - first_start
    count = values["recurrence_count"]
    requested_end = values["recurrence_ends_at"]
    occurrences: list[tuple[datetime, datetime]] = []
    for occurrence_index in range(100):
        local_start = recurring_local_start(
            first_start, frequency, values["recurrence_interval"], occurrence_index,
        )
        if requested_end is not None and local_start.date() > requested_end:
            break
        occurrences.append((
            local_start.astimezone(timezone.utc),
            (local_start + duration).astimezone(timezone.utc),
        ))
        if count is not None and len(occurrences) >= count:
            break
    if requested_end is not None:
        next_start = recurring_local_start(
            first_start, frequency, values["recurrence_interval"], len(occurrences),
        )
        if len(occurrences) == 100 and next_start.date() <= requested_end:
            raise GraphQLError(
                "This repeat schedule exceeds 100 occurrences; choose an earlier end date or a larger interval",
                extensions={"code": "BAD_USER_INPUT"},
            )
    if len(occurrences) < 2:
        raise GraphQLError(
            "The repeat schedule must create at least two occurrences",
            extensions={"code": "BAD_USER_INPUT"},
        )
    return occurrences


async def validated_calendar_attendees(
    info: GraphQLInfo,
    attendee_ids: set[str],
    external_attendee_emails: set[str],
) -> list[User]:
    users = list(await info.context.session.scalars(
        select(User).where(
            User.entity_id == info.context.user.entity_id,
            User.id.in_(attendee_ids),
        )
    )) if attendee_ids else []
    if len(users) != len(attendee_ids):
        raise GraphQLError("Every workspace attendee must belong to this workspace", extensions={"code": "BAD_USER_INPUT"})
    if external_attendee_emails:
        workspace_emails = set(await info.context.session.scalars(
            select(User.email).where(
                User.entity_id == info.context.user.entity_id,
                User.email.in_(external_attendee_emails),
            )
        ))
        if workspace_emails:
            raise GraphQLError(
                "Workspace members must be selected from contacts instead of added as external guests",
                extensions={"code": "BAD_USER_INPUT"},
            )
    return users


def new_meeting_email_job(
    info: GraphQLInfo,
    event: CalendarEvent,
    attendee: CalendarEventExternalAttendee,
    action: str,
) -> object:
    attendee.delivery_status = "queued"
    attendee.updated_at = datetime.now(timezone.utc)
    return new_background_job(
        entity_id=event.entity_id,
        created_by_id=info.context.user.id,
        kind=MEETING_EMAIL_JOB,
        payload={
            "external_attendee_id": attendee.id,
            "recipient_email": attendee.email,
            "organizer_name": info.context.user.display_name,
            "title": event.title,
            "starts_at": as_utc(event.starts_at).isoformat(),
            "ends_at": as_utc(event.ends_at).isoformat(),
            "timezone_name": event.timezone,
            "action": action,
            "description": event.description or "",
            "location": event.location or "",
            "meeting_url": event.meeting_url or "",
            "recurrence": calendar_recurrence_summary(event),
        },
        settings=info.context.settings,
    )


def calendar_recurrence_summary(event: CalendarEvent) -> str:
    if not event.series_id or not event.recurrence_frequency:
        return ""
    interval = event.recurrence_interval or 1
    local_start = as_utc(event.starts_at).astimezone(ZoneInfo(event.timezone or "UTC"))
    if event.recurrence_frequency == "daily":
        schedule = "Every day" if interval == 1 else f"Every {interval} days"
    elif event.recurrence_frequency == "weekdays":
        schedule = "Every weekday" if interval == 1 else f"Every {interval} weekdays"
    elif event.recurrence_frequency == "weekly":
        schedule = (
            f"Every week on {local_start.strftime('%A')}"
            if interval == 1 else f"Every {interval} weeks on {local_start.strftime('%A')}"
        )
    else:
        schedule = (
            f"Every month on day {local_start.day}"
            if interval == 1 else f"Every {interval} months on day {local_start.day}"
        )
    return f"{schedule}; {event.recurrence_count} occurrences; ends {event.recurrence_ends_at}"


def normalized_calendar_availability(input: CalendarAvailabilityInput) -> dict:
    range_start = as_utc(input.starts_after).astimezone(timezone.utc)
    range_end = as_utc(input.starts_before).astimezone(timezone.utc)
    if range_end <= range_start or range_end - range_start > timedelta(days=31):
        raise GraphQLError(
            "Availability ranges must be positive and no longer than 31 days",
            extensions={"code": "BAD_USER_INPUT"},
        )
    user_ids = list(dict.fromkeys(str(user_id) for user_id in input.user_ids))
    if not user_ids or len(user_ids) > 100:
        raise GraphQLError(
            "Availability requires between 1 and 100 workspace members",
            extensions={"code": "BAD_USER_INPUT"},
        )
    timezone_name = input.timezone.strip() or "UTC"
    try:
        timezone_value = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as error:
        raise GraphQLError("Availability timezone is invalid", extensions={"code": "BAD_USER_INPUT"}) from error
    try:
        workday_start = datetime_time.fromisoformat(input.workday_starts_at.strip())
        workday_end = datetime_time.fromisoformat(input.workday_ends_at.strip())
    except ValueError as error:
        raise GraphQLError(
            "Working hours must use HH:MM time values",
            extensions={"code": "BAD_USER_INPUT"},
        ) from error
    if workday_start >= workday_end:
        raise GraphQLError("Working hours must end after they start", extensions={"code": "BAD_USER_INPUT"})
    if input.duration_minutes < 15 or input.duration_minutes > 480 or input.duration_minutes % 15:
        raise GraphQLError(
            "Meeting duration must be 15 to 480 minutes in 15-minute increments",
            extensions={"code": "BAD_USER_INPUT"},
        )
    if input.interval_minutes not in {15, 30, 60}:
        raise GraphQLError("Suggestion intervals must be 15, 30, or 60 minutes", extensions={"code": "BAD_USER_INPUT"})
    return {
        "range_start": range_start,
        "range_end": range_end,
        "user_ids": user_ids,
        "timezone_name": timezone_name,
        "timezone": timezone_value,
        "duration_minutes": input.duration_minutes,
        "workday_start": workday_start,
        "workday_end": workday_end,
        "interval_minutes": input.interval_minutes,
        "include_weekends": input.include_weekends,
        "max_suggestions": min(30, max(1, input.max_suggestions)),
    }


def merge_busy_blocks(blocks: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    merged: list[tuple[datetime, datetime]] = []
    for starts_at, ends_at in sorted(blocks, key=lambda block: block[0]):
        if not merged or starts_at > merged[-1][1]:
            merged.append((starts_at, ends_at))
            continue
        merged[-1] = (merged[-1][0], max(merged[-1][1], ends_at))
    return merged


def meeting_time_suggestions(
    values: dict,
    busy_by_user: dict[str, list[tuple[datetime, datetime]]],
) -> list[MeetingTimeSuggestionType]:
    selected_ids = values["user_ids"]
    timezone_value = values["timezone"]
    local_start = values["range_start"].astimezone(timezone_value)
    local_end = values["range_end"].astimezone(timezone_value)
    day = local_start.date()
    final_day = local_end.date()
    candidates: list[MeetingTimeSuggestionType] = []
    duration = timedelta(minutes=values["duration_minutes"])
    interval = timedelta(minutes=values["interval_minutes"])
    while day <= final_day:
        if values["include_weekends"] or day.weekday() < 5:
            candidate = datetime.combine(day, values["workday_start"], tzinfo=timezone_value)
            workday_end = datetime.combine(day, values["workday_end"], tzinfo=timezone_value)
            while candidate + duration <= workday_end:
                candidate_end = candidate + duration
                candidate_utc = candidate.astimezone(timezone.utc)
                candidate_end_utc = candidate_end.astimezone(timezone.utc)
                if candidate_utc >= values["range_start"] and candidate_end_utc <= values["range_end"]:
                    unavailable = [user_id for user_id in selected_ids if any(
                        starts_at < candidate_end_utc and ends_at > candidate_utc
                        for starts_at, ends_at in busy_by_user.get(user_id, [])
                    )]
                    available = [user_id for user_id in selected_ids if user_id not in unavailable]
                    if available:
                        candidates.append(MeetingTimeSuggestionType(
                            starts_at=candidate_utc,
                            ends_at=candidate_end_utc,
                            available_user_ids=[strawberry.ID(user_id) for user_id in available],
                            unavailable_user_ids=[strawberry.ID(user_id) for user_id in unavailable],
                            attendance_count=len(available),
                            total_count=len(selected_ids),
                            score=round((len(available) / len(selected_ids)) * 100),
                        ))
                candidate += interval
        day += timedelta(days=1)
    candidates.sort(key=lambda item: (-item.attendance_count, item.starts_at))
    return candidates[:values["max_suggestions"]]


async def accessible_calendar_event(info: GraphQLInfo, event_id: str) -> CalendarEvent:
    event = await info.context.session.get(CalendarEvent, event_id)
    if not event or event.entity_id != info.context.user.entity_id:
        raise GraphQLError("Calendar event not found", extensions={"code": "NOT_FOUND"})
    membership = await info.context.session.scalar(
        select(CalendarEventAttendee.id).where(
            CalendarEventAttendee.event_id == event.id,
            CalendarEventAttendee.user_id == info.context.user.id,
        )
    )
    if not membership:
        raise GraphQLError("Calendar event not found", extensions={"code": "NOT_FOUND"})
    await enforce_calendar_policy(info, action="read", event=event)
    return event


async def calendar_event_types(
    info: GraphQLInfo,
    events: list[CalendarEvent],
) -> list[CalendarEventType]:
    if not events:
        return []
    event_ids = [event.id for event in events]
    rows = (await info.context.session.execute(
        select(CalendarEventAttendee, User)
        .join(User, User.id == CalendarEventAttendee.user_id)
        .where(CalendarEventAttendee.event_id.in_(event_ids))
        .order_by(User.display_name)
    )).all()
    attendees_by_event: dict[str, list[tuple[CalendarEventAttendee, User]]] = {}
    for membership, user in rows:
        attendees_by_event.setdefault(membership.event_id, []).append((membership, user))
    external_rows = list(await info.context.session.scalars(
        select(CalendarEventExternalAttendee)
        .where(
            CalendarEventExternalAttendee.event_id.in_(event_ids),
            CalendarEventExternalAttendee.status == "active",
        )
        .order_by(CalendarEventExternalAttendee.email)
    ))
    external_by_event: dict[str, list[CalendarEventExternalAttendee]] = {}
    for attendee in external_rows:
        external_by_event.setdefault(attendee.event_id, []).append(attendee)
    payload = []
    for event in events:
        event_attendees = attendees_by_event.get(event.id, [])
        users_by_id = {user.id: user for _, user in event_attendees}
        organizer = users_by_id.get(event.organizer_id)
        current_membership = next(
            (membership for membership, user in event_attendees if user.id == info.context.user.id),
            None,
        )
        if not organizer or not current_membership:
            continue
        payload.append(CalendarEventType(
            id=strawberry.ID(event.id),
            title=event.title,
            description=event.description or "",
            event_type=event.event_type,
            starts_at=as_utc(event.starts_at),
            ends_at=as_utc(event.ends_at),
            timezone=event.timezone or "UTC",
            all_day=event.all_day,
            location=event.location or "",
            meeting_url=event.meeting_url or "",
            status=event.status,
            series_id=strawberry.ID(event.series_id) if event.series_id else None,
            recurrence_frequency=event.recurrence_frequency,
            recurrence_interval=event.recurrence_interval or 1,
            recurrence_ends_at=event.recurrence_ends_at,
            recurrence_count=event.recurrence_count,
            occurrence_index=event.occurrence_index or 0,
            organizer=communication_user_type(organizer),
            attendees=[CalendarAttendeeType(
                user=communication_user_type(user),
                response=membership.response,
                is_organizer=user.id == event.organizer_id,
            ) for membership, user in event_attendees],
            external_attendees=[CalendarExternalAttendeeType(
                email=attendee.email,
                response=attendee.response,
                delivery_status=attendee.delivery_status,
            ) for attendee in external_by_event.get(event.id, [])],
            my_response=current_membership.response,
            reminder_minutes=current_membership.reminder_minutes,
            can_manage=event.organizer_id == info.context.user.id,
            created_at=as_utc(event.created_at),
            updated_at=as_utc(event.updated_at),
        ))
    return payload


def notification_type(
    notification: Notification,
    actor: User | None,
) -> NotificationType:
    return NotificationType(
        id=strawberry.ID(notification.id),
        kind=notification.kind,
        title=notification.title,
        body=notification.body,
        project_id=strawberry.ID(notification.project_id) if notification.project_id else None,
        contact_id=strawberry.ID(notification.contact_id) if notification.contact_id else None,
        calendar_event_id=(
            strawberry.ID(notification.calendar_event_id)
            if notification.calendar_event_id else None
        ),
        work_item_id=strawberry.ID(notification.work_item_id) if notification.work_item_id else None,
        communication_channel_id=(
            strawberry.ID(notification.communication_channel_id)
            if notification.communication_channel_id else None
        ),
        communication_message_id=(
            strawberry.ID(notification.communication_message_id)
            if notification.communication_message_id else None
        ),
        document_id=strawberry.ID(notification.document_id) if notification.document_id else None,
        group_key=notification.group_key,
        snoozed_until=as_utc(notification.snoozed_until) if notification.snoozed_until else None,
        read=notification.read_at is not None,
        created_at=as_utc(notification.created_at),
        actor=communication_user_type(actor) if actor else None,
    )


async def project_governance_type(
    info: GraphQLInfo,
    project: Project,
) -> ProjectGovernanceType:
    session = info.context.session
    access = await project_access_role(session, project, info.context.user)
    access_rows = (
        await session.execute(
            select(ProjectCollaborator, User)
            .join(User, User.id == ProjectCollaborator.user_id)
            .where(ProjectCollaborator.project_id == project.id)
            .order_by(User.display_name.asc())
        )
    ).all()
    revisions = list(
        await session.scalars(
            select(ProjectRevision)
            .where(ProjectRevision.project_id == project.id)
            .order_by(ProjectRevision.version.desc())
            .limit(25)
        )
    )
    approval = await session.scalar(
        select(ProjectApproval)
        .where(ProjectApproval.project_id == project.id)
        .order_by(ProjectApproval.requested_at.desc())
        .limit(1)
    )
    audit_events = list(
        await session.scalars(
            select(AuditEvent)
            .where(AuditEvent.project_id == project.id)
            .order_by(AuditEvent.created_at.desc())
            .limit(30)
        )
    )
    user_ids = {
        *[revision.created_by_id for revision in revisions],
        *[event.actor_id for event in audit_events if event.actor_id],
    }
    if approval:
        user_ids.add(approval.requested_by_id)
        if approval.reviewer_id:
            user_ids.add(approval.reviewer_id)
    users = list(await session.scalars(select(User).where(User.id.in_(user_ids)))) if user_ids else []
    users_by_id = {user.id: user for user in users}
    revisions_by_id = {revision.id: revision for revision in revisions}
    approval_type = None
    if approval:
        approval_revision = revisions_by_id.get(approval.revision_id) or await session.get(
            ProjectRevision, approval.revision_id
        )
        requester = users_by_id.get(approval.requested_by_id)
        if approval_revision and requester:
            approval_type = ProjectApprovalType(
                id=strawberry.ID(approval.id),
                revision_id=strawberry.ID(approval.revision_id),
                revision_version=approval_revision.version,
                status=approval.status,
                request_note=approval.request_note or "",
                decision_note=approval.decision_note or "",
                requested_by=project_member_type(requester),
                reviewer=(
                    project_member_type(users_by_id[approval.reviewer_id])
                    if approval.reviewer_id and approval.reviewer_id in users_by_id
                    else None
                ),
                requested_at=as_utc(approval.requested_at),
                decided_at=as_utc(approval.decided_at) if approval.decided_at else None,
            )
    return ProjectGovernanceType(
        project_id=strawberry.ID(project.id),
        visibility=project.visibility or "workspace",
        approval_status=project.approval_status or "draft",
        current_user_access=access or "viewer",
        current_revision=revisions[0].version if revisions else 0,
        access_entries=[
            ProjectAccessType(user=project_member_type(user), access_role=row.access_role)
            for row, user in access_rows
        ],
        revisions=[
            ProjectRevisionType(
                id=strawberry.ID(revision.id),
                version=revision.version,
                change_summary=revision.change_summary,
                created_by=project_member_type(users_by_id[revision.created_by_id]),
                created_at=as_utc(revision.created_at),
                title=revision.title,
                status=revision.status,
                node_count=len((revision.graph or {}).get("nodes", [])),
                edge_count=len((revision.graph or {}).get("edges", [])),
            )
            for revision in revisions
            if revision.created_by_id in users_by_id
        ],
        approval=approval_type,
        audit_events=[
            ProjectAuditEventType(
                id=strawberry.ID(event.id),
                action=event.action,
                actor=(
                    project_member_type(users_by_id[event.actor_id])
                    if event.actor_id and event.actor_id in users_by_id
                    else None
                ),
                details=event.details or {},
                created_at=as_utc(event.created_at),
            )
            for event in audit_events
        ],
    )


def project_access_filter(info: GraphQLInfo):
    base = Project.entity_id == info.context.user.entity_id
    if info.context.user.role == "admin":
        return base
    accessible_project_ids = select(ProjectCollaborator.project_id).where(
        ProjectCollaborator.user_id == info.context.user.id
    )
    group_project_ids = select(ProjectGroupAccess.project_id).join(
        OrganizationUnitMember, OrganizationUnitMember.unit_id == ProjectGroupAccess.unit_id
    ).where(OrganizationUnitMember.user_id == info.context.user.id)
    if info.context.user.role == "guest":
        return base & or_(Project.owner_id == info.context.user.id, Project.id.in_(accessible_project_ids), Project.id.in_(group_project_ids))
    return base & or_(
        Project.visibility == "workspace",
        Project.owner_id == info.context.user.id,
        Project.id.in_(accessible_project_ids),
        Project.id.in_(group_project_ids),
    )


def encode_project_cursor(project: Project) -> str:
    payload = json.dumps(
        [as_utc(project.updated_at).isoformat(), project.id],
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def decode_project_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        timestamp, project_id = json.loads(base64.urlsafe_b64decode(padded).decode())
        decoded_at = datetime.fromisoformat(timestamp)
        if decoded_at.tzinfo is None:
            decoded_at = decoded_at.replace(tzinfo=timezone.utc)
        if not isinstance(project_id, str) or not 1 <= len(project_id) <= 36:
            raise ValueError
        return decoded_at, project_id
    except (binascii.Error, UnicodeDecodeError, ValueError, TypeError) as error:
        raise GraphQLError(
            "Project cursor is invalid",
            extensions={"code": "BAD_USER_INPUT"},
        ) from error


async def project_summary_types(
    info: GraphQLInfo,
    projects: list[Project],
) -> list[ProjectSummaryType]:
    people = await load_project_people(info.context.session, projects)
    project_ids = [project.id for project in projects]
    task_rows = (
        await info.context.session.execute(
            select(
                ProjectTask.project_id,
                func.count(ProjectTask.id),
                func.sum(case((ProjectTask.status == "done", 1), else_=0)),
            )
            .where(ProjectTask.project_id.in_(project_ids))
            .group_by(ProjectTask.project_id)
        )
    ).all() if project_ids else []
    deliverable_rows = (
        await info.context.session.execute(
            select(
                ProjectDeliverable.project_id,
                func.count(ProjectDeliverable.id),
                func.sum(case((ProjectDeliverable.status == "done", 1), else_=0)),
            )
            .where(ProjectDeliverable.project_id.in_(project_ids))
            .group_by(ProjectDeliverable.project_id)
        )
    ).all() if project_ids else []
    task_stats = {
        project_id: (count or 0, complete or 0)
        for project_id, count, complete in task_rows
    }
    deliverable_stats = {
        project_id: (count or 0, complete or 0)
        for project_id, count, complete in deliverable_rows
    }
    user_access_rows = (
        await info.context.session.execute(
            select(ProjectCollaborator.project_id, ProjectCollaborator.access_role).where(
                ProjectCollaborator.project_id.in_(project_ids),
                ProjectCollaborator.user_id == info.context.user.id,
            )
        )
    ).all() if project_ids else []
    user_access = {project_id: role for project_id, role in user_access_rows}
    summaries = []
    for project in projects:
        task_total, task_complete = task_stats.get(project.id, (0, 0))
        deliverable_total, deliverable_complete = deliverable_stats.get(project.id, (0, 0))
        progress = (
            round((task_complete / task_total) * 100)
            if task_total
            else round((deliverable_complete / deliverable_total) * 100)
            if deliverable_total
            else 0
        )
        summaries.append(ProjectSummaryType(
            id=strawberry.ID(project.id),
            title=project.title,
            description=project.description or "",
            status=project.status or "active",
            visibility=project.visibility or "workspace",
            approval_status=project.approval_status or "draft",
            current_user_access=(
                "admin"
                if info.context.user.role == "admin"
                else "owner"
                if project.owner_id == info.context.user.id
                else user_access.get(project.id, "viewer")
            ),
            profile=project_profile_type(project.profile),
            owner=project_member_type(people[project.id][0]) if people[project.id][0] else None,
            collaborators=[
                project_member_type(member) for member in people[project.id][1]
            ],
            collaborator_count=len(people[project.id][1]),
            deliverable_count=deliverable_total,
            completed_deliverable_count=deliverable_complete,
            task_count=task_total,
            completed_task_count=task_complete,
            plan_progress=progress,
            created_at=as_utc(project.created_at),
            updated_at=as_utc(project.updated_at),
            node_count=len(project.graph.get("nodes", [])),
            edge_count=len(project.graph.get("edges", [])),
        ))
    return summaries


async def entity_communication_channel(
    info: GraphQLInfo,
    channel_id: str,
) -> CommunicationChannel:
    channel = await info.context.session.get(CommunicationChannel, channel_id)
    if not channel or channel.entity_id != info.context.user.entity_id:
        raise GraphQLError("Channel not found", extensions={"code": "NOT_FOUND"})
    if channel.visibility == "private":
        membership = await info.context.session.scalar(
            select(CommunicationChannelMember.id).where(
                CommunicationChannelMember.channel_id == channel.id,
                CommunicationChannelMember.user_id == info.context.user.id,
            )
        )
        if not membership:
            raise GraphQLError("Channel not found", extensions={"code": "NOT_FOUND"})
    return channel


async def channel_members(
    info: GraphQLInfo,
    channel: CommunicationChannel,
) -> list[User]:
    if channel.visibility == "workspace":
        return list(await info.context.session.scalars(
            select(User).where(User.entity_id == channel.entity_id).order_by(User.display_name)
        ))
    return list(await info.context.session.scalars(
        select(User)
        .join(CommunicationChannelMember, CommunicationChannelMember.user_id == User.id)
        .where(CommunicationChannelMember.channel_id == channel.id)
        .order_by(User.display_name)
    ))


async def accessible_chat_message(
    info: GraphQLInfo,
    message_kind: str,
    message_id: str,
) -> tuple[DirectMessage | CommunicationChannelMessage, list[User]]:
    if message_kind == "direct":
        message = await info.context.session.get(DirectMessage, message_id)
        if (
            not message
            or message.entity_id != info.context.user.entity_id
            or info.context.user.id not in {message.sender_id, message.recipient_id}
        ):
            raise GraphQLError("Message not found", extensions={"code": "NOT_FOUND"})
        users = list(await info.context.session.scalars(
            select(User).where(User.id.in_({message.sender_id, message.recipient_id}))
        ))
        return message, users
    if message_kind == "channel":
        message = await info.context.session.get(CommunicationChannelMessage, message_id)
        if not message or message.entity_id != info.context.user.entity_id:
            raise GraphQLError("Message not found", extensions={"code": "NOT_FOUND"})
        channel = await entity_communication_channel(info, message.channel_id)
        return message, await channel_members(info, channel)
    raise GraphQLError("Message type must be direct or channel", extensions={"code": "BAD_USER_INPUT"})


async def publish_chat_change(
    info: GraphQLInfo,
    message_kind: str,
    message: DirectMessage | CommunicationChannelMessage,
    viewers: list[User],
) -> None:
    event = {
        "type": "message_changed",
        "message_kind": message_kind,
        "message_id": message.id,
        "channel_id": message.channel_id if isinstance(message, CommunicationChannelMessage) else None,
        "actor": user_summary(info.context.user),
    }
    await asyncio.gather(*(
        communication_hub.publish(viewer.id, event)
        for viewer in viewers if viewer.id != info.context.user.id
    ))


@strawberry.type
class Query:
    @strawberry.field
    async def workspace(self, info: GraphQLInfo) -> WorkspaceType:
        entity = await info.context.session.get(Entity, info.context.user.entity_id)
        if not entity:
            raise GraphQLError("Workspace not found", extensions={"code": "NOT_FOUND"})
        member_count = await info.context.session.scalar(
            select(func.count(User.id)).where(User.entity_id == entity.id)
        )
        return WorkspaceType(
            id=strawberry.ID(entity.id),
            name=entity.name,
            member_count=member_count or 0,
        )

    @strawberry.field
    async def workspace_members(self, info: GraphQLInfo) -> list[WorkspaceMemberType]:
        require_admin(info)
        result = await info.context.session.scalars(
            select(User)
            .where(User.entity_id == info.context.user.entity_id)
            .order_by(User.display_name.asc())
        )
        return [
            WorkspaceMemberType(
                id=strawberry.ID(member.id),
                display_name=member.display_name,
                email=member.email,
                role=member.role,
                created_at=as_utc(member.created_at),
                is_current_user=member.id == info.context.user.id,
            )
            for member in result
        ]

    @strawberry.field
    async def workspace_invitations(self, info: GraphQLInfo) -> list[WorkspaceInvitationType]:
        require_admin(info)
        result = await info.context.session.scalars(
            select(Invitation)
            .where(
                Invitation.entity_id == info.context.user.entity_id,
                Invitation.status == "pending",
            )
            .order_by(Invitation.created_at.desc())
        )
        return [invitation_type(invitation) for invitation in result]

    @strawberry.field
    async def communication_contacts(
        self,
        info: GraphQLInfo,
    ) -> list[CommunicationContactType]:
        members = list(
            await info.context.session.scalars(
                select(User)
                .where(
                    User.entity_id == info.context.user.entity_id,
                    User.id != info.context.user.id,
                )
                .order_by(User.display_name.asc())
            )
        )
        contacts = []
        for member in members:
            unread_count = await info.context.session.scalar(
                select(func.count(DirectMessage.id)).where(
                    DirectMessage.sender_id == member.id,
                    DirectMessage.recipient_id == info.context.user.id,
                    DirectMessage.read_at.is_(None),
                )
            )
            latest = await info.context.session.scalar(
                select(DirectMessage)
                .where(
                    DirectMessage.entity_id == info.context.user.entity_id,
                    or_(
                        (DirectMessage.sender_id == info.context.user.id)
                        & (DirectMessage.recipient_id == member.id),
                        (DirectMessage.sender_id == member.id)
                        & (DirectMessage.recipient_id == info.context.user.id),
                    ),
                )
                .order_by(DirectMessage.created_at.desc())
                .limit(1)
            )
            contacts.append(
                CommunicationContactType(
                    user=communication_user_type(member),
                    unread_count=unread_count or 0,
                    latest_message=latest.body if latest else None,
                    latest_message_at=latest.created_at if latest else None,
                )
            )
        return contacts

    @strawberry.field
    async def direct_messages(
        self,
        info: GraphQLInfo,
        contact_id: strawberry.ID,
        limit: int = 100,
    ) -> list[DirectMessageType]:
        contact = await info.context.session.get(User, str(contact_id))
        if not contact or contact.entity_id != info.context.user.entity_id:
            raise GraphQLError("Contact not found", extensions={"code": "NOT_FOUND"})
        messages = list(
            await info.context.session.scalars(
                select(DirectMessage)
                .where(
                    DirectMessage.entity_id == info.context.user.entity_id,
                    or_(
                        (DirectMessage.sender_id == info.context.user.id)
                        & (DirectMessage.recipient_id == contact.id),
                        (DirectMessage.sender_id == contact.id)
                        & (DirectMessage.recipient_id == info.context.user.id),
                    ),
                )
                .order_by(DirectMessage.created_at.desc())
                .limit(min(200, max(1, limit)))
            )
        )
        users = {info.context.user.id: info.context.user, contact.id: contact}
        return [
            direct_message_type(
                message, users[message.sender_id], users[message.recipient_id], info.context.user.id
            )
            for message in reversed(messages)
        ]

    @strawberry.field
    async def communication_channels(
        self,
        info: GraphQLInfo,
    ) -> list[CommunicationChannelType]:
        member_channel_ids = select(CommunicationChannelMember.channel_id).where(
            CommunicationChannelMember.user_id == info.context.user.id
        )
        channels = list(await info.context.session.scalars(
            select(CommunicationChannel)
            .where(
                CommunicationChannel.entity_id == info.context.user.entity_id,
                or_(
                    CommunicationChannel.visibility == "workspace",
                    CommunicationChannel.id.in_(member_channel_ids),
                ),
            )
            .order_by(CommunicationChannel.updated_at.desc())
            .limit(200)
        ))
        if not channels:
            return []
        channel_ids = [channel.id for channel in channels]
        workspace_members = list(await info.context.session.scalars(
            select(User)
            .where(User.entity_id == info.context.user.entity_id)
            .order_by(User.display_name)
        ))
        private_rows = (await info.context.session.execute(
            select(CommunicationChannelMember.channel_id, User)
            .join(User, User.id == CommunicationChannelMember.user_id)
            .where(CommunicationChannelMember.channel_id.in_(channel_ids))
            .order_by(User.display_name)
        )).all()
        private_members: dict[str, list[User]] = {}
        for channel_id, member in private_rows:
            private_members.setdefault(channel_id, []).append(member)

        latest_times = (
            select(
                CommunicationChannelMessage.channel_id.label("channel_id"),
                func.max(CommunicationChannelMessage.created_at).label("created_at"),
            )
            .where(CommunicationChannelMessage.channel_id.in_(channel_ids))
            .group_by(CommunicationChannelMessage.channel_id)
            .subquery()
        )
        latest_rows = list(await info.context.session.scalars(
            select(CommunicationChannelMessage).join(
                latest_times,
                and_(
                    CommunicationChannelMessage.channel_id == latest_times.c.channel_id,
                    CommunicationChannelMessage.created_at == latest_times.c.created_at,
                ),
            )
        ))
        latest_by_channel = {message.channel_id: message for message in latest_rows}
        unread_rows = (await info.context.session.execute(
            select(CommunicationChannelMessage.channel_id, func.count(CommunicationChannelMessage.id))
            .outerjoin(
                CommunicationChannelMember,
                and_(
                    CommunicationChannelMember.channel_id == CommunicationChannelMessage.channel_id,
                    CommunicationChannelMember.user_id == info.context.user.id,
                ),
            )
            .where(
                CommunicationChannelMessage.channel_id.in_(channel_ids),
                CommunicationChannelMessage.sender_id != info.context.user.id,
                or_(
                    CommunicationChannelMember.last_read_at.is_(None),
                    CommunicationChannelMessage.created_at > CommunicationChannelMember.last_read_at,
                ),
            )
            .group_by(CommunicationChannelMessage.channel_id)
        )).all()
        unread_by_channel = {channel_id: count for channel_id, count in unread_rows}
        payload = [communication_channel_type(
            channel,
            workspace_members if channel.visibility == "workspace" else private_members.get(channel.id, []),
            latest_by_channel.get(channel.id),
            unread_by_channel.get(channel.id, 0),
            info.context.user,
        ) for channel in channels]
        return sorted(
            payload,
            key=lambda channel: channel.latest_message_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )

    @strawberry.field
    async def channel_messages(
        self,
        info: GraphQLInfo,
        channel_id: strawberry.ID,
        limit: int = 100,
    ) -> list[ChannelMessageType]:
        channel = await entity_communication_channel(info, str(channel_id))
        messages = list(await info.context.session.scalars(
            select(CommunicationChannelMessage)
            .where(CommunicationChannelMessage.channel_id == channel.id)
            .order_by(CommunicationChannelMessage.created_at.desc())
            .limit(min(200, max(1, limit)))
        ))
        sender_ids = {message.sender_id for message in messages}
        senders = {
            sender.id: sender for sender in await info.context.session.scalars(
                select(User).where(User.id.in_(sender_ids))
            )
        } if sender_ids else {}
        return [
            channel_message_type(message, senders[message.sender_id], info.context.user.id)
            for message in reversed(messages)
            if message.sender_id in senders
        ]

    @strawberry.field
    async def message_search(
        self,
        info: GraphQLInfo,
        term: str,
        limit: int = 50,
    ) -> list[MessageSearchResultType]:
        search_term = " ".join(term.strip().split())
        if len(search_term) < 2 or len(search_term) > 120:
            raise GraphQLError("Message search must be between 2 and 120 characters", extensions={"code": "BAD_USER_INPUT"})
        bounded_limit = min(100, max(1, limit))
        direct_rows = list(await info.context.session.scalars(
            select(DirectMessage)
            .where(
                DirectMessage.entity_id == info.context.user.entity_id,
                DirectMessage.deleted_at.is_(None),
                or_(
                    DirectMessage.sender_id == info.context.user.id,
                    DirectMessage.recipient_id == info.context.user.id,
                ),
                DirectMessage.body.ilike(f"%{search_term}%"),
            )
            .order_by(DirectMessage.created_at.desc())
            .limit(bounded_limit)
        ))
        member_channel_ids = select(CommunicationChannelMember.channel_id).where(
            CommunicationChannelMember.user_id == info.context.user.id
        )
        accessible_channels = list(await info.context.session.scalars(
            select(CommunicationChannel).where(
                CommunicationChannel.entity_id == info.context.user.entity_id,
                or_(
                    CommunicationChannel.visibility == "workspace",
                    CommunicationChannel.id.in_(member_channel_ids),
                ),
            )
        ))
        channels_by_id = {channel.id: channel for channel in accessible_channels}
        channel_rows = list(await info.context.session.scalars(
            select(CommunicationChannelMessage)
            .where(
                CommunicationChannelMessage.channel_id.in_(channels_by_id),
                CommunicationChannelMessage.deleted_at.is_(None),
                CommunicationChannelMessage.body.ilike(f"%{search_term}%"),
            )
            .order_by(CommunicationChannelMessage.created_at.desc())
            .limit(bounded_limit)
        )) if channels_by_id else []
        sender_ids = {
            item.sender_id for item in [*direct_rows, *channel_rows]
        } | {
            item.recipient_id if item.sender_id == info.context.user.id else item.sender_id
            for item in direct_rows
        }
        users = {
            user.id: user for user in await info.context.session.scalars(
                select(User).where(User.id.in_(sender_ids))
            )
        } if sender_ids else {}
        results: list[MessageSearchResultType] = []
        for message in direct_rows:
            contact_id = message.recipient_id if message.sender_id == info.context.user.id else message.sender_id
            sender = users.get(message.sender_id)
            contact = users.get(contact_id)
            if sender and contact:
                results.append(MessageSearchResultType(
                    kind="direct", context_id=strawberry.ID(contact_id), context_title=contact.display_name,
                    message_id=strawberry.ID(message.id), body=message.body,
                    created_at=as_utc(message.created_at), sender=communication_user_type(sender),
                ))
        for message in channel_rows:
            sender = users.get(message.sender_id)
            channel = channels_by_id.get(message.channel_id)
            if sender and channel:
                results.append(MessageSearchResultType(
                    kind="channel", context_id=strawberry.ID(channel.id), context_title=channel.name,
                    message_id=strawberry.ID(message.id), body=message.body,
                    created_at=as_utc(message.created_at), sender=communication_user_type(sender),
                ))
        return sorted(results, key=lambda item: item.created_at, reverse=True)[:bounded_limit]

    @strawberry.field
    async def calendar_events(
        self,
        info: GraphQLInfo,
        starts_after: datetime,
        starts_before: datetime,
    ) -> list[CalendarEventType]:
        range_start = as_utc(starts_after)
        range_end = as_utc(starts_before)
        if range_end <= range_start or range_end - range_start > timedelta(days=370):
            raise GraphQLError(
                "Calendar ranges must be positive and no longer than 370 days",
                extensions={"code": "BAD_USER_INPUT"},
            )
        accessible_event_ids = select(CalendarEventAttendee.event_id).where(
            CalendarEventAttendee.user_id == info.context.user.id
        )
        events = list(await info.context.session.scalars(
            select(CalendarEvent)
            .where(
                CalendarEvent.entity_id == info.context.user.entity_id,
                CalendarEvent.id.in_(accessible_event_ids),
                CalendarEvent.starts_at < range_end,
                CalendarEvent.ends_at > range_start,
            )
            .order_by(CalendarEvent.starts_at, CalendarEvent.id)
            .limit(2_000)
        ))
        snapshot = await load_policy_snapshot(info.context.session, info.context.user)
        permitted = []
        for event in events:
            decision = await evaluate_policy(info.context.session, info.context.user, PolicyContext(
                action="read", resource_type="meeting", resource_id=event.id,
                source_type="calendar", preauthorized=True,
            ), snapshot=snapshot)
            if decision.allowed:
                permitted.append(event)
        return await calendar_event_types(info, permitted)

    @strawberry.field
    async def calendar_availability(
        self,
        info: GraphQLInfo,
        input: CalendarAvailabilityInput,
    ) -> CalendarAvailabilityType:
        values = normalized_calendar_availability(input)
        users = list(await info.context.session.scalars(
            select(User)
            .where(
                User.entity_id == info.context.user.entity_id,
                User.id.in_(values["user_ids"]),
            )
            .order_by(User.display_name.asc(), User.id.asc())
        ))
        if len(users) != len(values["user_ids"]):
            raise GraphQLError(
                "Availability can only include members of your workspace",
                extensions={"code": "BAD_USER_INPUT"},
            )
        rows = (await info.context.session.execute(
            select(
                CalendarEventAttendee.user_id,
                CalendarEvent.starts_at,
                CalendarEvent.ends_at,
            )
            .join(CalendarEvent, CalendarEvent.id == CalendarEventAttendee.event_id)
            .where(
                CalendarEvent.entity_id == info.context.user.entity_id,
                CalendarEventAttendee.user_id.in_(values["user_ids"]),
                CalendarEventAttendee.response != "declined",
                CalendarEvent.status != "cancelled",
                CalendarEvent.starts_at < values["range_end"],
                CalendarEvent.ends_at > values["range_start"],
            )
            .order_by(CalendarEventAttendee.user_id, CalendarEvent.starts_at)
            .limit(50_001)
        )).all()
        if len(rows) > 50_000:
            raise GraphQLError(
                "This availability window contains too many calendar blocks; shorten the date range",
                extensions={"code": "BAD_USER_INPUT"},
            )
        raw_busy: dict[str, list[tuple[datetime, datetime]]] = {
            user_id: [] for user_id in values["user_ids"]
        }
        for user_id, starts_at, ends_at in rows:
            block_start = max(values["range_start"], as_utc(starts_at).astimezone(timezone.utc))
            block_end = min(values["range_end"], as_utc(ends_at).astimezone(timezone.utc))
            if block_end > block_start:
                raw_busy[user_id].append((block_start, block_end))
        busy_by_user = {
            user_id: merge_busy_blocks(blocks) for user_id, blocks in raw_busy.items()
        }
        return CalendarAvailabilityType(
            timezone=values["timezone_name"],
            range_start=values["range_start"],
            range_end=values["range_end"],
            users=[CalendarAvailabilityUserType(
                user=communication_user_type(user),
                busy=[CalendarBusyBlockType(starts_at=starts_at, ends_at=ends_at)
                      for starts_at, ends_at in busy_by_user[user.id]],
            ) for user in users],
            suggestions=meeting_time_suggestions(values, busy_by_user),
        )

    @strawberry.field
    async def calendar_event(
        self,
        info: GraphQLInfo,
        event_id: strawberry.ID,
    ) -> CalendarEventType:
        event = await accessible_calendar_event(info, str(event_id))
        return (await calendar_event_types(info, [event]))[0]

    @strawberry.field
    async def notifications(
        self,
        info: GraphQLInfo,
        limit: int = 50,
    ) -> list[NotificationType]:
        muted_kinds = set(await info.context.session.scalars(
            select(NotificationPreference.kind).where(
                NotificationPreference.user_id == info.context.user.id,
                or_(NotificationPreference.muted.is_(True), NotificationPreference.in_app.is_(False)),
            )
        ))
        now = datetime.now(timezone.utc)
        notifications = list(
            await info.context.session.scalars(
                select(Notification)
                .where(
                    Notification.user_id == info.context.user.id,
                    Notification.kind != "direct_message",
                    or_(Notification.snoozed_until.is_(None), Notification.snoozed_until <= now),
                    Notification.kind.not_in(muted_kinds) if muted_kinds else True,
                )
                .order_by(Notification.created_at.desc())
                .limit(min(100, max(1, limit)))
            )
        )
        actor_ids = {item.actor_id for item in notifications if item.actor_id}
        actors = {}
        if actor_ids:
            actor_rows = await info.context.session.scalars(
                select(User).where(User.id.in_(actor_ids))
            )
            actors = {actor.id: actor for actor in actor_rows}
        return [notification_type(item, actors.get(item.actor_id)) for item in notifications]

    @strawberry.field
    async def projects(self, info: GraphQLInfo) -> list[ProjectSummaryType]:
        access_filter = project_access_filter(info)
        projects = list(
            await info.context.session.scalars(
                select(Project)
                .where(access_filter)
                .order_by(Project.updated_at.desc())
                .limit(100)
            )
        )
        people = await load_project_people(info.context.session, projects)
        project_ids = [project.id for project in projects]
        task_rows = (
            await info.context.session.execute(
                select(
                    ProjectTask.project_id,
                    func.count(ProjectTask.id),
                    func.sum(case((ProjectTask.status == "done", 1), else_=0)),
                )
                .where(ProjectTask.project_id.in_(project_ids))
                .group_by(ProjectTask.project_id)
            )
        ).all() if project_ids else []
        deliverable_rows = (
            await info.context.session.execute(
                select(
                    ProjectDeliverable.project_id,
                    func.count(ProjectDeliverable.id),
                    func.sum(case((ProjectDeliverable.status == "done", 1), else_=0)),
                )
                .where(ProjectDeliverable.project_id.in_(project_ids))
                .group_by(ProjectDeliverable.project_id)
            )
        ).all() if project_ids else []
        task_stats = {project_id: (count or 0, complete or 0) for project_id, count, complete in task_rows}
        deliverable_stats = {
            project_id: (count or 0, complete or 0)
            for project_id, count, complete in deliverable_rows
        }
        user_access_rows = (
            await info.context.session.execute(
                select(ProjectCollaborator.project_id, ProjectCollaborator.access_role).where(
                    ProjectCollaborator.project_id.in_(project_ids),
                    ProjectCollaborator.user_id == info.context.user.id,
                )
            )
        ).all() if project_ids else []
        user_access = {project_id: role for project_id, role in user_access_rows}
        plan_progress = {}
        for project_id in project_ids:
            task_total, task_complete = task_stats.get(project_id, (0, 0))
            deliverable_total, deliverable_complete = deliverable_stats.get(project_id, (0, 0))
            if task_total:
                plan_progress[project_id] = round((task_complete / task_total) * 100)
            elif deliverable_total:
                plan_progress[project_id] = round(
                    (deliverable_complete / deliverable_total) * 100
                )
            else:
                plan_progress[project_id] = 0
        return [
            ProjectSummaryType(
                id=strawberry.ID(project.id),
                title=project.title,
                description=project.description or "",
                status=project.status or "active",
                visibility=project.visibility or "workspace",
                approval_status=project.approval_status or "draft",
                current_user_access=(
                    "admin"
                    if info.context.user.role == "admin"
                    else "owner"
                    if project.owner_id == info.context.user.id
                    else user_access.get(project.id, "viewer")
                ),
                profile=project_profile_type(project.profile),
                owner=project_member_type(people[project.id][0]) if people[project.id][0] else None,
                collaborators=[
                    project_member_type(member) for member in people[project.id][1]
                ],
                collaborator_count=len(people[project.id][1]),
                deliverable_count=deliverable_stats.get(project.id, (0, 0))[0],
                completed_deliverable_count=deliverable_stats.get(project.id, (0, 0))[1],
                task_count=task_stats.get(project.id, (0, 0))[0],
                completed_task_count=task_stats.get(project.id, (0, 0))[1],
                plan_progress=plan_progress[project.id],
                created_at=as_utc(project.created_at),
                updated_at=as_utc(project.updated_at),
                node_count=len(project.graph.get("nodes", [])),
                edge_count=len(project.graph.get("edges", [])),
            )
            for project in projects
        ]

    @strawberry.field
    async def project_page(
        self,
        info: GraphQLInfo,
        search: str = "",
        after: str | None = None,
        first: int = 24,
    ) -> ProjectPageType:
        if first < 1 or first > 50:
            raise GraphQLError(
                "Project page size must be between 1 and 50",
                extensions={"code": "BAD_USER_INPUT"},
            )
        normalized_search = search.strip().lower()
        if len(normalized_search) > 160:
            raise GraphQLError(
                "Project search must be at most 160 characters",
                extensions={"code": "BAD_USER_INPUT"},
            )
        filters = [project_access_filter(info)]
        if normalized_search:
            if info.context.session.bind.dialect.name == "postgresql":
                search_document = (
                    func.coalesce(Project.title, "")
                    + " "
                    + func.coalesce(Project.description, "")
                )
                filters.append(
                    func.to_tsvector(literal_column("'simple'"), search_document).op("@@")(
                        func.plainto_tsquery(literal_column("'simple'"), normalized_search)
                    )
                )
            else:
                filters.append(or_(
                    func.lower(Project.title).contains(normalized_search, autoescape=True),
                    func.lower(Project.description).contains(normalized_search, autoescape=True),
                ))
        total_count = await info.context.session.scalar(
            select(func.count(Project.id)).where(*filters)
        ) or 0
        if after:
            cursor_at, cursor_id = decode_project_cursor(after)
            filters.append(or_(
                Project.updated_at < cursor_at,
                (Project.updated_at == cursor_at) & (Project.id < cursor_id),
            ))
        rows = list(
            await info.context.session.scalars(
                select(Project)
                .where(*filters)
                .order_by(Project.updated_at.desc(), Project.id.desc())
                .limit(first + 1)
            )
        )
        has_more = len(rows) > first
        page_projects = rows[:first]
        return ProjectPageType(
            items=await project_summary_types(info, page_projects),
            next_cursor=(
                encode_project_cursor(page_projects[-1])
                if has_more and page_projects
                else None
            ),
            total_count=total_count,
        )

    @strawberry.field
    async def project(self, info: GraphQLInfo, id: strawberry.ID) -> ProjectType:
        project = await entity_project(info, str(id))
        return await serialize_project_for_user(info, project)

    @strawberry.field
    async def project_governance(
        self,
        info: GraphQLInfo,
        project_id: strawberry.ID,
    ) -> ProjectGovernanceType:
        project = await entity_project(info, str(project_id))
        return await project_governance_type(info, project)


@strawberry.type
class Mutation:
    @strawberry.mutation
    async def create_calendar_event(
        self,
        info: GraphQLInfo,
        input: CalendarEventInput,
    ) -> CalendarEventType:
        values = normalized_calendar_event(input)
        await enforce_calendar_policy(
            info, action="create", fields=set(values),
            content=f"{values.get('title', '')}\n{values.get('description', '')}",
        )
        attendee_ids = values.pop("attendee_ids")
        external_emails = values.pop("external_attendee_emails")
        organizer_reminder = values.pop("reminder_minutes")
        occurrence_times = calendar_occurrence_times(values)
        recurrence_frequency = values.pop("recurrence_frequency")
        recurrence_interval = values.pop("recurrence_interval")
        values.pop("recurrence_ends_at")
        values.pop("recurrence_count")
        attendee_ids.discard(info.context.user.id)
        if values["event_type"] == "personal" and (attendee_ids or external_emails):
            raise GraphQLError("Personal events cannot include attendees", extensions={"code": "BAD_USER_INPUT"})
        if values["event_type"] == "meeting" and not (attendee_ids or external_emails):
            raise GraphQLError("Meetings need at least one attendee", extensions={"code": "BAD_USER_INPUT"})
        users = await validated_calendar_attendees(info, attendee_ids, external_emails)

        series_id = str(uuid4()) if recurrence_frequency != "none" else None
        recurrence_count = len(occurrence_times) if series_id else None
        recurrence_ends_at = (
            occurrence_times[-1][0].astimezone(ZoneInfo(values["timezone"])).date()
            if series_id else None
        )
        events = [CalendarEvent(
            entity_id=info.context.user.entity_id,
            organizer_id=info.context.user.id,
            status="scheduled",
            starts_at=starts_at,
            ends_at=ends_at,
            series_id=series_id,
            recurrence_frequency=recurrence_frequency if series_id else None,
            recurrence_interval=recurrence_interval,
            recurrence_ends_at=recurrence_ends_at,
            recurrence_count=recurrence_count,
            occurrence_index=occurrence_index,
            **{key: value for key, value in values.items() if key not in {"starts_at", "ends_at"}},
        ) for occurrence_index, (starts_at, ends_at) in enumerate(occurrence_times)]
        info.context.session.add_all(events)
        await info.context.session.flush()
        event = events[0]
        now = datetime.now(timezone.utc)
        external_attendees: list[CalendarEventExternalAttendee] = []
        for occurrence in events:
            info.context.session.add(CalendarEventAttendee(
                event_id=occurrence.id,
                user_id=info.context.user.id,
                response="accepted",
                responded_at=now,
                reminder_minutes=organizer_reminder,
            ))
            for attendee in users:
                info.context.session.add(CalendarEventAttendee(
                    event_id=occurrence.id,
                    user_id=attendee.id,
                    response="pending",
                    reminder_minutes=15,
                ))
            occurrence_external_attendees = [CalendarEventExternalAttendee(
                event_id=occurrence.id,
                email=email,
                response="pending",
                status="active",
                delivery_status="pending" if occurrence.occurrence_index == 0 else "series",
            ) for email in sorted(external_emails)]
            info.context.session.add_all(occurrence_external_attendees)
            if occurrence.occurrence_index == 0:
                external_attendees = occurrence_external_attendees
        await info.context.session.flush()
        email_jobs = [new_meeting_email_job(info, event, attendee, "invitation") for attendee in external_attendees]
        info.context.session.add_all(email_jobs)
        notifications: list[tuple[Notification, User]] = []
        for attendee in users:
            notification = Notification(
                entity_id=event.entity_id,
                user_id=attendee.id,
                actor_id=info.context.user.id,
                kind="meeting_invitation",
                title=f"Meeting invitation from {info.context.user.display_name}",
                body=(
                    f"{event.title} · {as_utc(event.starts_at).strftime('%b %d at %H:%M UTC')}"
                    + (f" · Repeats {recurrence_frequency}" if series_id else "")
                ),
                calendar_event_id=event.id,
            )
            info.context.session.add(notification)
            notifications.append((notification, attendee))
        await info.context.session.commit()
        await asyncio.gather(*(notify_background_job(job.id) for job in email_jobs))
        await info.context.session.refresh(event)
        await asyncio.gather(*(
            communication_hub.publish(attendee.id, {
                "type": "notification",
                "notification": serialize_notification(notification, info.context.user),
            })
            for notification, attendee in notifications
        ), *(
            communication_hub.publish(attendee.id, {
                "type": "calendar_updated", "calendar_event_id": event.id,
            })
            for attendee in users
        ))
        return (await calendar_event_types(info, [event]))[0]

    @strawberry.mutation
    async def update_calendar_event(
        self,
        info: GraphQLInfo,
        event_id: strawberry.ID,
        input: CalendarEventInput,
    ) -> CalendarEventType:
        event = await accessible_calendar_event(info, str(event_id))
        if event.organizer_id != info.context.user.id:
            raise GraphQLError("Only the organizer can update this event", extensions={"code": "FORBIDDEN"})
        if event.status == "cancelled":
            raise GraphQLError("Cancelled events cannot be updated", extensions={"code": "CONFLICT"})
        values = normalized_calendar_event(input)
        await enforce_calendar_policy(
            info, action="edit", event=event, fields=set(values),
            content=f"{values.get('title', '')}\n{values.get('description', '')}",
        )
        attendee_ids = values.pop("attendee_ids")
        external_emails = values.pop("external_attendee_emails")
        organizer_reminder = values.pop("reminder_minutes")
        requested_recurrence = values.pop("recurrence_frequency")
        values.pop("recurrence_interval")
        values.pop("recurrence_ends_at")
        values.pop("recurrence_count")
        if requested_recurrence != "none" and not event.series_id:
            raise GraphQLError(
                "Create a new event to start a recurring series",
                extensions={"code": "BAD_USER_INPUT"},
            )
        attendee_ids.discard(info.context.user.id)
        if values["event_type"] == "personal" and (attendee_ids or external_emails):
            raise GraphQLError("Personal events cannot include attendees", extensions={"code": "BAD_USER_INPUT"})
        if values["event_type"] == "meeting" and not (attendee_ids or external_emails):
            raise GraphQLError("Meetings need at least one attendee", extensions={"code": "BAD_USER_INPUT"})
        await validated_calendar_attendees(info, attendee_ids, external_emails)
        memberships = list(await info.context.session.scalars(
            select(CalendarEventAttendee).where(CalendarEventAttendee.event_id == event.id)
        ))
        membership_by_user = {membership.user_id: membership for membership in memberships}
        organizer_membership = membership_by_user[info.context.user.id]
        if organizer_membership.reminder_minutes != organizer_reminder:
            organizer_membership.reminder_minutes = organizer_reminder
            organizer_membership.reminder_sent_at = None
        existing_ids = set(membership_by_user)
        requested_ids = attendee_ids | {info.context.user.id}
        removed_ids = existing_ids - requested_ids
        for user_id in removed_ids:
            await info.context.session.delete(membership_by_user[user_id])
        for user_id in requested_ids - existing_ids:
            info.context.session.add(CalendarEventAttendee(
                event_id=event.id,
                user_id=user_id,
                response="accepted" if user_id == info.context.user.id else "pending",
                responded_at=datetime.now(timezone.utc) if user_id == info.context.user.id else None,
                reminder_minutes=organizer_reminder if user_id == info.context.user.id else 15,
            ))
        previous_start = as_utc(event.starts_at)
        for field, value in values.items():
            setattr(event, field, value)
        if previous_start != values["starts_at"]:
            for membership in memberships:
                membership.reminder_sent_at = None
        event.updated_at = datetime.now(timezone.utc)

        external_attendees = list(await info.context.session.scalars(
            select(CalendarEventExternalAttendee).where(
                CalendarEventExternalAttendee.event_id == event.id,
            )
        ))
        external_by_email = {attendee.email: attendee for attendee in external_attendees}
        active_external_emails = {
            attendee.email for attendee in external_attendees if attendee.status == "active"
        }
        email_jobs = []
        for email in sorted(external_emails):
            attendee = external_by_email.get(email)
            is_new = not attendee or attendee.status != "active"
            if not attendee:
                attendee = CalendarEventExternalAttendee(
                    event_id=event.id, email=email, response="pending", status="active",
                )
                info.context.session.add(attendee)
                await info.context.session.flush()
            else:
                attendee.status = "active"
                if is_new:
                    attendee.response = "pending"
            email_jobs.append(new_meeting_email_job(
                info, event, attendee, "invitation" if is_new else "updated",
            ))
        for email in sorted(active_external_emails - external_emails):
            attendee = external_by_email[email]
            attendee.status = "removed"
            email_jobs.append(new_meeting_email_job(info, event, attendee, "cancelled"))
        info.context.session.add_all(email_jobs)

        notifications: list[tuple[Notification, str]] = []
        all_changed_ids = (requested_ids | removed_ids) - {info.context.user.id}
        removed_users = list(await info.context.session.scalars(
            select(User).where(User.id.in_(removed_ids))
        )) if removed_ids else []
        for attendee_id in attendee_ids:
            is_new = attendee_id not in existing_ids
            notification = Notification(
                entity_id=event.entity_id,
                user_id=attendee_id,
                actor_id=info.context.user.id,
                kind="meeting_invitation" if is_new else "meeting_updated",
                title="New meeting invitation" if is_new else "Meeting updated",
                body=f"{event.title} · {as_utc(event.starts_at).strftime('%b %d at %H:%M UTC')}",
                calendar_event_id=event.id,
            )
            info.context.session.add(notification)
            notifications.append((notification, attendee_id))
        for removed_user in removed_users:
            notification = Notification(
                entity_id=event.entity_id,
                user_id=removed_user.id,
                actor_id=info.context.user.id,
                kind="meeting_removed",
                title="Meeting removed from your calendar",
                body=event.title,
            )
            info.context.session.add(notification)
            notifications.append((notification, removed_user.id))
        await info.context.session.commit()
        await asyncio.gather(*(notify_background_job(job.id) for job in email_jobs))
        await info.context.session.refresh(event)
        await asyncio.gather(*(
            communication_hub.publish(user_id, {
                "type": "notification",
                "notification": serialize_notification(notification, info.context.user),
            })
            for notification, user_id in notifications
        ), *(
            communication_hub.publish(user_id, {
                "type": "calendar_updated", "calendar_event_id": event.id,
            })
            for user_id in all_changed_ids
        ))
        return (await calendar_event_types(info, [event]))[0]

    @strawberry.mutation
    async def set_calendar_event_reminder(
        self,
        info: GraphQLInfo,
        event_id: strawberry.ID,
        reminder_minutes: int | None,
    ) -> CalendarEventType:
        event = await accessible_calendar_event(info, str(event_id))
        if event.status == "cancelled":
            raise GraphQLError("Cancelled events cannot have reminders", extensions={"code": "CONFLICT"})
        if reminder_minutes not in REMINDER_MINUTES:
            raise GraphQLError(
                "Reminder must be off, at the start time, or 5 minutes to 1 day before the event",
                extensions={"code": "BAD_USER_INPUT"},
            )
        membership = await info.context.session.scalar(
            select(CalendarEventAttendee).where(
                CalendarEventAttendee.event_id == event.id,
                CalendarEventAttendee.user_id == info.context.user.id,
            )
        )
        membership.reminder_minutes = reminder_minutes
        membership.reminder_sent_at = None
        await info.context.session.commit()
        await info.context.session.refresh(event)
        return (await calendar_event_types(info, [event]))[0]

    @strawberry.mutation
    async def check_calendar_reminders(self, info: GraphQLInfo) -> list[NotificationType]:
        notifications = await dispatch_due_calendar_reminders(
            info.context.session,
            user_id=info.context.user.id,
            publish=True,
        )
        return [notification_type(notification, None) for notification in notifications]

    @strawberry.mutation
    async def respond_to_calendar_event(
        self,
        info: GraphQLInfo,
        event_id: strawberry.ID,
        response: str,
    ) -> CalendarEventType:
        event = await accessible_calendar_event(info, str(event_id))
        normalized_response = response.strip().lower()
        if normalized_response not in {"accepted", "tentative", "declined"}:
            raise GraphQLError("Response must be accepted, tentative, or declined", extensions={"code": "BAD_USER_INPUT"})
        if event.organizer_id == info.context.user.id:
            raise GraphQLError("The organizer is always attending", extensions={"code": "BAD_USER_INPUT"})
        membership = await info.context.session.scalar(
            select(CalendarEventAttendee).where(
                CalendarEventAttendee.event_id == event.id,
                CalendarEventAttendee.user_id == info.context.user.id,
            )
        )
        membership.response = normalized_response
        membership.responded_at = datetime.now(timezone.utc)
        notification = Notification(
            entity_id=event.entity_id,
            user_id=event.organizer_id,
            actor_id=info.context.user.id,
            kind="meeting_response",
            title=f"{info.context.user.display_name} responded {normalized_response}",
            body=event.title,
            calendar_event_id=event.id,
        )
        info.context.session.add(notification)
        await info.context.session.commit()
        await communication_hub.publish(event.organizer_id, {
            "type": "notification",
            "notification": serialize_notification(notification, info.context.user),
        })
        await communication_hub.publish(event.organizer_id, {
            "type": "calendar_updated", "calendar_event_id": event.id,
        })
        return (await calendar_event_types(info, [event]))[0]

    @strawberry.mutation
    async def cancel_calendar_event(
        self,
        info: GraphQLInfo,
        event_id: strawberry.ID,
        scope: str = "event",
    ) -> CalendarEventType:
        event = await accessible_calendar_event(info, str(event_id))
        if event.organizer_id != info.context.user.id:
            raise GraphQLError("Only the organizer can cancel this event", extensions={"code": "FORBIDDEN"})
        await enforce_calendar_policy(info, action="delete", event=event)
        normalized_scope = scope.strip().lower()
        if normalized_scope not in {"event", "future", "series"}:
            raise GraphQLError(
                "Cancellation scope must be event, future, or series",
                extensions={"code": "BAD_USER_INPUT"},
            )
        targets = [event]
        if event.series_id and normalized_scope != "event":
            series_filters = [
                CalendarEvent.entity_id == event.entity_id,
                CalendarEvent.series_id == event.series_id,
            ]
            if normalized_scope == "future":
                series_filters.append(CalendarEvent.occurrence_index >= event.occurrence_index)
            targets = list(await info.context.session.scalars(
                select(CalendarEvent).where(*series_filters).order_by(CalendarEvent.occurrence_index)
            ))
        target_ids = [target.id for target in targets]
        now = datetime.now(timezone.utc)
        for target in targets:
            target.status = "cancelled"
            target.updated_at = now
        attendee_ids = sorted(set(await info.context.session.scalars(
            select(CalendarEventAttendee.user_id).where(
                CalendarEventAttendee.event_id.in_(target_ids),
                CalendarEventAttendee.user_id != info.context.user.id,
            )
        )))
        external_rows = list(await info.context.session.scalars(
            select(CalendarEventExternalAttendee).where(
                CalendarEventExternalAttendee.event_id.in_(target_ids),
                CalendarEventExternalAttendee.status == "active",
            ).order_by(CalendarEventExternalAttendee.event_id)
        ))
        external_attendees = list({attendee.email: attendee for attendee in external_rows}.values())
        email_jobs = [
            new_meeting_email_job(info, event, attendee, "cancelled")
            for attendee in external_attendees
        ]
        info.context.session.add_all(email_jobs)
        notifications: list[tuple[Notification, str]] = []
        for attendee_id in attendee_ids:
            notification = Notification(
                entity_id=event.entity_id,
                user_id=attendee_id,
                actor_id=info.context.user.id,
                kind="meeting_cancelled",
                title="Meeting cancelled",
                body=(
                    f"{event.title} · This and future meetings"
                    if normalized_scope == "future"
                    else f"{event.title} · Entire series"
                    if normalized_scope == "series"
                    else event.title
                ),
                calendar_event_id=event.id,
            )
            info.context.session.add(notification)
            notifications.append((notification, attendee_id))
        await info.context.session.commit()
        await asyncio.gather(*(notify_background_job(job.id) for job in email_jobs))
        await info.context.session.refresh(event)
        await asyncio.gather(*(
            communication_hub.publish(user_id, {
                "type": "notification",
                "notification": serialize_notification(notification, info.context.user),
            })
            for notification, user_id in notifications
        ), *(
            communication_hub.publish(user_id, {
                "type": "calendar_updated", "calendar_event_id": event.id,
            })
            for user_id in attendee_ids
        ))
        return (await calendar_event_types(info, [event]))[0]

    @strawberry.mutation
    async def send_direct_message(
        self,
        info: GraphQLInfo,
        recipient_id: strawberry.ID,
        body: str,
        parent_id: strawberry.ID | None = None,
        attachments: list[MessageAttachmentInput] | None = None,
    ) -> DirectMessageType:
        message_body = body.strip()
        if not message_body or len(message_body) > 2_000:
            raise GraphQLError(
                "Messages must be between 1 and 2,000 characters",
                extensions={"code": "BAD_USER_INPUT"},
            )
        await enforce_message_policies(info, message_body)
        recipient = await info.context.session.get(User, str(recipient_id))
        if (
            not recipient
            or recipient.entity_id != info.context.user.entity_id
            or recipient.id == info.context.user.id
        ):
            raise GraphQLError("Contact not found", extensions={"code": "NOT_FOUND"})

        normalized_attachments = normalize_message_attachments(attachments or [])
        normalized_parent_id = str(parent_id) if parent_id else None
        if normalized_parent_id:
            parent = await info.context.session.get(DirectMessage, normalized_parent_id)
            expected_people = {info.context.user.id, recipient.id}
            if (
                not parent
                or parent.entity_id != info.context.user.entity_id
                or {parent.sender_id, parent.recipient_id} != expected_people
                or parent.deleted_at is not None
            ):
                raise GraphQLError("Reply target not found", extensions={"code": "NOT_FOUND"})

        message = DirectMessage(
            entity_id=info.context.user.entity_id,
            sender_id=info.context.user.id,
            recipient_id=recipient.id,
            body=message_body,
            parent_id=normalized_parent_id,
            attachments=normalized_attachments,
        )
        info.context.session.add(message)
        await info.context.session.commit()
        await info.context.session.refresh(message)

        await communication_hub.publish(
            recipient.id,
            {
                "type": "direct_message",
                "message": serialize_direct_message(
                    message,
                    info.context.user,
                    recipient,
                ),
            },
        )
        return direct_message_type(message, info.context.user, recipient, info.context.user.id)

    @strawberry.mutation
    async def create_communication_channel(
        self,
        info: GraphQLInfo,
        name: str,
        description: str,
        channel_type: str,
        member_ids: list[strawberry.ID],
    ) -> CommunicationChannelType:
        normalized_name = normalized_channel_name(name)
        normalized_description = description.strip()
        if len(normalized_description) > 500:
            raise GraphQLError(
                "Channel descriptions must be at most 500 characters",
                extensions={"code": "BAD_USER_INPUT"},
            )
        if channel_type not in {"channel", "group"}:
            raise GraphQLError("Channel type must be channel or group", extensions={"code": "BAD_USER_INPUT"})
        existing = await info.context.session.scalar(
            select(CommunicationChannel.id).where(
                CommunicationChannel.entity_id == info.context.user.entity_id,
                func.lower(CommunicationChannel.name) == normalized_name.lower(),
            )
        )
        if existing:
            raise GraphQLError("A channel or group with that name already exists", extensions={"code": "CONFLICT"})
        channel_count = await info.context.session.scalar(
            select(func.count(CommunicationChannel.id)).where(
                CommunicationChannel.entity_id == info.context.user.entity_id
            )
        )
        if (channel_count or 0) >= 200:
            raise GraphQLError("This workspace has reached its 200-channel limit", extensions={"code": "QUOTA_EXCEEDED"})

        workspace_users = list(await info.context.session.scalars(
            select(User).where(User.entity_id == info.context.user.entity_id)
        ))
        users_by_id = {member.id: member for member in workspace_users}
        requested_ids = {str(member_id) for member_id in member_ids}
        if any(member_id not in users_by_id for member_id in requested_ids):
            raise GraphQLError("Every group member must belong to this workspace", extensions={"code": "BAD_USER_INPUT"})
        requested_ids.discard(info.context.user.id)
        if channel_type == "group" and not requested_ids:
            raise GraphQLError("A group needs at least one other member", extensions={"code": "BAD_USER_INPUT"})

        channel = CommunicationChannel(
            entity_id=info.context.user.entity_id,
            created_by_id=info.context.user.id,
            name=normalized_name,
            description=normalized_description,
            channel_type=channel_type,
            visibility="workspace" if channel_type == "channel" else "private",
        )
        info.context.session.add(channel)
        await info.context.session.flush()
        included_ids = set(users_by_id) if channel_type == "channel" else requested_ids | {info.context.user.id}
        for member_id in included_ids:
            info.context.session.add(CommunicationChannelMember(
                channel_id=channel.id,
                user_id=member_id,
                role="owner" if member_id == info.context.user.id else "member",
                last_read_at=datetime.now(timezone.utc),
            ))
        await info.context.session.commit()
        await info.context.session.refresh(channel)
        members = sorted((users_by_id[member_id] for member_id in included_ids), key=lambda member: member.display_name)
        await asyncio.gather(*(
            communication_hub.publish(member_id, {"type": "channel_updated", "channel_id": channel.id})
            for member_id in included_ids if member_id != info.context.user.id
        ))
        return communication_channel_type(channel, members, None, 0, info.context.user)

    @strawberry.mutation
    async def update_communication_channel_members(
        self,
        info: GraphQLInfo,
        channel_id: strawberry.ID,
        member_ids: list[strawberry.ID],
    ) -> CommunicationChannelType:
        channel = await entity_communication_channel(info, str(channel_id))
        if channel.channel_type != "group":
            raise GraphQLError("Workspace channels already include every member", extensions={"code": "BAD_USER_INPUT"})
        if info.context.user.role != "admin" and channel.created_by_id != info.context.user.id:
            raise GraphQLError("Only the group owner or a workspace admin can manage members", extensions={"code": "FORBIDDEN"})
        requested_ids = {str(member_id) for member_id in member_ids} | {channel.created_by_id}
        workspace_users = list(await info.context.session.scalars(
            select(User).where(User.entity_id == info.context.user.entity_id)
        ))
        users_by_id = {member.id: member for member in workspace_users}
        if any(member_id not in users_by_id for member_id in requested_ids):
            raise GraphQLError("Every group member must belong to this workspace", extensions={"code": "BAD_USER_INPUT"})
        if len(requested_ids) < 2:
            raise GraphQLError("A group needs at least two members", extensions={"code": "BAD_USER_INPUT"})
        existing_members = list(await info.context.session.scalars(
            select(CommunicationChannelMember).where(CommunicationChannelMember.channel_id == channel.id)
        ))
        existing_ids = {membership.user_id for membership in existing_members}
        for membership in existing_members:
            if membership.user_id not in requested_ids:
                await info.context.session.delete(membership)
        for member_id in requested_ids - existing_ids:
            info.context.session.add(CommunicationChannelMember(
                channel_id=channel.id,
                user_id=member_id,
                role="owner" if member_id == channel.created_by_id else "member",
                last_read_at=datetime.now(timezone.utc),
            ))
        channel.updated_at = datetime.now(timezone.utc)
        await info.context.session.commit()
        await asyncio.gather(*(
            communication_hub.publish(member_id, {"type": "channel_updated", "channel_id": channel.id})
            for member_id in existing_ids | requested_ids if member_id != info.context.user.id
        ))
        members = sorted((users_by_id[member_id] for member_id in requested_ids), key=lambda member: member.display_name)
        latest = await info.context.session.scalar(
            select(CommunicationChannelMessage)
            .where(CommunicationChannelMessage.channel_id == channel.id)
            .order_by(CommunicationChannelMessage.created_at.desc())
            .limit(1)
        )
        return communication_channel_type(channel, members, latest, 0, info.context.user)

    @strawberry.mutation
    async def send_channel_message(
        self,
        info: GraphQLInfo,
        channel_id: strawberry.ID,
        body: str,
        parent_id: strawberry.ID | None = None,
        attachments: list[MessageAttachmentInput] | None = None,
    ) -> ChannelMessageType:
        message_body = body.strip()
        if not message_body or len(message_body) > 2_000:
            raise GraphQLError(
                "Messages must be between 1 and 2,000 characters",
                extensions={"code": "BAD_USER_INPUT"},
            )
        await enforce_message_policies(info, message_body)
        channel = await entity_communication_channel(info, str(channel_id))
        normalized_attachments = normalize_message_attachments(attachments or [])
        normalized_parent_id = str(parent_id) if parent_id else None
        if normalized_parent_id:
            parent = await info.context.session.get(CommunicationChannelMessage, normalized_parent_id)
            if not parent or parent.channel_id != channel.id or parent.deleted_at is not None:
                raise GraphQLError("Reply target not found", extensions={"code": "NOT_FOUND"})
        membership = await info.context.session.scalar(
            select(CommunicationChannelMember).where(
                CommunicationChannelMember.channel_id == channel.id,
                CommunicationChannelMember.user_id == info.context.user.id,
            )
        )
        now = datetime.now(timezone.utc)
        if not membership:
            membership = CommunicationChannelMember(
                channel_id=channel.id, user_id=info.context.user.id,
                role="member", last_read_at=now,
            )
            info.context.session.add(membership)
        else:
            membership.last_read_at = now
        message = CommunicationChannelMessage(
            entity_id=info.context.user.entity_id,
            channel_id=channel.id,
            sender_id=info.context.user.id,
            body=message_body,
            parent_id=normalized_parent_id,
            attachments=normalized_attachments,
        )
        channel.updated_at = now
        info.context.session.add(message)
        members = await channel_members(info, channel)
        mentioned_handles = {
            match.casefold() for match in re.findall(r"(?<![A-Za-z0-9_])@([A-Za-z0-9._-]{1,80})", message_body)
        }
        mention_notifications: list[tuple[Notification, User]] = []
        for member in members:
            if member.id == info.context.user.id or user_summary(member)["handle"].casefold() not in mentioned_handles:
                continue
            notification = Notification(
                entity_id=info.context.user.entity_id,
                user_id=member.id,
                actor_id=info.context.user.id,
                kind="chat_mention",
                title=f"{info.context.user.display_name} mentioned you in {channel.name}",
                body=message_body[:240],
                communication_channel_id=channel.id,
                communication_message_id=message.id,
            )
            info.context.session.add(notification)
            mention_notifications.append((notification, member))
        await info.context.session.commit()
        await info.context.session.refresh(message)
        serialized = serialize_channel_message(message, info.context.user)
        await asyncio.gather(*(
            communication_hub.publish(member.id, {"type": "channel_message", "message": serialized})
            for member in members if member.id != info.context.user.id
        ), *(
            communication_hub.publish(member.id, {
                "type": "notification",
                "notification": serialize_notification(notification, info.context.user),
            })
            for notification, member in mention_notifications
        ))
        return channel_message_type(message, info.context.user, info.context.user.id)

    @strawberry.mutation
    async def update_chat_message(
        self,
        info: GraphQLInfo,
        message_kind: str,
        message_id: strawberry.ID,
        body: str,
    ) -> bool:
        message, viewers = await accessible_chat_message(info, message_kind, str(message_id))
        if message.sender_id != info.context.user.id or message.deleted_at is not None:
            raise GraphQLError("Only the author can edit this message", extensions={"code": "FORBIDDEN"})
        message_body = body.strip()
        if not message_body or len(message_body) > 2_000:
            raise GraphQLError("Messages must be between 1 and 2,000 characters", extensions={"code": "BAD_USER_INPUT"})
        await enforce_message_policies(info, message_body, "edit")
        message.body = message_body
        message.edited_at = datetime.now(timezone.utc)
        await info.context.session.commit()
        await publish_chat_change(info, message_kind, message, viewers)
        return True

    @strawberry.mutation
    async def delete_chat_message(
        self,
        info: GraphQLInfo,
        message_kind: str,
        message_id: strawberry.ID,
    ) -> bool:
        message, viewers = await accessible_chat_message(info, message_kind, str(message_id))
        if message.sender_id != info.context.user.id:
            raise GraphQLError("Only the author can delete this message", extensions={"code": "FORBIDDEN"})
        if message.deleted_at is None:
            message.deleted_at = datetime.now(timezone.utc)
            message.attachments = []
            await info.context.session.commit()
            await publish_chat_change(info, message_kind, message, viewers)
        return True

    @strawberry.mutation
    async def toggle_chat_message_reaction(
        self,
        info: GraphQLInfo,
        message_kind: str,
        message_id: strawberry.ID,
        emoji: str,
    ) -> bool:
        if emoji not in {"👍", "❤️", "🎉", "👀", "✅", "😂"}:
            raise GraphQLError("Unsupported message reaction", extensions={"code": "BAD_USER_INPUT"})
        message, viewers = await accessible_chat_message(info, message_kind, str(message_id))
        if message.deleted_at is not None:
            raise GraphQLError("Deleted messages cannot be reacted to", extensions={"code": "BAD_USER_INPUT"})
        reactions = {key: list(value) for key, value in (message.reactions or {}).items() if isinstance(value, list)}
        users = reactions.get(emoji, [])
        if info.context.user.id in users:
            users = [user_id for user_id in users if user_id != info.context.user.id]
        else:
            users.append(info.context.user.id)
        if users:
            reactions[emoji] = list(dict.fromkeys(users))
        else:
            reactions.pop(emoji, None)
        message.reactions = reactions
        await info.context.session.commit()
        await publish_chat_change(info, message_kind, message, viewers)
        return True

    @strawberry.mutation
    async def toggle_chat_message_pin(
        self,
        info: GraphQLInfo,
        message_kind: str,
        message_id: strawberry.ID,
    ) -> bool:
        message, viewers = await accessible_chat_message(info, message_kind, str(message_id))
        if message.deleted_at is not None:
            raise GraphQLError("Deleted messages cannot be pinned", extensions={"code": "BAD_USER_INPUT"})
        message.pinned = not message.pinned
        await info.context.session.commit()
        await publish_chat_change(info, message_kind, message, viewers)
        return message.pinned

    @strawberry.mutation
    async def toggle_chat_message_bookmark(
        self,
        info: GraphQLInfo,
        message_kind: str,
        message_id: strawberry.ID,
    ) -> bool:
        message, _ = await accessible_chat_message(info, message_kind, str(message_id))
        if message.deleted_at is not None:
            raise GraphQLError("Deleted messages cannot be bookmarked", extensions={"code": "BAD_USER_INPUT"})
        user_ids = list(message.bookmark_user_ids or [])
        if info.context.user.id in user_ids:
            user_ids = [user_id for user_id in user_ids if user_id != info.context.user.id]
        else:
            user_ids.append(info.context.user.id)
        message.bookmark_user_ids = list(dict.fromkeys(user_ids))
        await info.context.session.commit()
        return info.context.user.id in message.bookmark_user_ids

    @strawberry.mutation
    async def mark_channel_read(
        self,
        info: GraphQLInfo,
        channel_id: strawberry.ID,
    ) -> bool:
        channel = await entity_communication_channel(info, str(channel_id))
        membership = await info.context.session.scalar(
            select(CommunicationChannelMember).where(
                CommunicationChannelMember.channel_id == channel.id,
                CommunicationChannelMember.user_id == info.context.user.id,
            )
        )
        if not membership:
            membership = CommunicationChannelMember(
                channel_id=channel.id,
                user_id=info.context.user.id,
                role="member",
            )
            info.context.session.add(membership)
        membership.last_read_at = datetime.now(timezone.utc)
        await info.context.session.commit()
        return True

    @strawberry.mutation
    async def mark_direct_conversation_read(
        self,
        info: GraphQLInfo,
        contact_id: strawberry.ID,
    ) -> bool:
        contact = await info.context.session.get(User, str(contact_id))
        if not contact or contact.entity_id != info.context.user.entity_id:
            raise GraphQLError("Contact not found", extensions={"code": "NOT_FOUND"})
        now = datetime.now(timezone.utc)
        unread_messages = await info.context.session.scalars(
            select(DirectMessage).where(
                DirectMessage.sender_id == contact.id,
                DirectMessage.recipient_id == info.context.user.id,
                DirectMessage.read_at.is_(None),
            )
        )
        for message in unread_messages:
            message.read_at = now
        unread_notifications = await info.context.session.scalars(
            select(Notification).where(
                Notification.user_id == info.context.user.id,
                Notification.kind == "direct_message",
                Notification.contact_id == contact.id,
                Notification.read_at.is_(None),
            )
        )
        for notification in unread_notifications:
            notification.read_at = now
        await info.context.session.commit()
        await communication_hub.publish(contact.id, {
            "type": "direct_read",
            "contact_id": info.context.user.id,
            "read_at": now.isoformat(),
        })
        return True

    @strawberry.mutation
    async def mark_notification_read(
        self,
        info: GraphQLInfo,
        notification_id: strawberry.ID,
    ) -> bool:
        notification = await info.context.session.get(Notification, str(notification_id))
        if not notification or notification.user_id != info.context.user.id:
            raise GraphQLError("Notification not found", extensions={"code": "NOT_FOUND"})
        notification.read_at = notification.read_at or datetime.now(timezone.utc)
        await info.context.session.commit()
        return True

    @strawberry.mutation
    async def mark_all_notifications_read(self, info: GraphQLInfo) -> bool:
        unread = await info.context.session.scalars(
            select(Notification).where(
                Notification.user_id == info.context.user.id,
                Notification.read_at.is_(None),
            )
        )
        now = datetime.now(timezone.utc)
        for notification in unread:
            notification.read_at = now
        await info.context.session.commit()
        return True

    @strawberry.mutation
    async def invite_workspace_member(
        self,
        info: GraphQLInfo,
        input: InviteMemberInput,
    ) -> WorkspaceInvitationType:
        require_admin(info)
        email = normalized_email(input.email)
        display_name = input.display_name.strip()
        role = validated_role(input.role)
        job_title = normalized_job_title(input.job_title)
        if len(display_name) < 2 or len(display_name) > 100:
            raise GraphQLError(
                "Full name must be between 2 and 100 characters",
                extensions={"code": "BAD_USER_INPUT"},
            )
        existing_user = await info.context.session.scalar(select(User).where(User.email == email))
        if existing_user:
            raise GraphQLError(
                "An account already uses this email",
                extensions={"code": "CONFLICT"},
            )

        token = create_invitation_token()
        expires_at = datetime.now(timezone.utc) + timedelta(
            days=info.context.settings.invitation_expiry_days
        )
        invitation = await info.context.session.scalar(
            select(Invitation).where(
                Invitation.entity_id == info.context.user.entity_id,
                Invitation.email == email,
            )
        )
        if invitation and invitation.status == "accepted":
            raise GraphQLError("This contact is already active", extensions={"code": "CONFLICT"})
        try:
            await ensure_user_capacity(
                info.context.session,
                info.context.user.entity_id,
                additional_reserved_seats=(
                    0 if invitation and invitation.status == "pending" else 1
                ),
            )
        except QuotaExceededError as error:
            metrics.record_quota(error.resource)
            raise GraphQLError(
                str(error),
                extensions={"code": "QUOTA_EXCEEDED", "resource": error.resource},
            ) from error
        if invitation:
            invitation.display_name = display_name
            invitation.job_title = job_title
            invitation.role = role
            invitation.status = "pending"
            invitation.token_hash = hash_invitation_token(token)
            invitation.delivery_status = "pending"
            invitation.expires_at = expires_at
            invitation.invited_by_id = info.context.user.id
        else:
            invitation = Invitation(
                entity_id=info.context.user.entity_id,
                invited_by_id=info.context.user.id,
                email=email,
                display_name=display_name,
                job_title=job_title,
                role=role,
                token_hash=hash_invitation_token(token),
                expires_at=expires_at,
            )
            info.context.session.add(invitation)
        await info.context.session.flush()
        setup_url = (
            f"{info.context.settings.frontend_url.rstrip('/')}"
            f"/accept-invite?token={token}"
        )
        invitation.delivery_status = "queued"
        email_job = new_background_job(
            entity_id=info.context.user.entity_id,
            created_by_id=info.context.user.id,
            kind=INVITATION_EMAIL_JOB,
            payload={
                "invitation_id": invitation.id,
                "encrypted_token": SecretBox(info.context.settings.auth_secret).encrypt(
                    token,
                    "invitation_email",
                ),
            },
            settings=info.context.settings,
        )
        info.context.session.add(email_job)
        await info.context.session.commit()
        await notify_background_job(email_job.id)
        await info.context.session.refresh(invitation)
        preview_url = setup_url if info.context.settings.environment == "development" else None
        return invitation_type(invitation, preview_url)

    @strawberry.mutation
    async def update_workspace_member_role(
        self,
        info: GraphQLInfo,
        user_id: strawberry.ID,
        role: str,
    ) -> WorkspaceMemberType:
        require_admin(info)
        normalized_role = validated_role(role)
        member = await info.context.session.get(User, str(user_id))
        if not member or member.entity_id != info.context.user.entity_id:
            raise GraphQLError("Member not found", extensions={"code": "NOT_FOUND"})
        if member.role == "admin" and normalized_role != "admin":
            admin_count = await info.context.session.scalar(
                select(func.count(User.id)).where(
                    User.entity_id == info.context.user.entity_id,
                    User.role == "admin",
                )
            )
            if (admin_count or 0) <= 1:
                raise GraphQLError(
                    "Every workspace must keep at least one admin",
                    extensions={"code": "CONFLICT"},
                )
        member.role = normalized_role
        await info.context.session.commit()
        await info.context.session.refresh(member)
        return WorkspaceMemberType(
            id=strawberry.ID(member.id),
            display_name=member.display_name,
            email=member.email,
            role=member.role,
            created_at=as_utc(member.created_at),
            is_current_user=member.id == info.context.user.id,
        )

    @strawberry.mutation
    async def cancel_workspace_invitation(
        self,
        info: GraphQLInfo,
        invitation_id: strawberry.ID,
    ) -> bool:
        require_admin(info)
        invitation = await info.context.session.get(Invitation, str(invitation_id))
        if not invitation or invitation.entity_id != info.context.user.entity_id:
            raise GraphQLError("Invitation not found", extensions={"code": "NOT_FOUND"})
        if invitation.status != "pending":
            raise GraphQLError("Only pending invitations can be canceled", extensions={"code": "CONFLICT"})
        invitation.status = "canceled"
        await info.context.session.commit()
        return True

    @strawberry.mutation
    async def create_project(self, info: GraphQLInfo, input: ProjectInput) -> ProjectType:
        require_admin(info)
        try:
            await ensure_project_capacity(info.context.session, info.context.user.entity_id)
        except QuotaExceededError as error:
            metrics.record_quota(error.resource)
            raise GraphQLError(
                str(error),
                extensions={"code": "QUOTA_EXCEEDED", "resource": error.resource},
            ) from error
        validated = validate_project_input(input)
        owner_id, collaborator_ids = await validate_project_people(
            info, validated, info.context.user.id
        )
        project = Project(
            owner_id=owner_id,
            entity_id=info.context.user.entity_id,
            title=validated.title,
            description=validated.description,
            status=validated.status,
            visibility="workspace",
            approval_status="draft",
            profile=validated.profile.model_dump(mode="json"),
            source_text=validated.source_text,
            graph=validated.graph.model_dump(mode="json"),
        )
        info.context.session.add(project)
        await info.context.session.flush()
        await replace_project_collaborators(
            info.context.session, project.id, collaborator_ids
        )
        revision = await snapshot_project(
            info.context.session, project, info.context.user.id, "Created flowchart"
        )
        record_audit_event(
            info.context.session,
            entity_id=project.entity_id,
            actor_id=info.context.user.id,
            project_id=project.id,
            action="project.created",
            details={"revision": revision.version},
        )
        await info.context.session.commit()
        await info.context.session.refresh(project)
        return await serialize_project_for_user(info, project)

    @strawberry.mutation
    async def update_project(
        self,
        info: GraphQLInfo,
        id: strawberry.ID,
        input: ProjectInput,
        expected_revision: int,
    ) -> ProjectType:
        project = await info.context.session.scalar(
            select(Project).where(Project.id == str(id)).with_for_update()
        )
        if (
            not project
            or project.entity_id != info.context.user.entity_id
            or not await project_access_role(
                info.context.session, project, info.context.user
            )
        ):
            raise GraphQLError("Project not found", extensions={"code": "NOT_FOUND"})
        access = await project_access_role(
            info.context.session, project, info.context.user
        )
        if not can_edit_project(access):
            raise GraphQLError(
                "Editor access is required",
                extensions={"code": "FORBIDDEN"},
            )
        if expected_revision != (project.revision or 0):
            raise GraphQLError(
                "This flowchart changed after you opened it. Reload the latest version before saving.",
                extensions={
                    "code": "CONFLICT",
                    "currentRevision": project.revision or 0,
                },
            )
        validated = validate_project_input(input)
        existing_collaborator_ids = list(
            await info.context.session.scalars(
                select(ProjectCollaborator.user_id).where(
                    ProjectCollaborator.project_id == project.id
                )
            )
        )
        if can_manage_project(access):
            owner_id, collaborator_ids = await validate_project_people(
                info, validated, project.owner_id or info.context.user.id
            )
        else:
            owner_id = project.owner_id or info.context.user.id
            collaborator_ids = existing_collaborator_ids
            if (
                validated.owner_id not in {None, owner_id}
                or set(validated.collaborator_ids) != set(existing_collaborator_ids)
            ):
                raise GraphQLError(
                    "Only the project owner or a workspace admin can change access",
                    extensions={"code": "FORBIDDEN"},
                )
        graph = validated.graph.model_dump(mode="json")
        project.title = validated.title
        project.description = validated.description
        project.status = validated.status
        project.profile = validated.profile.model_dump(mode="json")
        project.owner_id = owner_id
        project.source_text = validated.source_text
        project.graph = graph
        project.revision = (project.revision or 0) + 1
        if can_manage_project(access):
            await replace_project_collaborators(
                info.context.session, project.id, collaborator_ids
            )
        revision = await snapshot_project(
            info.context.session,
            project,
            info.context.user.id,
            "Saved flowchart changes",
        )
        project.approval_status = "draft"
        record_audit_event(
            info.context.session,
            entity_id=project.entity_id,
            actor_id=info.context.user.id,
            project_id=project.id,
            action="project.revision_created",
            target_type="project_revision",
            target_id=revision.id,
            details={"revision": revision.version},
        )
        await info.context.session.commit()
        await info.context.session.refresh(project)
        return await serialize_project_for_user(info, project)

    @strawberry.mutation
    async def update_project_governance(
        self,
        info: GraphQLInfo,
        project_id: strawberry.ID,
        visibility: str,
        access_entries: list[ProjectAccessInput],
    ) -> ProjectGovernanceType:
        project = await entity_project(info, str(project_id))
        access = await project_access_role(
            info.context.session, project, info.context.user
        )
        if not can_manage_project(access):
            raise GraphQLError(
                "Only the project owner or a workspace admin can change access",
                extensions={"code": "FORBIDDEN"},
            )
        try:
            normalized_visibility = normalize_visibility(visibility)
            normalized_entries = {
                str(entry.user_id): normalize_project_role(entry.access_role)
                for entry in access_entries
            }
        except ValueError as error:
            raise GraphQLError(
                str(error), extensions={"code": "BAD_USER_INPUT"}
            ) from error
        if project.owner_id:
            normalized_entries.setdefault(project.owner_id, "editor")
        if len(normalized_entries) > 50:
            raise GraphQLError(
                "A project can have at most 50 collaborators",
                extensions={"code": "BAD_USER_INPUT"},
            )
        members = list(
            await info.context.session.scalars(
                select(User).where(
                    User.id.in_(normalized_entries),
                    User.entity_id == info.context.user.entity_id,
                )
            )
        )
        if len(members) != len(normalized_entries):
            raise GraphQLError(
                "Project access can only include members of this workspace",
                extensions={"code": "BAD_USER_INPUT"},
            )
        await info.context.session.execute(
            delete(ProjectCollaborator).where(
                ProjectCollaborator.project_id == project.id
            )
        )
        info.context.session.add_all(
            ProjectCollaborator(
                project_id=project.id,
                user_id=user_id,
                access_role=role,
            )
            for user_id, role in normalized_entries.items()
        )
        project.visibility = normalized_visibility
        record_audit_event(
            info.context.session,
            entity_id=project.entity_id,
            actor_id=info.context.user.id,
            project_id=project.id,
            action="project.access_updated",
            details={
                "visibility": normalized_visibility,
                "member_count": len(normalized_entries),
            },
        )
        await info.context.session.commit()
        return await project_governance_type(info, project)

    @strawberry.mutation
    async def request_project_approval(
        self,
        info: GraphQLInfo,
        project_id: strawberry.ID,
        note: str = "",
    ) -> ProjectGovernanceType:
        project = await entity_project(info, str(project_id))
        access = await project_access_role(
            info.context.session, project, info.context.user
        )
        if not can_edit_project(access):
            raise GraphQLError(
                "Editor access is required to request approval",
                extensions={"code": "FORBIDDEN"},
            )
        request_note = note.strip()
        if len(request_note) > 2_000:
            raise GraphQLError(
                "Approval notes must be at most 2,000 characters",
                extensions={"code": "BAD_USER_INPUT"},
            )
        pending = await info.context.session.scalar(
            select(ProjectApproval).where(
                ProjectApproval.project_id == project.id,
                ProjectApproval.status == "pending",
            )
        )
        if pending:
            raise GraphQLError(
                "This flowchart already has a pending approval request",
                extensions={"code": "CONFLICT"},
            )
        revision = await latest_revision(info.context.session, project.id)
        if not revision or any(
            (
                revision.title != project.title,
                revision.description != (project.description or ""),
                revision.status != (project.status or "active"),
                revision.profile != (project.profile or {}),
                revision.source_text != project.source_text,
                revision.graph != project.graph,
            )
        ):
            revision = await snapshot_project(
                info.context.session,
                project,
                info.context.user.id,
                "Submitted for approval",
            )
        approval = ProjectApproval(
            project_id=project.id,
            revision_id=revision.id,
            requested_by_id=info.context.user.id,
            status="pending",
            request_note=request_note,
        )
        info.context.session.add(approval)
        await info.context.session.flush()
        project.approval_status = "pending"
        record_audit_event(
            info.context.session,
            entity_id=project.entity_id,
            actor_id=info.context.user.id,
            project_id=project.id,
            action="project.approval_requested",
            target_type="project_approval",
            target_id=approval.id,
            details={"revision": revision.version},
        )
        await info.context.session.commit()
        return await project_governance_type(info, project)

    @strawberry.mutation
    async def decide_project_approval(
        self,
        info: GraphQLInfo,
        project_id: strawberry.ID,
        decision: str,
        note: str = "",
    ) -> ProjectGovernanceType:
        project = await entity_project(info, str(project_id))
        access = await project_access_role(
            info.context.session, project, info.context.user
        )
        if not can_approve_project(access):
            raise GraphQLError(
                "Approver access is required",
                extensions={"code": "FORBIDDEN"},
            )
        normalized_decision = decision.strip().lower()
        if normalized_decision not in {"approved", "changes_requested"}:
            raise GraphQLError(
                "Decision must be approved or changes_requested",
                extensions={"code": "BAD_USER_INPUT"},
            )
        decision_note = note.strip()
        if len(decision_note) > 2_000:
            raise GraphQLError(
                "Decision notes must be at most 2,000 characters",
                extensions={"code": "BAD_USER_INPUT"},
            )
        if normalized_decision == "changes_requested" and not decision_note:
            raise GraphQLError(
                "Explain what must change",
                extensions={"code": "BAD_USER_INPUT"},
            )
        approval = await info.context.session.scalar(
            select(ProjectApproval)
            .where(
                ProjectApproval.project_id == project.id,
                ProjectApproval.status == "pending",
            )
            .order_by(ProjectApproval.requested_at.desc())
        )
        if not approval:
            raise GraphQLError(
                "No approval request is pending",
                extensions={"code": "CONFLICT"},
            )
        approval.status = normalized_decision
        approval.reviewer_id = info.context.user.id
        approval.decision_note = decision_note
        approval.decided_at = datetime.now(timezone.utc)
        project.approval_status = normalized_decision
        revision = await info.context.session.get(ProjectRevision, approval.revision_id)
        record_audit_event(
            info.context.session,
            entity_id=project.entity_id,
            actor_id=info.context.user.id,
            project_id=project.id,
            action=f"project.approval_{normalized_decision}",
            target_type="project_approval",
            target_id=approval.id,
            details={"revision": revision.version if revision else None},
        )
        await info.context.session.commit()
        return await project_governance_type(info, project)

    @strawberry.mutation
    async def restore_project_revision(
        self,
        info: GraphQLInfo,
        project_id: strawberry.ID,
        revision_id: strawberry.ID,
    ) -> ProjectType:
        project = await entity_project(info, str(project_id))
        access = await project_access_role(
            info.context.session, project, info.context.user
        )
        if not can_manage_project(access):
            raise GraphQLError(
                "Only the project owner or a workspace admin can restore revisions",
                extensions={"code": "FORBIDDEN"},
            )
        revision = await info.context.session.get(ProjectRevision, str(revision_id))
        if not revision or revision.project_id != project.id:
            raise GraphQLError(
                "Revision not found", extensions={"code": "NOT_FOUND"}
            )
        project.title = revision.title
        project.description = revision.description
        project.status = revision.status
        project.profile = revision.profile or {}
        project.source_text = revision.source_text
        project.graph = revision.graph
        project.approval_status = "draft"
        project.revision = (project.revision or 0) + 1
        restored = await snapshot_project(
            info.context.session,
            project,
            info.context.user.id,
            f"Restored version {revision.version}",
        )
        record_audit_event(
            info.context.session,
            entity_id=project.entity_id,
            actor_id=info.context.user.id,
            project_id=project.id,
            action="project.revision_restored",
            target_type="project_revision",
            target_id=restored.id,
            details={
                "restored_from": revision.version,
                "created_revision": restored.version,
            },
        )
        await info.context.session.commit()
        await info.context.session.refresh(project)
        return await serialize_project_for_user(info, project)

    @strawberry.mutation
    async def delete_project(self, info: GraphQLInfo, id: strawberry.ID) -> bool:
        project = await entity_project(info, str(id))
        access = await project_access_role(
            info.context.session, project, info.context.user
        )
        if not can_manage_project(access):
            raise GraphQLError(
                "Only the project owner or a workspace admin can delete this flowchart",
                extensions={"code": "FORBIDDEN"},
            )
        if await is_held(info.context.session, project.entity_id, "project", project.id):
            raise GraphQLError(
                "This project is preserved by an active legal hold",
                extensions={"code": "LEGAL_HOLD"},
            )
        record_audit_event(
            info.context.session,
            entity_id=project.entity_id,
            actor_id=info.context.user.id,
            project_id=project.id,
            action="project.deleted",
            details={"title": project.title},
        )
        await info.context.session.flush()
        try:
            await delete_project_objects(info.context.session, project.id, object_storage)
        except ObjectStorageError as error:
            raise GraphQLError(
                "Project files could not be removed",
                extensions={"code": "STORAGE_UNAVAILABLE"},
            ) from error
        await info.context.session.delete(project)
        await info.context.session.commit()
        return True


schema = strawberry.Schema(query=Query, mutation=Mutation)
settings = get_settings()
graphql_router = GraphQLRouter(
    schema,
    context_getter=get_graphql_context,
    graphql_ide="graphiql" if settings.environment == "development" else None,
)
