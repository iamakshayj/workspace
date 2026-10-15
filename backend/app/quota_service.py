from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .database import (
    BackgroundJob,
    Entity,
    GeneratedArtifact,
    Invitation,
    Project,
    ProjectAttachment,
    User,
)


GENERATION_JOB = "generate_flowchart"
PENDING_JOB_STATUSES = ("queued", "running")
ACTIVE_UPLOAD_STATUSES = ("uploading", "complete")


class QuotaExceededError(RuntimeError):
    def __init__(self, resource: str, limit: int, used: int) -> None:
        self.resource = resource
        self.limit = limit
        self.used = used
        super().__init__(f"The workspace {resource} quota of {limit:,} has been reached.")


@dataclass(frozen=True)
class EntityUsageSnapshot:
    users: int
    pending_invitations: int
    projects: int
    storage_bytes: int
    monthly_generations: int
    pending_generations: int


def month_start(now: datetime | None = None) -> datetime:
    current = now or datetime.now(timezone.utc)
    return datetime(current.year, current.month, 1, tzinfo=timezone.utc)


async def locked_entity(session: AsyncSession, entity_id: str) -> Entity:
    entity = await session.scalar(
        select(Entity).where(Entity.id == entity_id).with_for_update()
    )
    if not entity:
        raise RuntimeError("Workspace not found")
    return entity


async def entity_usage(session: AsyncSession, entity_id: str) -> EntityUsageSnapshot:
    users = await session.scalar(
        select(func.count(User.id)).where(User.entity_id == entity_id)
    )
    pending_invitations = await session.scalar(
        select(func.count(Invitation.id)).where(
            Invitation.entity_id == entity_id,
            Invitation.status == "pending",
            Invitation.expires_at > datetime.now(timezone.utc),
        )
    )
    projects = await session.scalar(
        select(func.count(Project.id)).where(Project.entity_id == entity_id)
    )
    attachment_bytes = await session.scalar(
        select(func.coalesce(func.sum(ProjectAttachment.size_bytes), 0)).where(
            ProjectAttachment.entity_id == entity_id,
            ProjectAttachment.upload_status.in_(ACTIVE_UPLOAD_STATUSES),
        )
    )
    artifact_bytes = await session.scalar(
        select(func.coalesce(func.sum(GeneratedArtifact.size_bytes), 0)).where(
            GeneratedArtifact.entity_id == entity_id,
            GeneratedArtifact.expires_at > datetime.now(timezone.utc),
        )
    )
    monthly_generations = await session.scalar(
        select(func.count(BackgroundJob.id)).where(
            BackgroundJob.entity_id == entity_id,
            BackgroundJob.kind == GENERATION_JOB,
            BackgroundJob.created_at >= month_start(),
        )
    )
    pending_generations = await session.scalar(
        select(func.count(BackgroundJob.id)).where(
            BackgroundJob.entity_id == entity_id,
            BackgroundJob.kind == GENERATION_JOB,
            BackgroundJob.status.in_(PENDING_JOB_STATUSES),
        )
    )
    return EntityUsageSnapshot(
        users=int(users or 0),
        pending_invitations=int(pending_invitations or 0),
        projects=int(projects or 0),
        storage_bytes=int(attachment_bytes or 0) + int(artifact_bytes or 0),
        monthly_generations=int(monthly_generations or 0),
        pending_generations=int(pending_generations or 0),
    )


async def ensure_project_capacity(session: AsyncSession, entity_id: str) -> Entity:
    entity = await locked_entity(session, entity_id)
    used = int(
        await session.scalar(
            select(func.count(Project.id)).where(Project.entity_id == entity_id)
        )
        or 0
    )
    if used >= entity.max_projects:
        raise QuotaExceededError("projects", entity.max_projects, used)
    return entity


async def ensure_user_capacity(
    session: AsyncSession,
    entity_id: str,
    *,
    additional_reserved_seats: int,
) -> Entity:
    entity = await locked_entity(session, entity_id)
    users = int(
        await session.scalar(select(func.count(User.id)).where(User.entity_id == entity_id)) or 0
    )
    invitations = int(
        await session.scalar(
            select(func.count(Invitation.id)).where(
                Invitation.entity_id == entity_id,
                Invitation.status == "pending",
                Invitation.expires_at > datetime.now(timezone.utc),
            )
        )
        or 0
    )
    used = users + invitations
    if used + additional_reserved_seats > entity.max_users:
        raise QuotaExceededError("users", entity.max_users, used)
    return entity


async def ensure_attachment_capacity(
    session: AsyncSession,
    entity_id: str,
    requested_bytes: int,
) -> Entity:
    entity = await locked_entity(session, entity_id)
    attachment_bytes = int(
        await session.scalar(
            select(func.coalesce(func.sum(ProjectAttachment.size_bytes), 0)).where(
                ProjectAttachment.entity_id == entity_id,
                ProjectAttachment.upload_status.in_(ACTIVE_UPLOAD_STATUSES),
            )
        )
        or 0
    )
    artifact_bytes = int(
        await session.scalar(
            select(func.coalesce(func.sum(GeneratedArtifact.size_bytes), 0)).where(
                GeneratedArtifact.entity_id == entity_id,
                GeneratedArtifact.expires_at > datetime.now(timezone.utc),
            )
        )
        or 0
    )
    used = attachment_bytes + artifact_bytes
    if used + requested_bytes > entity.max_storage_bytes:
        raise QuotaExceededError("storage", entity.max_storage_bytes, used)
    return entity


async def ensure_artifact_capacity(
    session: AsyncSession,
    entity_id: str,
    requested_bytes: int,
) -> Entity:
    return await ensure_attachment_capacity(session, entity_id, requested_bytes)


async def ensure_generation_capacity(session: AsyncSession, entity_id: str) -> Entity:
    entity = await locked_entity(session, entity_id)
    monthly = int(
        await session.scalar(
            select(func.count(BackgroundJob.id)).where(
                BackgroundJob.entity_id == entity_id,
                BackgroundJob.kind == GENERATION_JOB,
                BackgroundJob.created_at >= month_start(),
            )
        )
        or 0
    )
    if monthly >= entity.max_monthly_generations:
        raise QuotaExceededError(
            "monthly generations",
            entity.max_monthly_generations,
            monthly,
        )
    pending = int(
        await session.scalar(
            select(func.count(BackgroundJob.id)).where(
                BackgroundJob.entity_id == entity_id,
                BackgroundJob.kind == GENERATION_JOB,
                BackgroundJob.status.in_(PENDING_JOB_STATUSES),
            )
        )
        or 0
    )
    if pending >= entity.max_pending_generations:
        raise QuotaExceededError(
            "pending generations",
            entity.max_pending_generations,
            pending,
        )
    return entity
