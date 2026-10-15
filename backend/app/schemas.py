from enum import Enum
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class NodeType(str, Enum):
    START = "start"
    END = "end"
    PROCESS = "process"
    DECISION = "decision"
    DOCUMENT = "document"
    EXTERNAL_SYSTEM = "external_system"
    WAIT = "wait"
    SUBPROCESS = "subprocess"
    SWIMLANE = "swimlane"


class UserRole(str, Enum):
    ADMIN = "admin"
    BASIC = "basic"
    GUEST = "guest"


class FlowNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")
    label: str = Field(min_length=1, max_length=240)
    type: NodeType = NodeType.PROCESS
    owner: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=1_000)
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    shape: str = Field(default="rounded", pattern=r"^(rounded|rectangle|ellipse|diamond|text|document)$")
    symbol: str | None = Field(
        default=None,
        max_length=60,
        pattern=r"^(bpmn_(start|end|timer|message|user_task|service_task|exclusive_gateway|parallel_gateway|data_object|data_store)|enterprise_(database|server|cloud|api|user|document|queue|system)|uml_(class|actor)|sequence_lifeline|erd_entity|architecture_component|network_device|mind_topic|org_unit|sticky_note|comment_card)$",
    )
    width: float = Field(default=180, ge=80, le=720)
    height: float = Field(default=76, ge=44, le=520)
    backup_owner: str | None = Field(default=None, max_length=120)
    system: str | None = Field(default=None, max_length=160)
    vendor: str | None = Field(default=None, max_length=160)
    control_id: str | None = Field(default=None, max_length=100)
    policy_reference: str | None = Field(default=None, max_length=240)
    evidence_requirement: str | None = Field(default=None, max_length=500)
    segregation_rule: str | None = Field(default=None, max_length=500)
    risk_level: str = Field(default="none", pattern=r"^(none|low|medium|high|critical)$")
    data_classification: str = Field(
        default="internal",
        pattern=r"^(public|internal|confidential|restricted)$",
    )
    sla_minutes: int | None = Field(default=None, ge=1, le=5_256_000)
    review_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    required: bool = False
    layer: str = Field(default="Default", min_length=1, max_length=80)
    parent_id: str | None = Field(default=None, max_length=80)


class FlowEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=80)
    target: str = Field(min_length=1, max_length=80)
    label: str = Field(default="", max_length=120)
    is_loop: bool = False
    bidirectional: bool = False


class GraphWarning(BaseModel):
    code: str
    message: str
    node_ids: list[str] = Field(default_factory=list)


class FlowGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=160)
    nodes: list[FlowNode] = Field(min_length=1, max_length=200)
    edges: list[FlowEdge] = Field(default_factory=list, max_length=400)
    questions: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("nodes")
    @classmethod
    def unique_node_ids(cls, nodes: list[FlowNode]) -> list[FlowNode]:
        ids = [node.id for node in nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("Node IDs must be unique")
        return nodes


class PositionedNode(FlowNode):
    x: float
    y: float


class GeneratedFlowchart(BaseModel):
    title: str
    nodes: list[PositionedNode]
    edges: list[FlowEdge]
    questions: list[str]
    warnings: list[GraphWarning]


class GenerateFlowchartRequest(BaseModel):
    text: str = Field(min_length=3)
    title: str | None = Field(default=None, max_length=160)

    @field_validator("text")
    @classmethod
    def strip_text(cls, text: str) -> str:
        return text.strip()


class HealthResponse(BaseModel):
    status: str
    database_reachable: bool = True
    model: str
    model_server_reachable: bool
    realtime_mode: str
    realtime_server_reachable: bool
    job_queue_mode: str
    job_queue_reachable: bool
    storage_mode: str
    storage_reachable: bool
    rate_limit_mode: str
    rate_limit_reachable: bool


class BackgroundJobResponse(BaseModel):
    id: str
    kind: str
    status: str
    attempts: int
    max_attempts: int
    result: GeneratedFlowchart | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class ArtifactJobRequest(BaseModel):
    kind: Literal["export", "evidence_package", "operational_package"] = "export"
    format: Literal["svg", "json", "zip"] = "svg"

    @model_validator(mode="after")
    def validate_kind_format(self) -> "ArtifactJobRequest":
        if self.kind in {"evidence_package", "operational_package"} and self.format != "zip":
            raise ValueError("Evidence and operational packages must use zip format")
        if self.kind == "export" and self.format == "zip":
            raise ValueError("Flowchart exports must use svg or json format")
        return self


class ProcessEventInput(BaseModel):
    case_id: str = Field(min_length=1, max_length=160)
    activity: str = Field(min_length=1, max_length=240)
    occurred_at: datetime
    status: str | None = Field(default=None, max_length=80)
    owner: str | None = Field(default=None, max_length=160)
    cost: float | None = Field(default=None, ge=0, le=1_000_000_000)
    attributes: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class ProcessEventImportRequest(BaseModel):
    filename: str = Field(default="events.csv", min_length=1, max_length=240)
    activity_node_map: dict[str, str] = Field(default_factory=dict)
    events: list[ProcessEventInput] = Field(min_length=1, max_length=10_000)


class ProcessEventImportResponse(BaseModel):
    id: str
    filename: str
    event_count: int
    case_count: int
    mapped_event_count: int
    unmapped_activities: list[str]
    created_at: datetime


class ProcessNodeMetric(BaseModel):
    node_id: str
    count: int
    average_wait_seconds: float
    failure_count: int
    sla_breach_count: int
    total_cost: float


class ProcessEdgeMetric(BaseModel):
    source: str
    target: str
    count: int
    unexpected: bool = False


class ProcessInsightResponse(BaseModel):
    id: str
    kind: str
    severity: str
    title: str
    description: str
    node_id: str | None = None
    status: str
    evidence: dict = Field(default_factory=dict)
    detected_at: datetime
    resolved_at: datetime | None = None


class ProcessAnalyticsResponse(BaseModel):
    event_count: int
    case_count: int
    mapped_event_count: int
    conformance_rate: float
    average_case_cycle_seconds: float
    node_metrics: list[ProcessNodeMetric]
    edge_metrics: list[ProcessEdgeMetric]
    insights: list[ProcessInsightResponse]
    imports: list[ProcessEventImportResponse]


class ProcessImpactProject(BaseModel):
    project_id: str
    project_title: str
    node_id: str
    node_label: str
    dependency_type: str
    dependency_value: str


class ProcessImpactResponse(BaseModel):
    query: str
    matches: list[ProcessImpactProject]
    dependency_summary: dict[str, int]


class GeneratedArtifactResponse(BaseModel):
    id: str
    kind: str
    format: str
    filename: str
    content_type: str
    size_bytes: int
    download_url: str
    expires_at: datetime
    created_at: datetime


class ArtifactJobResponse(BaseModel):
    id: str
    status: str
    attempts: int
    max_attempts: int
    artifact: GeneratedArtifactResponse | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class ProjectProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(default="", max_length=20, pattern=r"^[A-Z0-9-]*$")
    sponsor_id: str | None = Field(default=None, max_length=36)
    department: str = Field(default="", max_length=120)
    team: str = Field(default="", max_length=120)
    program: str = Field(default="", max_length=160)
    priority: Literal["low", "medium", "high", "critical"] = "medium"
    health: Literal["unknown", "on_track", "at_risk", "off_track"] = "unknown"
    start_date: date | None = None
    target_date: date | None = None
    progress: int | None = Field(default=None, ge=0, le=100)
    classification: Literal["public", "internal", "confidential", "restricted"] = "internal"
    tags: list[str] = Field(default_factory=list, max_length=20)
    template: Literal[
        "blank", "software", "general", "research", "transformation", "infrastructure", "compliance"
    ] = "blank"

    @field_validator("key", mode="before")
    @classmethod
    def normalize_project_key(cls, value: object) -> str:
        return str(value or "").strip().upper()

    @field_validator("priority", "health", "classification", "template", mode="before")
    @classmethod
    def normalize_project_choice(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @model_validator(mode="after")
    def normalize_profile(self) -> "ProjectProfile":
        if self.start_date and self.target_date and self.start_date > self.target_date:
            raise ValueError("Project start date must be on or before its target date")
        self.department = self.department.strip()
        self.team = self.team.strip()
        self.program = self.program.strip()
        normalized_tags: list[str] = []
        seen_tags: set[str] = set()
        for source_tag in self.tags:
            tag = source_tag.strip()[:40]
            if tag and tag.casefold() not in seen_tags:
                normalized_tags.append(tag)
                seen_tags.add(tag.casefold())
        self.tags = normalized_tags
        return self


class ProjectWrite(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    graph: GeneratedFlowchart
    source_text: str = Field(default="", max_length=30_000)
    description: str = Field(default="", max_length=2_000)
    status: str = Field(default="active", max_length=20)
    owner_id: str | None = Field(default=None, max_length=36)
    collaborator_ids: list[str] = Field(default_factory=list, max_length=50)
    profile: ProjectProfile = Field(default_factory=ProjectProfile)

    @field_validator("description")
    @classmethod
    def strip_project_description(cls, value: str) -> str:
        return value.strip()

    @field_validator("status")
    @classmethod
    def validate_project_status(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"draft", "active", "archived"}:
            raise ValueError("Project status must be draft, active, or archived")
        return normalized

    @field_validator("collaborator_ids")
    @classmethod
    def unique_project_collaborators(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class ProjectResponse(ProjectWrite):
    id: str
    document_revision: int = 0
    created_at: datetime
    updated_at: datetime


class ProjectSummary(BaseModel):
    id: str
    title: str
    description: str = ""
    status: str = "active"
    profile: ProjectProfile = Field(default_factory=ProjectProfile)
    owner_id: str | None = None
    collaborator_count: int = 0
    deliverable_count: int = 0
    completed_deliverable_count: int = 0
    task_count: int = 0
    completed_task_count: int = 0
    plan_progress: int = 0
    created_at: datetime
    updated_at: datetime
    node_count: int = 0
    edge_count: int = 0


class AttachmentResponse(BaseModel):
    id: str
    project_id: str
    node_id: str | None
    filename: str
    content_type: str
    size_bytes: int
    uploaded_by_id: str
    upload_status: str = "complete"
    scan_status: str = "clean"
    scan_message: str | None = None
    created_at: datetime


class AttachmentUploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=240)
    node_id: str | None = Field(default=None, max_length=80)
    content_type: str = Field(default="application/octet-stream", min_length=1, max_length=160)
    size_bytes: int = Field(gt=0)


class AttachmentUploadGrant(BaseModel):
    method: str
    url: str
    fields: dict[str, str] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    expires_at: datetime | None = None


class AttachmentUploadResponse(BaseModel):
    attachment: AttachmentResponse
    upload: AttachmentUploadGrant


class LoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=1, max_length=128)
    mfa_code: str | None = Field(default=None, min_length=6, max_length=32)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class ProfileUpdate(BaseModel):
    display_name: str = Field(min_length=2, max_length=100)
    email: str = Field(min_length=5, max_length=320)

    @field_validator("display_name")
    @classmethod
    def strip_display_name(cls, value: str) -> str:
        return value.strip()

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("Enter a valid email address")
        return normalized


class UserResponse(BaseModel):
    id: str
    email: str
    display_name: str
    entity_id: str
    entity_name: str
    role: UserRole
    created_at: datetime
    mfa_enabled: bool = False
    mfa_required: bool = False
    security_status: Literal["compliant", "setup_required", "verification_required"] = "compliant"


class AuthenticationPolicyWrite(BaseModel):
    mfa_requirement: Literal["optional", "admins", "all"] = "optional"
    session_lifetime_hours: int = Field(default=720, ge=1, le=720)
    idle_timeout_minutes: int = Field(default=720, ge=5, le=10_080)


class MfaEnrollRequest(BaseModel):
    password: str = Field(min_length=1, max_length=128)


class MfaCodeRequest(BaseModel):
    code: str = Field(min_length=6, max_length=32)


class MfaDisableRequest(BaseModel):
    password: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=6, max_length=32)


class InternalAdminCreate(BaseModel):
    display_name: str = Field(min_length=2, max_length=100)
    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=12, max_length=128)

    @field_validator("display_name")
    @classmethod
    def strip_admin_name(cls, value: str) -> str:
        return value.strip()

    @field_validator("email")
    @classmethod
    def normalize_admin_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("Enter a valid email address")
        return normalized


class InternalEntityCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    admins: list[InternalAdminCreate] = Field(min_length=1, max_length=20)
    max_users: int = Field(default=100, ge=1, le=100_000)
    max_projects: int = Field(default=1_000, ge=1, le=10_000_000)
    max_storage_bytes: int = Field(default=10 * 1024 * 1024 * 1024, ge=1_048_576)
    max_monthly_generations: int = Field(default=1_000, ge=0, le=10_000_000)
    max_pending_generations: int = Field(default=20, ge=1, le=10_000)
    data_region: Literal[
        "us-central", "us-east", "us-west", "ca-central", "eu-central", "eu-west",
        "uk-south", "ap-southeast", "au-southeast",
    ] = "us-central"
    data_residency_locked: bool = False

    @field_validator("name")
    @classmethod
    def strip_entity_name(cls, value: str) -> str:
        return value.strip()

    @field_validator("admins")
    @classmethod
    def unique_admin_emails(cls, admins: list[InternalAdminCreate]) -> list[InternalAdminCreate]:
        emails = [admin.email for admin in admins]
        if len(emails) != len(set(emails)):
            raise ValueError("Admin email addresses must be unique")
        return admins


class InternalEntityUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    max_users: int | None = Field(default=None, ge=1, le=100_000)
    max_projects: int | None = Field(default=None, ge=1, le=10_000_000)
    max_storage_bytes: int | None = Field(default=None, ge=1_048_576)
    max_monthly_generations: int | None = Field(default=None, ge=0, le=10_000_000)
    max_pending_generations: int | None = Field(default=None, ge=1, le=10_000)
    data_region: Literal[
        "us-central", "us-east", "us-west", "ca-central", "eu-central", "eu-west",
        "uk-south", "ap-southeast", "au-southeast",
    ] | None = None
    data_residency_locked: bool | None = None

    @field_validator("name")
    @classmethod
    def strip_updated_entity_name(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class InternalAdminResponse(BaseModel):
    id: str
    display_name: str
    email: str
    role: UserRole
    created_at: datetime


class InternalEntityResponse(BaseModel):
    id: str
    name: str
    admins: list[InternalAdminResponse]
    max_users: int
    max_projects: int
    max_storage_bytes: int
    max_monthly_generations: int
    max_pending_generations: int
    data_region: str
    data_residency_locked: bool
    created_at: datetime


class UsageValue(BaseModel):
    used: int
    limit: int
    remaining: int


class EntityUsageResponse(BaseModel):
    entity_id: str
    period_start: datetime
    users: UsageValue
    projects: UsageValue
    storage_bytes: UsageValue
    monthly_generations: UsageValue
    pending_generations: UsageValue


class InvitationPreview(BaseModel):
    email: str
    display_name: str
    entity_name: str
    role: UserRole
    expires_at: datetime


class AcceptInvitationRequest(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=8, max_length=128)
