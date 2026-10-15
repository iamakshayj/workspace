from datetime import datetime, timezone
from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from .artifact_service import EVIDENCE_PACKAGE_JOB, OPERATIONAL_PACKAGE_JOB, PROJECT_EXPORT_JOB
from .auth import get_current_user
from .config import Settings, get_settings
from .database import BackgroundJob, GeneratedArtifact, User, get_session
from .governance import can_manage_project, project_access_role
from .job_service import create_background_job
from .object_storage import ObjectStorageError, object_storage
from .policy_engine import authorize, enforce_dlp, require_entitlement
from .project_routes import entity_project
from .schemas import (
    ArtifactJobRequest,
    ArtifactJobResponse,
    GeneratedArtifactResponse,
)


router = APIRouter(prefix="/projects", tags=["project artifacts"])


def serialize_artifact(artifact: GeneratedArtifact) -> GeneratedArtifactResponse:
    return GeneratedArtifactResponse(
        id=artifact.id,
        kind=artifact.kind,
        format=artifact.format,
        filename=artifact.filename,
        content_type=artifact.content_type,
        size_bytes=artifact.size_bytes,
        download_url=(
            f"/api/v1/projects/{artifact.project_id}/artifacts/{artifact.id}/download"
        ),
        expires_at=artifact.expires_at,
        created_at=artifact.created_at,
    )


async def serialize_artifact_job(
    job: BackgroundJob,
    session: AsyncSession,
) -> ArtifactJobResponse:
    artifact = None
    artifact_id = str((job.result or {}).get("artifact_id") or "")
    if artifact_id:
        record = await session.get(GeneratedArtifact, artifact_id)
        if record:
            artifact = serialize_artifact(record)
    return ArtifactJobResponse(
        id=job.id,
        status=job.status,
        attempts=job.attempts or 0,
        max_attempts=job.max_attempts,
        artifact=artifact,
        error_code=job.error_code,
        error_message=job.error_message,
        created_at=job.created_at,
        updated_at=job.updated_at,
        completed_at=job.completed_at,
    )


@router.post(
    "/{project_id}/artifact-jobs",
    response_model=ArtifactJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_artifact_job(
    project_id: str,
    payload: ArtifactJobRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ArtifactJobResponse:
    project = await entity_project(project_id, user, session)
    access = await project_access_role(session, project, user)
    if payload.kind in {"evidence_package", "operational_package"} and not can_manage_project(access):
        raise HTTPException(
            status_code=403,
            detail="Only a project manager can create governed project packages",
        )
    classification = str((project.profile or {}).get("classification") or "internal")
    await require_entitlement(session, user.entity_id, "governed_exports")
    await authorize(
        session, user, action="export", resource_type="export", resource_id=project.id,
        project_id=project.id, classification=classification, source_type="project",
    )
    await enforce_dlp(
        session, user,
        content=f"{project.title}\n{project.description or ''}\n{project.source_text or ''}",
        source_type="export", action="export", classification=classification,
    )
    job_kind = {
        "evidence_package": EVIDENCE_PACKAGE_JOB,
        "operational_package": OPERATIONAL_PACKAGE_JOB,
    }.get(payload.kind, PROJECT_EXPORT_JOB)
    job = await create_background_job(
        entity_id=user.entity_id,
        created_by_id=user.id,
        kind=job_kind,
        payload={
            "project_id": project.id,
            "artifact_kind": payload.kind,
            "format": payload.format,
        },
        settings=settings,
    )
    return await serialize_artifact_job(job, session)


@router.get(
    "/{project_id}/artifact-jobs/{job_id}",
    response_model=ArtifactJobResponse,
)
async def get_artifact_job(
    project_id: str,
    job_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ArtifactJobResponse:
    await entity_project(project_id, user, session)
    job = await session.get(BackgroundJob, job_id)
    if (
        not job
        or job.kind not in {PROJECT_EXPORT_JOB, EVIDENCE_PACKAGE_JOB, OPERATIONAL_PACKAGE_JOB}
        or job.entity_id != user.entity_id
        or job.created_by_id != user.id
        or str(job.payload.get("project_id") or "") != project_id
    ):
        raise HTTPException(status_code=404, detail="Generated artifact job not found")
    return await serialize_artifact_job(job, session)


@router.get("/{project_id}/artifacts/{artifact_id}/download")
async def download_artifact(
    project_id: str,
    artifact_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    project = await entity_project(project_id, user, session)
    artifact = await session.get(GeneratedArtifact, artifact_id)
    if (
        not artifact
        or artifact.project_id != project.id
        or artifact.entity_id != user.entity_id
    ):
        raise HTTPException(status_code=404, detail="Generated artifact not found")
    expires_at = artifact.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="Generated artifact has expired")
    access = await project_access_role(session, project, user)
    if artifact.kind in {"evidence_package", "operational_package"} and not can_manage_project(access):
        raise HTTPException(status_code=403, detail="Governed package access is restricted")
    await authorize(
        session, user, action="download", resource_type="export", resource_id=artifact.id,
        project_id=project.id, classification=str((project.profile or {}).get("classification") or "internal"),
        source_type="export",
    )
    try:
        if object_storage.mode == "local":
            content = await object_storage.read(artifact.storage_key)
            return Response(
                content=content,
                media_type=artifact.content_type,
                headers={
                    "Content-Disposition": (
                        f"attachment; filename*=UTF-8''{quote(artifact.filename)}"
                    ),
                    "X-Content-Type-Options": "nosniff",
                },
            )
        url = await object_storage.create_download_url(
            artifact.id,
            artifact.storage_key,
            artifact.filename,
        )
    except ObjectStorageError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return RedirectResponse(url=url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
