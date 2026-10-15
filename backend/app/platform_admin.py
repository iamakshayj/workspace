"""Enterprise policy, data governance, integrations, commercial, and operations APIs."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from ipaddress import ip_address
import json
import re
from secrets import token_urlsafe
from typing import Any, Literal
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import get_current_admin, get_current_user
from .config import Settings, get_settings
from .database import (
    ApiAccessToken,
    AuditEvent,
    BackgroundJob,
    DataGovernancePolicy,
    EncryptionKeyReference,
    Entity,
    FeatureEntitlement,
    IntegrationConnection,
    LegalHold,
    OperationalEvent,
    PolicyRule,
    ServiceObjective,
    SupportAccessGrant,
    User,
    WebhookSubscription,
    WebhookDelivery,
    get_session,
)
from .governance import record_audit_event
from .job_service import CONNECTOR_SYNC_JOB, WEBHOOK_DELIVERY_JOB, create_background_job
from .policy_engine import PolicyContext, evaluate_dlp, evaluate_policy
from .quota_service import entity_usage
from .secret_box import SecretBox


router = APIRouter(prefix="/platform", tags=["enterprise platform"])
POLICY_ACTIONS = {
    "read", "search", "preview", "comment", "mention", "create", "edit", "delete",
    "move", "upload", "manage", "share", "approve", "export", "download",
    "webhook.send", "ai.retrieve", "ai.summarize", "ai.send", "policy.manage", "integration.manage", "*",
}
RESOURCE_TYPES = {
    "*", "entity", "project", "work_item", "document", "message", "meeting", "file",
    "decision", "risk", "diagram", "search", "assistant", "export", "integration", "audit",
}
TOKEN_SCOPES = {
    "projects:read", "projects:write", "work:read", "work:write", "documents:read",
    "documents:write", "meetings:read", "meetings:write", "files:read", "files:write",
    "search:read", "webhooks:manage", "audit:read", "admin:read", "admin:write",
}
INTEGRATION_PROVIDERS = {
    "google_calendar", "microsoft_365", "slack", "zoom", "jira", "github",
    "salesforce", "sharepoint", "google_drive", "box", "custom",
}
DLP_DETECTORS = {"email", "us_ssn", "payment_card", "private_key", "credential"}


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.replace(tzinfo=value.tzinfo or timezone.utc).isoformat()


def expected_audit_hash(event: AuditEvent) -> str:
    created_at = event.created_at.replace(tzinfo=event.created_at.tzinfo or timezone.utc)
    canonical = json.dumps({
        "id": event.id, "entity_id": event.entity_id, "actor_id": event.actor_id,
        "action": event.action, "target_type": event.target_type, "target_id": event.target_id,
        "details": event.details or {}, "created_at": created_at.isoformat(),
        "previous_hash": event.previous_hash,
    }, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(canonical.encode("utf-8")).hexdigest()


SENSITIVE_CONTEXT_KEYS = {"password", "token", "secret", "authorization", "cookie", "credential", "api_key"}


def scrub_context(value: Any, depth: int = 0) -> Any:
    if depth >= 4:
        return "[truncated]"
    if isinstance(value, dict):
        clean = {}
        for key, item in list(value.items())[:25]:
            normalized = str(key).lower().replace("-", "_")
            if any(sensitive in normalized for sensitive in SENSITIVE_CONTEXT_KEYS):
                continue
            clean[str(key)[:80]] = scrub_context(item, depth + 1)
        return clean
    if isinstance(value, list):
        return [scrub_context(item, depth + 1) for item in value[:25]]
    if isinstance(value, str):
        return value[:500]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:500]


def safe_url(value: str, *, allow_local: bool = False) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme != "https" and not (allow_local and parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}):
        raise ValueError("URL must use HTTPS")
    if not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("URL must be an absolute HTTPS URL without embedded credentials or fragments")
    hostname = parsed.hostname.lower().rstrip(".")
    if not allow_local and (hostname == "localhost" or hostname.endswith(".local")):
        raise ValueError("URL cannot target a local network host")
    try:
        address = ip_address(hostname)
    except ValueError:
        address = None
    if address and not allow_local and not address.is_global:
        raise ValueError("URL cannot target a private, local, or reserved address")
    return value.strip()


class PolicyRuleWrite(BaseModel):
    name: str = Field(min_length=2, max_length=140)
    description: str = Field(default="", max_length=500)
    effect: Literal["allow", "deny"] = "deny"
    actions: list[str] = Field(min_length=1, max_length=40)
    subject_type: Literal["any", "user", "role", "group"] = "role"
    subject_id: str | None = Field(default=None, max_length=80)
    resource_type: str = Field(default="*", max_length=40)
    resource_id: str | None = Field(default=None, max_length=80)
    fields: list[str] = Field(default_factory=list, max_length=100)
    conditions: dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(default=100, ge=0, le=10_000)
    active: bool = True

    @model_validator(mode="after")
    def validate_rule(self) -> "PolicyRuleWrite":
        if not set(self.actions).issubset(POLICY_ACTIONS):
            raise ValueError("Policy contains an unsupported action")
        if self.resource_type not in RESOURCE_TYPES:
            raise ValueError("Policy contains an unsupported resource type")
        if self.subject_type != "any" and not self.subject_id:
            raise ValueError("A user, role, or group policy requires a subject")
        if self.subject_type == "role" and self.subject_id not in {"admin", "basic", "guest"}:
            raise ValueError("Unknown workspace role")
        self.actions = list(dict.fromkeys(self.actions))
        self.fields = list(dict.fromkeys(field.strip()[:80] for field in self.fields if field.strip()))
        return self


class PolicySimulation(BaseModel):
    user_id: str
    action: str
    resource_type: str
    resource_id: str | None = None
    project_id: str | None = None
    fields: list[str] = Field(default_factory=list, max_length=100)
    classification: Literal["public", "internal", "confidential", "restricted"] = "internal"
    source_type: str | None = Field(default=None, max_length=40)
    attributes: dict[str, Any] = Field(default_factory=dict)


class DataPolicyWrite(BaseModel):
    name: str = Field(min_length=2, max_length=140)
    kind: Literal["dlp", "retention", "classification", "residency"]
    applies_to: list[str] = Field(default_factory=list, max_length=40)
    classification: Literal["public", "internal", "confidential", "restricted"] = "internal"
    enforcement: Literal["audit", "warn", "block"] = "audit"
    configuration: dict[str, Any] = Field(default_factory=dict)
    active: bool = True

    @model_validator(mode="after")
    def validate_configuration(self) -> "DataPolicyWrite":
        if self.kind == "retention":
            days = self.configuration.get("retention_days")
            if not isinstance(days, int) or not 1 <= days <= 36_500:
                raise ValueError("Retention policies require retention_days between 1 and 36500")
        detectors = self.configuration.get("detectors")
        if detectors is not None and (
            not isinstance(detectors, list)
            or len(detectors) > 20
            or any(not isinstance(detector, str) for detector in detectors)
        ):
            raise ValueError("DLP detectors must be a list of at most 20 names")
        if detectors is not None and not set(detectors).issubset(DLP_DETECTORS):
            raise ValueError("DLP policy contains an unsupported detector")
        blocked_actions = self.configuration.get("blocked_actions")
        if blocked_actions is not None and (
            not isinstance(blocked_actions, list)
            or any(not isinstance(action, str) for action in blocked_actions)
            or not set(blocked_actions).issubset(POLICY_ACTIONS)
        ):
            raise ValueError("DLP policy contains an unsupported blocked action")
        if self.kind == "residency":
            regions = self.configuration.get("allowed_regions")
            if not isinstance(regions, list) or not regions or len(regions) > 20:
                raise ValueError("Residency policies require one or more allowed_regions")
            if any(not isinstance(region, str) or not re.fullmatch(r"[a-z0-9-]{2,40}", region) for region in regions):
                raise ValueError("Residency regions must use deployment region identifiers")
        self.applies_to = list(dict.fromkeys(value.strip()[:40] for value in self.applies_to if value.strip()))
        return self


class DlpSimulation(BaseModel):
    content: str = Field(min_length=1, max_length=1_000_000)
    source_type: str = Field(min_length=1, max_length=40)
    action: str = Field(min_length=1, max_length=40)
    classification: Literal["public", "internal", "confidential", "restricted"] = "internal"


class LegalHoldWrite(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    scope_type: Literal["entity", "project", "document", "message", "meeting", "file"] = "entity"
    scope_id: str | None = Field(default=None, max_length=80)
    reason: str = Field(min_length=3, max_length=10_000)

    @model_validator(mode="after")
    def validate_scope(self) -> "LegalHoldWrite":
        if self.scope_type != "entity" and not self.scope_id:
            raise ValueError("A scoped legal hold requires an object id")
        return self


class KeyReferenceWrite(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    provider: Literal["platform", "aws_kms", "azure_key_vault", "gcp_kms", "hashicorp_vault"] = "platform"
    key_reference: str = Field(min_length=3, max_length=1000)


class IntegrationWrite(BaseModel):
    name: str = Field(min_length=2, max_length=140)
    provider: str = Field(max_length=50)
    scopes: list[str] = Field(default_factory=list, max_length=100)
    credentials: dict[str, str] | None = None
    configuration: dict[str, Any] = Field(default_factory=dict)
    conflict_policy: Literal["source_wins", "workspace_wins", "newest_wins", "manual"] = "source_wins"

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, value: str) -> str:
        if value not in INTEGRATION_PROVIDERS:
            raise ValueError("Unsupported integration provider")
        return value

    @field_validator("credentials")
    @classmethod
    def bound_credentials(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        if value and (len(value) > 30 or any(len(str(item)) > 10_000 for item in value.values())):
            raise ValueError("Integration credentials are too large")
        return value


class WebhookWrite(BaseModel):
    name: str = Field(min_length=2, max_length=140)
    target_url: str = Field(max_length=1000)
    event_types: list[str] = Field(min_length=1, max_length=100)

    @field_validator("target_url")
    @classmethod
    def validate_target_url(cls, value: str) -> str:
        return safe_url(value)

    @field_validator("event_types")
    @classmethod
    def validate_event_types(cls, values: list[str]) -> list[str]:
        pattern = re.compile(r"^(?:\*|[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*(?:\.\*)?)$")
        if any(not pattern.fullmatch(value) for value in values):
            raise ValueError("Webhook event types must be exact names, namespace wildcards, or *")
        return list(dict.fromkeys(values))


class WebhookTestWrite(BaseModel):
    event_type: str = Field(default="workspace.test", min_length=3, max_length=100)


class TokenWrite(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    scopes: list[str] = Field(min_length=1, max_length=30)
    expires_in_days: int | None = Field(default=90, ge=1, le=365)

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, value: list[str]) -> list[str]:
        if not set(value).issubset(TOKEN_SCOPES):
            raise ValueError("Token contains an unsupported scope")
        return list(dict.fromkeys(value))


class SupportAccessWrite(BaseModel):
    requested_for: str = Field(min_length=3, max_length=320)
    reason: str = Field(min_length=10, max_length=10_000)
    scopes: list[Literal["diagnostics:read", "configuration:read", "data:read", "data:repair"]] = Field(min_length=1, max_length=4)
    duration_hours: int = Field(default=4, ge=1, le=24)


class SupportDecision(BaseModel):
    decision: Literal["approved", "denied", "revoked"]
    duration_hours: int = Field(default=4, ge=1, le=24)


class EntitlementWrite(BaseModel):
    enabled: bool = True
    limit_value: int | None = Field(default=None, ge=0)
    configuration: dict[str, Any] = Field(default_factory=dict)
    starts_at: datetime | None = None
    ends_at: datetime | None = None

    @model_validator(mode="after")
    def validate_dates(self) -> "EntitlementWrite":
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValueError("Entitlement end must follow its start")
        return self


class OperationalEventWrite(BaseModel):
    service: str = Field(min_length=2, max_length=60)
    severity: Literal["info", "warning", "error", "critical"] = "error"
    fingerprint: str = Field(min_length=4, max_length=128)
    message: str = Field(min_length=1, max_length=1000)
    context: dict[str, Any] = Field(default_factory=dict)


class ObjectiveWrite(BaseModel):
    service: str = Field(min_length=2, max_length=60)
    metric: Literal["availability", "latency_p95_ms", "error_rate", "queue_age_seconds", "sync_lag_seconds"]
    target: float = Field(gt=0)
    window_days: int = Field(default=30, ge=1, le=365)
    warning_threshold: float = Field(default=0.8, gt=0, le=1)
    active: bool = True


def serialize_policy(item: PolicyRule) -> dict[str, Any]:
    return {name: getattr(item, name) for name in (
        "id", "name", "description", "effect", "actions", "subject_type", "subject_id",
        "resource_type", "resource_id", "fields", "conditions", "priority", "active",
    )} | {"created_at": iso(item.created_at), "updated_at": iso(item.updated_at)}


def serialize_data_policy(item: DataGovernancePolicy) -> dict[str, Any]:
    return {name: getattr(item, name) for name in (
        "id", "name", "kind", "applies_to", "classification", "enforcement", "configuration", "active",
    )} | {"created_at": iso(item.created_at), "updated_at": iso(item.updated_at)}


def serialize_integration(item: IntegrationConnection) -> dict[str, Any]:
    return {name: getattr(item, name) for name in (
        "id", "name", "provider", "status", "scopes", "configuration", "conflict_policy",
        "failure_count", "last_error",
    )} | {
        "credential_configured": bool(item.credentials_encrypted), "last_sync_at": iso(item.last_sync_at),
        "next_sync_at": iso(item.next_sync_at), "created_at": iso(item.created_at), "updated_at": iso(item.updated_at),
    }


async def validate_residency_policy(
    session: AsyncSession,
    entity_id: str,
    payload: DataPolicyWrite,
) -> None:
    if payload.kind != "residency" or not payload.active or payload.enforcement != "block":
        return
    entity = await session.get(Entity, entity_id)
    allowed_regions = payload.configuration.get("allowed_regions", [])
    if not entity or entity.data_region not in allowed_regions:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "residency_region_conflict",
                "message": "The enforced residency policy must include the workspace data region.",
                "workspace_region": entity.data_region if entity else None,
            },
        )


@router.get("/overview")
async def platform_overview(
    user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    entity = await session.get(Entity, user.entity_id)
    usage = await entity_usage(session, user.entity_id)
    policies = list(await session.scalars(select(PolicyRule).where(PolicyRule.entity_id == user.entity_id).order_by(PolicyRule.priority.desc())))
    data_policies = list(await session.scalars(select(DataGovernancePolicy).where(DataGovernancePolicy.entity_id == user.entity_id).order_by(DataGovernancePolicy.kind, DataGovernancePolicy.name)))
    holds = list(await session.scalars(select(LegalHold).where(LegalHold.entity_id == user.entity_id).order_by(LegalHold.created_at.desc())))
    keys = list(await session.scalars(select(EncryptionKeyReference).where(EncryptionKeyReference.entity_id == user.entity_id).order_by(EncryptionKeyReference.created_at.desc())))
    integrations = list(await session.scalars(select(IntegrationConnection).where(IntegrationConnection.entity_id == user.entity_id).order_by(IntegrationConnection.name)))
    webhooks = list(await session.scalars(select(WebhookSubscription).where(WebhookSubscription.entity_id == user.entity_id).order_by(WebhookSubscription.created_at.desc())))
    deliveries = list(await session.scalars(select(WebhookDelivery).where(WebhookDelivery.entity_id == user.entity_id).order_by(WebhookDelivery.created_at.desc()).limit(100)))
    tokens = list(await session.scalars(select(ApiAccessToken).where(ApiAccessToken.entity_id == user.entity_id).order_by(ApiAccessToken.created_at.desc())))
    support = list(await session.scalars(select(SupportAccessGrant).where(SupportAccessGrant.entity_id == user.entity_id).order_by(SupportAccessGrant.created_at.desc())))
    entitlements = list(await session.scalars(select(FeatureEntitlement).where(FeatureEntitlement.entity_id == user.entity_id).order_by(FeatureEntitlement.feature)))
    incidents = list(await session.scalars(select(OperationalEvent).where(OperationalEvent.entity_id == user.entity_id).order_by(OperationalEvent.last_seen_at.desc()).limit(200)))
    objectives = list(await session.scalars(select(ServiceObjective).where(ServiceObjective.entity_id == user.entity_id).order_by(ServiceObjective.service, ServiceObjective.metric)))
    job_counts = dict((await session.execute(select(BackgroundJob.status, func.count(BackgroundJob.id)).where(BackgroundJob.entity_id == user.entity_id).group_by(BackgroundJob.status))).all())
    return {
        "workspace": {
            "id": entity.id, "name": entity.name, "data_region": entity.data_region,
            "data_residency_locked": entity.data_residency_locked,
            "usage": {"users": usage.users + usage.pending_invitations, "projects": usage.projects, "storage_bytes": usage.storage_bytes},
            "limits": {"users": entity.max_users, "projects": entity.max_projects, "storage_bytes": entity.max_storage_bytes},
        },
        "policies": [serialize_policy(item) for item in policies],
        "data_policies": [serialize_data_policy(item) for item in data_policies],
        "legal_holds": [{"id": item.id, "name": item.name, "scope_type": item.scope_type, "scope_id": item.scope_id, "reason": item.reason, "status": item.status, "created_at": iso(item.created_at), "released_at": iso(item.released_at)} for item in holds],
        "encryption_keys": [{"id": item.id, "name": item.name, "provider": item.provider, "key_reference": item.key_reference, "status": item.status, "is_primary": item.is_primary, "last_verified_at": iso(item.last_verified_at)} for item in keys],
        "integrations": [serialize_integration(item) for item in integrations],
        "webhooks": [{"id": item.id, "name": item.name, "target_url": item.target_url, "event_types": item.event_types, "status": item.status, "failure_count": item.failure_count, "last_delivery_at": iso(item.last_delivery_at), "last_status_code": item.last_status_code} for item in webhooks],
        "webhook_deliveries": [{"id": item.id, "subscription_id": item.subscription_id, "event_id": item.event_id, "event_type": item.event_type, "status": item.status, "attempts": item.attempts, "status_code": item.status_code, "next_attempt_at": iso(item.next_attempt_at), "delivered_at": iso(item.delivered_at), "created_at": iso(item.created_at)} for item in deliveries],
        "api_tokens": [{"id": item.id, "name": item.name, "token_prefix": item.token_prefix, "scopes": item.scopes, "expires_at": iso(item.expires_at), "last_used_at": iso(item.last_used_at), "revoked_at": iso(item.revoked_at), "created_at": iso(item.created_at)} for item in tokens],
        "support_access": [{"id": item.id, "requested_for": item.requested_for, "reason": item.reason, "scopes": item.scopes, "status": item.status, "expires_at": iso(item.expires_at), "revoked_at": iso(item.revoked_at), "created_at": iso(item.created_at)} for item in support],
        "entitlements": [{"id": item.id, "feature": item.feature, "enabled": item.enabled, "limit_value": item.limit_value, "configuration": item.configuration, "starts_at": iso(item.starts_at), "ends_at": iso(item.ends_at)} for item in entitlements],
        "operations": {
            "jobs": job_counts,
            "open_incidents": sum(item.status == "open" for item in incidents),
            "degraded_integrations": sum(item.status in {"degraded", "error"} for item in integrations),
            "incidents": [{"id": item.id, "service": item.service, "severity": item.severity, "fingerprint": item.fingerprint, "message": item.message, "context": item.context, "occurrence_count": item.occurrence_count, "status": item.status, "first_seen_at": iso(item.first_seen_at), "last_seen_at": iso(item.last_seen_at), "resolved_at": iso(item.resolved_at)} for item in incidents],
            "objectives": [{"id": item.id, "service": item.service, "metric": item.metric, "target": item.target, "window_days": item.window_days, "warning_threshold": item.warning_threshold, "active": item.active} for item in objectives],
        },
    }


@router.post("/policies", status_code=status.HTTP_201_CREATED)
async def create_policy(payload: PolicyRuleWrite, user: User = Depends(get_current_admin), session: AsyncSession = Depends(get_session)) -> dict:
    item = PolicyRule(entity_id=user.entity_id, created_by_id=user.id, **payload.model_dump())
    session.add(item); await session.flush()
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="policy.created", target_type="policy", target_id=item.id, details={"effect": item.effect, "actions": item.actions, "resource_type": item.resource_type})
    await session.commit(); await session.refresh(item)
    return serialize_policy(item)


@router.put("/policies/{policy_id}")
async def update_policy(policy_id: str, payload: PolicyRuleWrite, user: User = Depends(get_current_admin), session: AsyncSession = Depends(get_session)) -> dict:
    item = await session.get(PolicyRule, policy_id)
    if not item or item.entity_id != user.entity_id: raise HTTPException(status_code=404, detail="Policy not found")
    for key, value in payload.model_dump().items(): setattr(item, key, value)
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="policy.updated", target_type="policy", target_id=item.id, details={"active": item.active})
    await session.commit(); await session.refresh(item)
    return serialize_policy(item)


@router.delete("/policies/{policy_id}", status_code=204)
async def delete_policy(policy_id: str, user: User = Depends(get_current_admin), session: AsyncSession = Depends(get_session)) -> None:
    item = await session.get(PolicyRule, policy_id)
    if not item or item.entity_id != user.entity_id: raise HTTPException(status_code=404, detail="Policy not found")
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="policy.deleted", target_type="policy", target_id=item.id)
    await session.delete(item); await session.commit()


@router.post("/policies/simulate")
async def simulate_policy(payload: PolicySimulation, user: User = Depends(get_current_admin), session: AsyncSession = Depends(get_session)) -> dict:
    subject = await session.get(User, payload.user_id)
    if not subject or subject.entity_id != user.entity_id: raise HTTPException(status_code=404, detail="Policy subject not found")
    decision = await evaluate_policy(session, subject, PolicyContext(
        action=payload.action, resource_type=payload.resource_type, resource_id=payload.resource_id,
        project_id=payload.project_id, fields=set(payload.fields), classification=payload.classification,
        source_type=payload.source_type, attributes=payload.attributes,
    ))
    return {"subject": {"id": subject.id, "display_name": subject.display_name, "role": subject.role}, "decision": decision.as_dict()}


@router.post("/data-policies", status_code=201)
async def create_data_policy(payload: DataPolicyWrite, user: User = Depends(get_current_admin), session: AsyncSession = Depends(get_session)) -> dict:
    await validate_residency_policy(session, user.entity_id, payload)
    item = DataGovernancePolicy(entity_id=user.entity_id, created_by_id=user.id, **payload.model_dump())
    session.add(item)
    try: await session.flush()
    except IntegrityError as error: raise HTTPException(status_code=409, detail="A data policy with this name already exists") from error
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="data_policy.created", target_type="data_policy", target_id=item.id, details={"kind": item.kind, "enforcement": item.enforcement})
    await session.commit(); await session.refresh(item)
    return serialize_data_policy(item)


@router.put("/data-policies/{policy_id}")
async def update_data_policy(policy_id: str, payload: DataPolicyWrite, user: User = Depends(get_current_admin), session: AsyncSession = Depends(get_session)) -> dict:
    item = await session.get(DataGovernancePolicy, policy_id)
    if not item or item.entity_id != user.entity_id: raise HTTPException(status_code=404, detail="Data policy not found")
    await validate_residency_policy(session, user.entity_id, payload)
    for key, value in payload.model_dump().items(): setattr(item, key, value)
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="data_policy.updated", target_type="data_policy", target_id=item.id, details={"active": item.active})
    await session.commit(); await session.refresh(item)
    return serialize_data_policy(item)


@router.post("/data-policies/simulate")
async def simulate_dlp(payload: DlpSimulation, user: User = Depends(get_current_admin), session: AsyncSession = Depends(get_session)) -> dict:
    return (await evaluate_dlp(session, user, **payload.model_dump())).as_dict()


@router.post("/legal-holds", status_code=201)
async def create_legal_hold(payload: LegalHoldWrite, user: User = Depends(get_current_admin), session: AsyncSession = Depends(get_session)) -> dict:
    item = LegalHold(entity_id=user.entity_id, created_by_id=user.id, **payload.model_dump())
    session.add(item); await session.flush()
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="legal_hold.created", target_type="legal_hold", target_id=item.id, details={"scope_type": item.scope_type, "scope_id": item.scope_id})
    await session.commit(); return {"id": item.id, "status": item.status}


@router.post("/legal-holds/{hold_id}/release")
async def release_legal_hold(hold_id: str, user: User = Depends(get_current_admin), session: AsyncSession = Depends(get_session)) -> dict:
    item = await session.get(LegalHold, hold_id)
    if not item or item.entity_id != user.entity_id: raise HTTPException(status_code=404, detail="Legal hold not found")
    if item.status != "active": raise HTTPException(status_code=409, detail="Legal hold is already released")
    item.status = "released"; item.released_by_id = user.id; item.released_at = datetime.now(timezone.utc)
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="legal_hold.released", target_type="legal_hold", target_id=item.id)
    await session.commit(); return {"id": item.id, "status": item.status, "released_at": iso(item.released_at)}


@router.post("/encryption-keys", status_code=201)
async def create_key_reference(payload: KeyReferenceWrite, user: User = Depends(get_current_admin), session: AsyncSession = Depends(get_session)) -> dict:
    item = EncryptionKeyReference(entity_id=user.entity_id, created_by_id=user.id, **payload.model_dump())
    session.add(item)
    try: await session.flush()
    except IntegrityError as error: raise HTTPException(status_code=409, detail="An encryption key with this name already exists") from error
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="encryption_key.registered", target_type="encryption_key", target_id=item.id, details={"provider": item.provider})
    await session.commit(); return {"id": item.id, "status": item.status}


@router.post("/encryption-keys/{key_id}/verify")
async def verify_key_reference(key_id: str, user: User = Depends(get_current_admin), session: AsyncSession = Depends(get_session)) -> dict:
    item = await session.get(EncryptionKeyReference, key_id)
    if not item or item.entity_id != user.entity_id: raise HTTPException(status_code=404, detail="Encryption key not found")
    item.status = "verified" if item.provider == "platform" else "pending_external_verification"
    item.last_verified_at = datetime.now(timezone.utc) if item.provider == "platform" else None
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="encryption_key.verification_requested", target_type="encryption_key", target_id=item.id, details={"result": item.status})
    await session.commit(); return {"id": item.id, "status": item.status, "operationally_pending": item.provider != "platform"}


@router.post("/integrations", status_code=201)
async def create_integration(payload: IntegrationWrite, user: User = Depends(get_current_admin), session: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings)) -> dict:
    item_id = str(uuid4())
    encrypted = SecretBox(settings.auth_secret).encrypt(json.dumps(payload.credentials, sort_keys=True), f"integration:{item_id}") if payload.credentials else None
    values = payload.model_dump(exclude={"credentials"})
    item = IntegrationConnection(id=item_id, entity_id=user.entity_id, created_by_id=user.id, credentials_encrypted=encrypted, status="configured" if encrypted else "draft", **values)
    session.add(item)
    try: await session.flush()
    except IntegrityError as error: raise HTTPException(status_code=409, detail="An integration with this name already exists") from error
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="integration.created", target_type="integration", target_id=item.id, details={"provider": item.provider, "scopes": item.scopes})
    await session.commit(); await session.refresh(item); return serialize_integration(item)


@router.post("/integrations/{integration_id}/sync", status_code=202)
async def sync_integration(integration_id: str, user: User = Depends(get_current_admin), session: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings)) -> dict:
    item = await session.get(IntegrationConnection, integration_id)
    if not item or item.entity_id != user.entity_id: raise HTTPException(status_code=404, detail="Integration not found")
    if item.status == "disconnected": raise HTTPException(status_code=409, detail="Reconnect the integration before syncing")
    if not item.credentials_encrypted and item.provider != "custom": raise HTTPException(status_code=409, detail="Integration credentials are not configured")
    item.status = "syncing"; item.last_error = ""; await session.commit()
    job = await create_background_job(entity_id=user.entity_id, created_by_id=user.id, kind=CONNECTOR_SYNC_JOB, payload={"integration_id": item.id}, settings=settings)
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="integration.sync_requested", target_type="integration", target_id=item.id, details={"job_id": job.id})
    await session.commit(); return {"job_id": job.id, "status": job.status}


@router.post("/integrations/{integration_id}/disconnect")
async def disconnect_integration(integration_id: str, user: User = Depends(get_current_admin), session: AsyncSession = Depends(get_session)) -> dict:
    item = await session.get(IntegrationConnection, integration_id)
    if not item or item.entity_id != user.entity_id: raise HTTPException(status_code=404, detail="Integration not found")
    item.status = "disconnected"; item.credentials_encrypted = None; item.sync_cursor = None; item.next_sync_at = None
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="integration.disconnected", target_type="integration", target_id=item.id)
    await session.commit(); return serialize_integration(item)


@router.post("/webhooks", status_code=201)
async def create_webhook(payload: WebhookWrite, user: User = Depends(get_current_admin), session: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings)) -> dict:
    item_id = str(uuid4()); signing_secret = token_urlsafe(32)
    item = WebhookSubscription(id=item_id, entity_id=user.entity_id, name=payload.name, target_url=payload.target_url, event_types=list(dict.fromkeys(payload.event_types)), signing_secret_encrypted=SecretBox(settings.auth_secret).encrypt(signing_secret, f"webhook:{item_id}"), created_by_id=user.id)
    session.add(item); await session.flush()
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="webhook.created", target_type="webhook", target_id=item.id, details={"event_types": item.event_types})
    await session.commit(); return {"id": item.id, "name": item.name, "target_url": item.target_url, "event_types": item.event_types, "signing_secret": signing_secret, "status": item.status}


@router.post("/webhooks/{webhook_id}/disable")
async def disable_webhook(webhook_id: str, user: User = Depends(get_current_admin), session: AsyncSession = Depends(get_session)) -> dict:
    item = await session.get(WebhookSubscription, webhook_id)
    if not item or item.entity_id != user.entity_id: raise HTTPException(status_code=404, detail="Webhook not found")
    item.status = "disabled"
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="webhook.disabled", target_type="webhook", target_id=item.id)
    await session.commit(); return {"id": item.id, "status": item.status}


@router.post("/webhooks/{webhook_id}/test", status_code=202)
async def test_webhook(webhook_id: str, payload: WebhookTestWrite, user: User = Depends(get_current_admin), session: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings)) -> dict:
    subscription = await session.get(WebhookSubscription, webhook_id)
    if not subscription or subscription.entity_id != user.entity_id: raise HTTPException(status_code=404, detail="Webhook not found")
    if subscription.status != "active": raise HTTPException(status_code=409, detail="Webhook is disabled")
    event_id = str(uuid4())
    delivery = WebhookDelivery(
        entity_id=user.entity_id, subscription_id=subscription.id, event_id=event_id,
        event_type=payload.event_type, payload={"id": event_id, "type": payload.event_type, "occurred_at": iso(datetime.now(timezone.utc)), "data": {"test": True}},
    )
    session.add(delivery); await session.commit(); await session.refresh(delivery)
    job = await create_background_job(entity_id=user.entity_id, created_by_id=user.id, kind=WEBHOOK_DELIVERY_JOB, payload={"delivery_id": delivery.id}, settings=settings)
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="webhook.test_requested", target_type="webhook", target_id=subscription.id, details={"event_id": event_id, "job_id": job.id})
    await session.commit()
    return {"delivery_id": delivery.id, "event_id": event_id, "job_id": job.id, "status": delivery.status}


@router.post("/api-tokens", status_code=201)
async def create_api_token(payload: TokenWrite, user: User = Depends(get_current_admin), session: AsyncSession = Depends(get_session)) -> dict:
    raw = f"wsp_{token_urlsafe(36)}"; digest = sha256(raw.encode()).hexdigest()
    item = ApiAccessToken(entity_id=user.entity_id, name=payload.name, token_prefix=raw[:12], token_hash=digest, scopes=payload.scopes, created_by_id=user.id, expires_at=datetime.now(timezone.utc) + timedelta(days=payload.expires_in_days) if payload.expires_in_days else None)
    session.add(item); await session.flush()
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="api_token.created", target_type="api_token", target_id=item.id, details={"scopes": item.scopes, "expires_at": iso(item.expires_at)})
    await session.commit(); return {"id": item.id, "name": item.name, "token": raw, "token_prefix": item.token_prefix, "scopes": item.scopes, "expires_at": iso(item.expires_at)}


@router.post("/api-tokens/{token_id}/revoke")
async def revoke_api_token(token_id: str, user: User = Depends(get_current_admin), session: AsyncSession = Depends(get_session)) -> dict:
    item = await session.get(ApiAccessToken, token_id)
    if not item or item.entity_id != user.entity_id: raise HTTPException(status_code=404, detail="API token not found")
    item.revoked_at = item.revoked_at or datetime.now(timezone.utc)
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="api_token.revoked", target_type="api_token", target_id=item.id)
    await session.commit(); return {"id": item.id, "revoked_at": iso(item.revoked_at)}


@router.post("/support-access", status_code=201)
async def request_support_access(payload: SupportAccessWrite, user: User = Depends(get_current_admin), session: AsyncSession = Depends(get_session)) -> dict:
    item = SupportAccessGrant(entity_id=user.entity_id, requested_for=payload.requested_for, reason=payload.reason, scopes=payload.scopes, requested_by_id=user.id, expires_at=datetime.now(timezone.utc) + timedelta(hours=payload.duration_hours))
    session.add(item); await session.flush()
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="support_access.requested", target_type="support_access", target_id=item.id, details={"scopes": item.scopes, "requested_for": item.requested_for})
    await session.commit(); return {"id": item.id, "status": item.status, "expires_at": iso(item.expires_at)}


@router.put("/support-access/{grant_id}")
async def decide_support_access(grant_id: str, payload: SupportDecision, user: User = Depends(get_current_admin), session: AsyncSession = Depends(get_session)) -> dict:
    item = await session.get(SupportAccessGrant, grant_id)
    if not item or item.entity_id != user.entity_id: raise HTTPException(status_code=404, detail="Support access request not found")
    now = datetime.now(timezone.utc)
    if payload.decision == "approved": item.status = "approved"; item.approved_by_id = user.id; item.expires_at = now + timedelta(hours=payload.duration_hours); item.revoked_at = None
    elif payload.decision == "revoked": item.status = "revoked"; item.revoked_at = now
    else: item.status = "denied"; item.revoked_at = now
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action=f"support_access.{payload.decision}", target_type="support_access", target_id=item.id, details={"expires_at": iso(item.expires_at)})
    await session.commit(); return {"id": item.id, "status": item.status, "expires_at": iso(item.expires_at), "revoked_at": iso(item.revoked_at)}


@router.put("/entitlements/{feature}")
async def save_entitlement(feature: str, payload: EntitlementWrite, user: User = Depends(get_current_admin), session: AsyncSession = Depends(get_session)) -> dict:
    if not re.fullmatch(r"[a-z][a-z0-9_.-]{1,79}", feature): raise HTTPException(status_code=422, detail="Invalid feature key")
    item = await session.scalar(select(FeatureEntitlement).where(FeatureEntitlement.entity_id == user.entity_id, FeatureEntitlement.feature == feature))
    if not item: item = FeatureEntitlement(entity_id=user.entity_id, feature=feature, updated_by_id=user.id); session.add(item)
    for key, value in payload.model_dump().items(): setattr(item, key, value)
    item.updated_by_id = user.id
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="entitlement.updated", target_type="entitlement", target_id=feature, details={"enabled": item.enabled, "limit_value": item.limit_value})
    await session.commit(); await session.refresh(item)
    return {"feature": item.feature, "enabled": item.enabled, "limit_value": item.limit_value, "configuration": item.configuration, "starts_at": iso(item.starts_at), "ends_at": iso(item.ends_at)}


@router.post("/operational-events", status_code=202)
async def record_operational_event(payload: OperationalEventWrite, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> dict:
    now = datetime.now(timezone.utc)
    item = await session.scalar(select(OperationalEvent).where(OperationalEvent.entity_id == user.entity_id, OperationalEvent.fingerprint == payload.fingerprint, OperationalEvent.status == "open"))
    safe_context = scrub_context(payload.context)
    if item:
        item.occurrence_count += 1; item.last_seen_at = now; item.message = payload.message; item.severity = payload.severity; item.context = safe_context
    else:
        item = OperationalEvent(entity_id=user.entity_id, service=payload.service, severity=payload.severity, fingerprint=payload.fingerprint, message=payload.message, context=safe_context, first_seen_at=now, last_seen_at=now); session.add(item)
    await session.commit(); await session.refresh(item)
    return {"id": item.id, "occurrence_count": item.occurrence_count}


@router.post("/operational-events/{event_id}/resolve")
async def resolve_operational_event(event_id: str, user: User = Depends(get_current_admin), session: AsyncSession = Depends(get_session)) -> dict:
    item = await session.get(OperationalEvent, event_id)
    if not item or item.entity_id != user.entity_id: raise HTTPException(status_code=404, detail="Operational event not found")
    item.status = "resolved"; item.resolved_at = datetime.now(timezone.utc)
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="operational_event.resolved", target_type="operational_event", target_id=item.id)
    await session.commit(); return {"id": item.id, "status": item.status, "resolved_at": iso(item.resolved_at)}


@router.put("/service-objectives/{service}/{metric}")
async def save_service_objective(service: str, metric: str, payload: ObjectiveWrite, user: User = Depends(get_current_admin), session: AsyncSession = Depends(get_session)) -> dict:
    if service != payload.service or metric != payload.metric: raise HTTPException(status_code=422, detail="Objective path and payload must match")
    item = await session.scalar(select(ServiceObjective).where(ServiceObjective.entity_id == user.entity_id, ServiceObjective.service == service, ServiceObjective.metric == metric))
    if not item: item = ServiceObjective(entity_id=user.entity_id, service=service, metric=metric, target=payload.target, updated_by_id=user.id); session.add(item)
    for key, value in payload.model_dump().items(): setattr(item, key, value)
    item.updated_by_id = user.id
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="service_objective.updated", target_type="service_objective", target_id=item.id, details={"service": service, "metric": metric, "target": item.target})
    await session.commit(); await session.refresh(item)
    return {"id": item.id, "service": item.service, "metric": item.metric, "target": item.target, "window_days": item.window_days, "warning_threshold": item.warning_threshold, "active": item.active}


@router.get("/compliance/evidence")
async def compliance_evidence(
    user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Summarize repository-backed evidence without claiming external certification."""
    counts = {}
    for key, model in {
        "policy_rules": PolicyRule,
        "data_policies": DataGovernancePolicy,
        "legal_holds": LegalHold,
        "encryption_keys": EncryptionKeyReference,
        "integrations": IntegrationConnection,
        "webhooks": WebhookSubscription,
        "api_tokens": ApiAccessToken,
        "service_objectives": ServiceObjective,
        "audit_events": AuditEvent,
    }.items():
        counts[key] = int(await session.scalar(select(func.count(model.id)).where(model.entity_id == user.entity_id)) or 0)
    chain = list(await session.scalars(select(AuditEvent).where(
        AuditEvent.entity_id == user.entity_id,
        AuditEvent.event_hash.is_not(None),
    ).order_by(AuditEvent.created_at, AuditEvent.id)))
    previous = None
    chain_valid = True
    for event in chain:
        if event.previous_hash != previous or event.event_hash != expected_audit_hash(event):
            chain_valid = False
            break
        previous = event.event_hash
    controls = [
        {"control": "tenant_isolation", "status": "implemented", "evidence": "entity-scoped queries and service-token tenant checks"},
        {"control": "central_authorization", "status": "implemented", "evidence": f"{counts['policy_rules']} policy rules with deny precedence and simulation"},
        {"control": "data_protection", "status": "implemented", "evidence": f"{counts['data_policies']} DLP, classification, retention, or residency policies"},
        {"control": "legal_preservation", "status": "implemented", "evidence": f"{counts['legal_holds']} legal hold records"},
        {"control": "tamper_evident_audit", "status": "implemented" if chain_valid else "attention_required", "evidence": f"{len(chain)} chained audit records"},
        {"control": "encryption_key_inventory", "status": "implemented", "evidence": f"{counts['encryption_keys']} registered key references"},
        {"control": "scoped_machine_access", "status": "implemented", "evidence": f"{counts['api_tokens']} hashed, revocable API token records"},
        {"control": "availability_targets", "status": "implemented", "evidence": f"{counts['service_objectives']} service objectives"},
    ]
    return {
        "generated_at": iso(datetime.now(timezone.utc)),
        "workspace_id": user.entity_id,
        "controls": controls,
        "counts": counts,
        "operational_validation_pending": [
            "independent penetration test", "SOC 2 / ISO audit", "production restore exercise",
            "regional deployment and residency verification", "external KMS verification",
            "vendor connector certification", "high-volume soak and failover exercise",
        ],
        "certification_claimed": False,
    }


@router.get("/compliance/siem-export")
async def siem_export(
    user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
    action: str | None = Query(default=None, max_length=120),
    after: datetime | None = None,
    limit: int = Query(default=10_000, ge=1, le=100_000),
) -> StreamingResponse:
    query = select(AuditEvent).where(AuditEvent.entity_id == user.entity_id)
    if action:
        query = query.where(AuditEvent.action == action)
    if after:
        query = query.where(AuditEvent.created_at >= after)
    events = list(await session.scalars(query.order_by(AuditEvent.created_at, AuditEvent.id).limit(limit)))
    lines = []
    for event in events:
        lines.append(json.dumps({
            "event_id": event.id,
            "timestamp": iso(event.created_at),
            "workspace_id": event.entity_id,
            "actor_id": event.actor_id,
            "action": event.action,
            "object": {"type": event.target_type, "id": event.target_id},
            "project_id": event.project_id,
            "request_id": event.request_id,
            "details": event.details or {},
            "integrity": {"previous_hash": event.previous_hash, "event_hash": event.event_hash},
        }, sort_keys=True, separators=(",", ":"), default=str))
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="audit.siem_exported", target_type="entity", target_id=user.entity_id, details={"event_count": len(events), "filter_action": action})
    await session.commit()
    body = "\n".join(lines) + ("\n" if lines else "")
    return StreamingResponse(iter([body]), media_type="application/x-ndjson", headers={
        "Content-Disposition": "attachment; filename=workspace-siem.ndjson",
        "X-Exported-Event-Count": str(len(events)),
    })
