from datetime import datetime, timezone
from secrets import compare_digest

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import get_current_admin
from .config import Settings, get_settings
from .database import (
    BackgroundJob,
    Entity,
    GeneratedArtifact,
    ProjectAttachment,
    ProcessEvent,
    ProcessEventImport,
    ProcessInsight,
    User,
    get_session,
)
from .quota_service import entity_usage, month_start
from .schemas import EntityUsageResponse, UsageValue
from .telemetry import metrics


router = APIRouter(prefix="/operations", tags=["operations"])
metrics_router = APIRouter(tags=["operations"])


def usage_value(used: int, limit: int) -> UsageValue:
    return UsageValue(used=used, limit=limit, remaining=max(0, limit - used))


@router.get("/usage", response_model=EntityUsageResponse)
async def workspace_usage(
    user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> EntityUsageResponse:
    entity = await session.get(Entity, user.entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Workspace not found")
    usage = await entity_usage(session, entity.id)
    return EntityUsageResponse(
        entity_id=entity.id,
        period_start=month_start(),
        users=usage_value(usage.users + usage.pending_invitations, entity.max_users),
        projects=usage_value(usage.projects, entity.max_projects),
        storage_bytes=usage_value(usage.storage_bytes, entity.max_storage_bytes),
        monthly_generations=usage_value(
            usage.monthly_generations,
            entity.max_monthly_generations,
        ),
        pending_generations=usage_value(
            usage.pending_generations,
            entity.max_pending_generations,
        ),
    )


def require_metrics_key(
    supplied_key: str | None = Header(default=None, alias="X-FlowForge-Metrics-Key"),
    settings: Settings = Depends(get_settings),
) -> None:
    if settings.environment.strip().lower() != "production" and not supplied_key:
        return
    if not supplied_key or not compare_digest(supplied_key, settings.metrics_api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid metrics key is required",
        )


@metrics_router.get(
    "/metrics",
    include_in_schema=False,
    dependencies=[Depends(require_metrics_key)],
)
async def prometheus_metrics(
    session: AsyncSession = Depends(get_session),
) -> PlainTextResponse:
    job_counts = (
        await session.execute(
            select(BackgroundJob.status, func.count(BackgroundJob.id)).group_by(
                BackgroundJob.status
            )
        )
    ).all()
    scan_pending = int(
        await session.scalar(
            select(func.count(ProjectAttachment.id)).where(
                ProjectAttachment.scan_status.in_(("pending", "queued", "scanning"))
            )
        )
        or 0
    )
    now = datetime.now(timezone.utc)
    artifact_count, artifact_bytes = (
        await session.execute(
            select(
                func.count(GeneratedArtifact.id),
                func.coalesce(func.sum(GeneratedArtifact.size_bytes), 0),
            ).where(GeneratedArtifact.expires_at > now)
        )
    ).one()
    oldest_queued = await session.scalar(
        select(func.min(BackgroundJob.created_at)).where(BackgroundJob.status == "queued")
    )
    if oldest_queued and oldest_queued.tzinfo is None:
        oldest_queued = oldest_queued.replace(tzinfo=timezone.utc)
    gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {
        (
            "flowforge_background_jobs",
            (("status", job_status),),
        ): float(count)
        for job_status, count in job_counts
    }
    gauges[("flowforge_attachment_scans_pending", ())] = float(scan_pending)
    gauges[("flowforge_generated_artifacts", ())] = float(artifact_count or 0)
    gauges[("flowforge_generated_artifact_bytes", ())] = float(artifact_bytes or 0)
    gauges[("flowforge_process_event_imports", ())] = float(
        int(await session.scalar(select(func.count(ProcessEventImport.id))) or 0)
    )
    gauges[("flowforge_process_events", ())] = float(
        int(await session.scalar(select(func.count(ProcessEvent.id))) or 0)
    )
    gauges[("flowforge_process_insights_open", ())] = float(
        int(await session.scalar(
            select(func.count(ProcessInsight.id)).where(ProcessInsight.status == "open")
        ) or 0)
    )
    gauges[("flowforge_oldest_queued_job_age_seconds", ())] = (
        max(0.0, (now - oldest_queued).total_seconds()) if oldest_queued else 0.0
    )
    return PlainTextResponse(
        metrics.render(gauges),
        media_type="text/plain; version=0.0.4",
    )
