"""Canonical tenant authorization, data-loss prevention, and entitlement decisions.

Feature modules keep ownership of object lookup and mutation semantics. This module owns
the final policy decision so REST, GraphQL, search, AI, export, and worker paths can use
the same deny-by-default vocabulary and produce explainable decisions.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
from typing import Any, Iterable

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .database import (
    DataGovernancePolicy,
    FeatureEntitlement,
    LegalHold,
    OrganizationUnitMember,
    PolicyRule,
    Project,
    User,
)
from .governance import project_access_role


READ_ACTIONS = {"read", "search", "preview", "ai.retrieve", "ai.summarize"}
COMMENT_ACTIONS = {"comment", "mention"}
EDIT_ACTIONS = {"create", "edit", "delete", "move", "upload"}
MANAGE_ACTIONS = {"manage", "share", "approve", "policy.manage", "integration.manage"}
EGRESS_ACTIONS = {"export", "download", "webhook.send", "ai.send"}
SUPPORTED_SUBJECT_TYPES = {"any", "user", "role", "group"}
CLASSIFICATION_RANK = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}


@dataclass(slots=True)
class PolicyContext:
    action: str
    resource_type: str
    resource_id: str | None = None
    project_id: str | None = None
    fields: set[str] = field(default_factory=set)
    classification: str = "internal"
    source_type: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    preauthorized: bool = False


@dataclass(slots=True)
class PolicyDecision:
    allowed: bool
    reason: str
    base_role: str | None
    matched_rule_ids: list[str] = field(default_factory=list)
    denied_fields: list[str] = field(default_factory=list)
    obligations: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "base_role": self.base_role,
            "matched_rule_ids": self.matched_rule_ids,
            "denied_fields": self.denied_fields,
            "obligations": self.obligations,
        }


@dataclass(slots=True)
class DlpDecision:
    allowed: bool
    classification: str
    findings: list[dict[str, Any]]
    matched_policy_ids: list[str]
    obligations: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "classification": self.classification,
            "findings": self.findings,
            "matched_policy_ids": self.matched_policy_ids,
            "obligations": self.obligations,
        }


@dataclass(slots=True)
class PolicySnapshot:
    rules: list[PolicyRule]
    group_ids: set[str]


def _base_allowed(action: str, base_role: str | None, workspace_role: str) -> bool:
    if workspace_role == "admin":
        return True
    if base_role == "member":
        return action not in {"manage", "share", "approve", "policy.manage", "integration.manage"}
    if action in READ_ACTIONS:
        return base_role is not None or workspace_role == "basic"
    if action in COMMENT_ACTIONS:
        return base_role in {"owner", "editor", "commenter", "approver"}
    if action in EDIT_ACTIONS:
        return base_role in {"owner", "editor"}
    if action in EGRESS_ACTIONS:
        return base_role is not None
    if action in MANAGE_ACTIONS:
        return base_role == "owner"
    return False


async def _group_ids(session: AsyncSession, user: User) -> set[str]:
    return set(await session.scalars(
        select(OrganizationUnitMember.unit_id).where(OrganizationUnitMember.user_id == user.id)
    ))


def _subject_matches(rule: PolicyRule, user: User, groups: set[str]) -> bool:
    if rule.subject_type == "any":
        return True
    if rule.subject_type == "user":
        return rule.subject_id == user.id
    if rule.subject_type == "role":
        return rule.subject_id == user.role
    if rule.subject_type == "group":
        return bool(rule.subject_id and rule.subject_id in groups)
    return False


def _resource_matches(rule: PolicyRule, context: PolicyContext) -> bool:
    if rule.resource_type not in {"*", context.resource_type}:
        return False
    if rule.resource_id and rule.resource_id not in {context.resource_id, context.project_id}:
        return False
    if rule.actions and "*" not in rule.actions and context.action not in rule.actions:
        return False
    if rule.fields and context.fields and not context.fields.intersection(set(rule.fields)):
        return False
    conditions = rule.conditions or {}
    allowed_classifications = set(conditions.get("classifications") or [])
    if allowed_classifications and context.classification not in allowed_classifications:
        return False
    source_types = set(conditions.get("source_types") or [])
    if source_types and context.source_type not in source_types:
        return False
    attributes = conditions.get("attributes") or {}
    if any(context.attributes.get(key) != value for key, value in attributes.items()):
        return False
    return True


async def evaluate_policy(
    session: AsyncSession,
    user: User,
    context: PolicyContext,
    snapshot: PolicySnapshot | None = None,
) -> PolicyDecision:
    """Evaluate base object access followed by tenant rules; any matching deny wins."""
    if user.account_status != "active":
        return PolicyDecision(False, "account_inactive", None)

    base_role: str | None = None
    if context.preauthorized:
        base_role = "admin" if user.role == "admin" else "member"
    elif context.project_id:
        project = await session.get(Project, context.project_id)
        if not project or project.entity_id != user.entity_id:
            return PolicyDecision(False, "resource_not_found", None)
        base_role = await project_access_role(session, project, user)
    elif user.role == "admin":
        base_role = "admin"
    elif user.role != "guest":
        base_role = "member"

    default_allowed = _base_allowed(context.action, base_role, user.role)
    if snapshot is None:
        snapshot = await load_policy_snapshot(session, user)
    groups = snapshot.group_ids
    rules = [rule for rule in snapshot.rules if rule.resource_type in {"*", context.resource_type}]
    matching = [
        rule for rule in rules
        if _subject_matches(rule, user, groups) and _resource_matches(rule, context)
    ]
    denied_fields = sorted({
        field_name for rule in matching if rule.effect == "deny"
        for field_name in (rule.fields or []) if not context.fields or field_name in context.fields
    })
    denies = [rule for rule in matching if rule.effect == "deny"]
    allows = [rule for rule in matching if rule.effect == "allow"]
    obligations = sorted({
        str(item) for rule in matching for item in (rule.conditions or {}).get("obligations", [])
    })
    if denies:
        return PolicyDecision(
            False, "explicit_deny", base_role, [rule.id for rule in matching], denied_fields, obligations,
        )
    if allows:
        return PolicyDecision(
            True, "explicit_allow", base_role, [rule.id for rule in matching], [], obligations,
        )
    return PolicyDecision(default_allowed, "base_access" if default_allowed else "default_deny", base_role)


async def load_policy_snapshot(session: AsyncSession, user: User) -> PolicySnapshot:
    rules = list(await session.scalars(
        select(PolicyRule).where(
            PolicyRule.entity_id == user.entity_id,
            PolicyRule.active.is_(True),
        ).order_by(PolicyRule.priority.desc(), PolicyRule.created_at.asc())
    ))
    return PolicySnapshot(rules=rules, group_ids=await _group_ids(session, user))


async def authorize(
    session: AsyncSession,
    user: User,
    *,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    project_id: str | None = None,
    fields: Iterable[str] = (),
    classification: str = "internal",
    source_type: str | None = None,
    attributes: dict[str, Any] | None = None,
    preauthorized: bool = False,
) -> PolicyDecision:
    decision = await evaluate_policy(session, user, PolicyContext(
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        project_id=project_id,
        fields=set(fields),
        classification=classification,
        source_type=source_type,
        attributes=attributes or {},
        preauthorized=preauthorized,
    ))
    if not decision.allowed:
        raise HTTPException(
            status_code=403,
            detail={
                "message": "Workspace policy does not permit this action",
                "code": "policy_denied",
                "reason": decision.reason,
                "matched_rule_ids": decision.matched_rule_ids,
                "denied_fields": decision.denied_fields,
            },
        )
    return decision


BUILTIN_DETECTORS = {
    "email": re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+", re.IGNORECASE),
    "us_ssn": re.compile(r"(?<!\d)(?!000|666|9\d\d)\d{3}[- ]?(?!00)\d{2}[- ]?(?!0000)\d{4}(?!\d)"),
    "payment_card": re.compile(r"(?<!\d)(?:\d[ -]*?){13,19}(?!\d)"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "credential": re.compile(r"(?i)\b(?:api[_ -]?key|secret|password|bearer)\b\s*[:=]\s*[A-Za-z0-9_./+\-=]{8,}"),
}


def _luhn_candidate(value: str) -> bool:
    digits = [int(character) for character in value if character.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    checksum = 0
    parity = len(digits) % 2
    for index, digit in enumerate(digits):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


async def evaluate_dlp(
    session: AsyncSession,
    user: User,
    *,
    content: str,
    source_type: str,
    action: str,
    classification: str = "internal",
) -> DlpDecision:
    """Return metadata-only findings. Matched secrets are never returned or logged."""
    policies = list(await session.scalars(select(DataGovernancePolicy).where(
        DataGovernancePolicy.entity_id == user.entity_id,
        DataGovernancePolicy.kind == "dlp",
        DataGovernancePolicy.active.is_(True),
    )))
    applicable = [policy for policy in policies if not policy.applies_to or source_type in policy.applies_to or "*" in policy.applies_to]
    findings: list[dict[str, Any]] = []
    obligations: set[str] = set()
    blocked = False
    highest = classification if classification in CLASSIFICATION_RANK else "internal"
    for policy in applicable:
        findings_before = len(findings)
        configuration = policy.configuration or {}
        detector_names = configuration.get("detectors") or list(BUILTIN_DETECTORS)
        for detector_name in detector_names:
            detector = BUILTIN_DETECTORS.get(str(detector_name))
            if not detector:
                continue
            matches = list(detector.finditer(content[:1_000_000]))
            if detector_name == "payment_card":
                matches = [match for match in matches if _luhn_candidate(match.group(0))]
            if matches:
                findings.append({"type": detector_name, "count": len(matches), "policy_id": policy.id})
        if len(findings) > findings_before:
            if CLASSIFICATION_RANK.get(policy.classification, 1) > CLASSIFICATION_RANK.get(highest, 1):
                highest = policy.classification
            obligations.update(str(item) for item in configuration.get("obligations", []))
            actions = set(configuration.get("blocked_actions") or list(EGRESS_ACTIONS))
            if policy.enforcement == "block" and action in actions:
                blocked = True
    if user.role == "guest" and CLASSIFICATION_RANK.get(highest, 1) >= CLASSIFICATION_RANK["confidential"]:
        blocked = True
        obligations.add("guest_isolation")
    return DlpDecision(not blocked, highest, findings, [policy.id for policy in applicable], sorted(obligations))


async def enforce_dlp(session: AsyncSession, user: User, **kwargs: Any) -> DlpDecision:
    decision = await evaluate_dlp(session, user, **kwargs)
    if not decision.allowed:
        raise HTTPException(
            status_code=403,
            detail={
                "message": "Data protection policy blocked this action",
                "code": "dlp_blocked",
                "classification": decision.classification,
                "findings": decision.findings,
                "obligations": decision.obligations,
            },
        )
    return decision


async def is_held(
    session: AsyncSession,
    entity_id: str,
    scope_type: str,
    scope_id: str | None,
) -> bool:
    return bool(await session.scalar(select(LegalHold.id).where(
        LegalHold.entity_id == entity_id,
        LegalHold.status == "active",
        or_(
            LegalHold.scope_type == "entity",
            (LegalHold.scope_type == scope_type) & (LegalHold.scope_id == scope_id),
        ),
    ).limit(1)))


async def entitlement_enabled(
    session: AsyncSession,
    entity_id: str,
    feature: str,
    *,
    default: bool = True,
) -> bool:
    item = await session.scalar(select(FeatureEntitlement).where(
        FeatureEntitlement.entity_id == entity_id,
        FeatureEntitlement.feature == feature,
    ))
    if not item:
        return default
    now = datetime.now(timezone.utc)
    if item.starts_at and item.starts_at.replace(tzinfo=item.starts_at.tzinfo or timezone.utc) > now:
        return False
    if item.ends_at and item.ends_at.replace(tzinfo=item.ends_at.tzinfo or timezone.utc) <= now:
        return False
    return item.enabled


async def require_entitlement(session: AsyncSession, entity_id: str, feature: str) -> None:
    if not await entitlement_enabled(session, entity_id, feature):
        raise HTTPException(
            status_code=403,
            detail={"message": "This workspace plan does not include the requested feature", "code": "entitlement_required", "feature": feature},
        )
