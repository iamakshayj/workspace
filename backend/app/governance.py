from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .database import AuditEvent, OrganizationUnitMember, Project, ProjectCollaborator, ProjectGroupAccess, ProjectRevision, User


PROJECT_ACCESS_ROLES = {"viewer", "commenter", "editor", "approver"}
EDIT_ACCESS_ROLES = {"admin", "owner", "editor"}
APPROVE_ACCESS_ROLES = {"admin", "approver"}
MANAGE_ACCESS_ROLES = {"admin", "owner"}
PROJECT_VISIBILITIES = {"workspace", "restricted"}


def default_project_role(user: User) -> str:
    return "editor" if user.role == "admin" else "viewer"


def normalize_project_role(role: str) -> str:
    normalized = role.strip().lower()
    if normalized not in PROJECT_ACCESS_ROLES:
        raise ValueError("Project role must be viewer, commenter, editor, or approver")
    return normalized


def normalize_visibility(visibility: str) -> str:
    normalized = visibility.strip().lower()
    if normalized not in PROJECT_VISIBILITIES:
        raise ValueError("Visibility must be workspace or restricted")
    return normalized


async def project_access_role(
    session: AsyncSession,
    project: Project,
    user: User,
) -> str | None:
    if project.entity_id != user.entity_id:
        return None
    if user.role == "admin":
        return "admin"
    if project.owner_id == user.id:
        return "owner"
    role = await session.scalar(
        select(ProjectCollaborator.access_role).where(
            ProjectCollaborator.project_id == project.id,
            ProjectCollaborator.user_id == user.id,
        )
    )
    if role:
        return role
    group_roles = list(await session.scalars(
        select(ProjectGroupAccess.access_role)
        .join(OrganizationUnitMember, OrganizationUnitMember.unit_id == ProjectGroupAccess.unit_id)
        .where(ProjectGroupAccess.project_id == project.id, OrganizationUnitMember.user_id == user.id)
    ))
    if group_roles:
        rank = {"viewer": 1, "commenter": 2, "approver": 3, "editor": 4}
        return max(group_roles, key=lambda value: rank.get(value, 0))
    if user.role != "guest" and (project.visibility or "workspace") == "workspace":
        return "viewer"
    return None


def can_edit_project(access_role: str | None) -> bool:
    return access_role in EDIT_ACCESS_ROLES


def can_approve_project(access_role: str | None) -> bool:
    return access_role in APPROVE_ACCESS_ROLES


def can_manage_project(access_role: str | None) -> bool:
    return access_role in MANAGE_ACCESS_ROLES


async def latest_revision(
    session: AsyncSession,
    project_id: str,
) -> ProjectRevision | None:
    return await session.scalar(
        select(ProjectRevision)
        .where(ProjectRevision.project_id == project_id)
        .order_by(ProjectRevision.version.desc())
        .limit(1)
    )


async def snapshot_project(
    session: AsyncSession,
    project: Project,
    actor_id: str,
    change_summary: str,
) -> ProjectRevision:
    current_version = await session.scalar(
        select(func.max(ProjectRevision.version)).where(
            ProjectRevision.project_id == project.id
        )
    )
    revision = ProjectRevision(
        project_id=project.id,
        version=(current_version or 0) + 1,
        title=project.title,
        description=project.description or "",
        status=project.status or "active",
        profile=project.profile or {},
        source_text=project.source_text,
        graph=project.graph,
        change_summary=change_summary.strip()[:240] or "Saved changes",
        created_by_id=actor_id,
    )
    session.add(revision)
    await session.flush()
    return revision


def record_audit_event(
    session: AsyncSession,
    *,
    entity_id: str,
    actor_id: str | None,
    action: str,
    project_id: str | None = None,
    target_type: str = "project",
    target_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        entity_id=entity_id,
        project_id=project_id,
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id or project_id,
        details=details or {},
        created_at=datetime.now(timezone.utc),
    )
    session.add(event)
    return event
