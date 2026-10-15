import asyncio
from datetime import datetime, timezone
from pathlib import PurePath
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import get_current_admin, get_current_user
from .artifact_service import delete_project_objects
from .database import (
    Project,
    ProjectAttachment,
    ProjectCollaborator,
    ProjectDeliverable,
    ProjectTask,
    User,
    get_session,
)
from .config import Settings, get_settings
from .job_service import (
    ATTACHMENT_SCAN_JOB,
    create_background_job,
    notify_background_job,
    stage_webhook_event,
)
from .object_storage import (
    ObjectNotFoundError,
    ObjectStorageError,
    clean_storage_key,
    object_storage,
)
from .quota_service import ensure_attachment_capacity, ensure_project_capacity
from .policy_engine import PolicyContext, authorize, enforce_dlp, evaluate_policy, is_held, load_policy_snapshot
from .governance import (
    can_edit_project,
    can_manage_project,
    project_access_role,
    record_audit_event,
    snapshot_project,
)
from .schemas import (
    AttachmentResponse,
    AttachmentUploadGrant,
    AttachmentUploadRequest,
    AttachmentUploadResponse,
    ProjectResponse,
    ProjectSummary,
    ProjectWrite,
)


router = APIRouter(prefix="/projects", tags=["projects"])


def serialize_attachment(attachment: ProjectAttachment) -> AttachmentResponse:
    return AttachmentResponse(
        id=attachment.id,
        project_id=attachment.project_id,
        node_id=attachment.node_id,
        filename=attachment.filename,
        content_type=attachment.content_type,
        size_bytes=attachment.size_bytes,
        uploaded_by_id=attachment.uploaded_by_id,
        upload_status=attachment.upload_status or "complete",
        scan_status=attachment.scan_status or "clean",
        scan_message=attachment.scan_message,
        created_at=attachment.created_at,
    )


def safe_attachment_filename(filename: str) -> str:
    safe_filename = PurePath(filename).name.strip()
    if not safe_filename or safe_filename in {".", ".."}:
        raise HTTPException(status_code=400, detail="Enter a valid attachment filename")
    return safe_filename


async def validate_attachment_node(project: Project, node_id: str | None) -> None:
    if node_id and node_id not in {node.get("id") for node in project.graph.get("nodes", [])}:
        raise HTTPException(status_code=400, detail="The selected flowchart step no longer exists")


async def entity_project(project_id: str, user: User, session: AsyncSession) -> Project:
    project = await session.get(Project, project_id)
    if (
        not project
        or project.entity_id != user.entity_id
        or not await project_access_role(session, project, user)
    ):
        raise HTTPException(status_code=404, detail="Project not found")
    await authorize(
        session, user, action="read", resource_type="project", resource_id=project.id,
        project_id=project.id,
        classification=str((project.profile or {}).get("classification") or "internal"),
        source_type="project",
    )
    return project


async def require_project_editor(
    project: Project,
    user: User,
    session: AsyncSession,
) -> None:
    if not can_edit_project(await project_access_role(session, project, user)):
        raise HTTPException(status_code=403, detail="Editor access is required")


async def validated_people(
    payload: ProjectWrite,
    user: User,
    session: AsyncSession,
    fallback_owner_id: str,
) -> tuple[str, list[str]]:
    owner_id = payload.owner_id or fallback_owner_id
    collaborator_ids = list(dict.fromkeys([*payload.collaborator_ids, owner_id]))
    members = list(
        await session.scalars(
            select(User).where(
                User.id.in_(collaborator_ids),
                User.entity_id == user.entity_id,
            )
        )
    )
    if len(members) != len(collaborator_ids):
        raise HTTPException(
            status_code=400,
            detail="Project owners and collaborators must belong to this workspace",
        )
    if payload.profile.sponsor_id:
        sponsor = await session.get(User, payload.profile.sponsor_id)
        if not sponsor or sponsor.entity_id != user.entity_id:
            raise HTTPException(status_code=400, detail="Project sponsor must belong to this workspace")
    return owner_id, collaborator_ids


async def project_collaborator_ids(project_id: str, session: AsyncSession) -> list[str]:
    return list(
        await session.scalars(
            select(ProjectCollaborator.user_id)
            .where(ProjectCollaborator.project_id == project_id)
            .order_by(ProjectCollaborator.added_at.asc())
        )
    )


async def serialize(project: Project, session: AsyncSession) -> ProjectResponse:
    return ProjectResponse(
        id=project.id,
        document_revision=project.revision or 0,
        title=project.title,
        description=project.description or "",
        status=project.status or "active",
        owner_id=project.owner_id,
        collaborator_ids=await project_collaborator_ids(project.id, session),
        profile=project.profile or {},
        source_text=project.source_text,
        graph=project.graph,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


@router.get("", response_model=list[ProjectSummary])
async def list_projects(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[ProjectSummary]:
    access_filter = Project.entity_id == user.entity_id
    if user.role != "admin":
        access_filter = (
            (Project.entity_id == user.entity_id)
            & or_(
                Project.visibility == "workspace",
                Project.owner_id == user.id,
                Project.id.in_(
                    select(ProjectCollaborator.project_id).where(
                        ProjectCollaborator.user_id == user.id
                    )
                ),
            )
        )
    result = await session.scalars(
        select(Project).where(access_filter).order_by(Project.updated_at.desc()).limit(100)
    )
    summaries = []
    policy_snapshot = await load_policy_snapshot(session, user)
    for item in result:
        policy = await evaluate_policy(session, user, PolicyContext(
            action="read", resource_type="project", resource_id=item.id, project_id=item.id,
            classification=str((item.profile or {}).get("classification") or "internal"),
            source_type="project", preauthorized=True,
        ), snapshot=policy_snapshot)
        if not policy.allowed:
            continue
        collaborator_count = await session.scalar(
            select(func.count(ProjectCollaborator.user_id)).where(
                ProjectCollaborator.project_id == item.id
            )
        ) or 0
        deliverable_count = await session.scalar(
            select(func.count(ProjectDeliverable.id)).where(
                ProjectDeliverable.project_id == item.id
            )
        ) or 0
        completed_deliverable_count = await session.scalar(
            select(func.count(ProjectDeliverable.id)).where(
                ProjectDeliverable.project_id == item.id,
                ProjectDeliverable.status == "done",
            )
        ) or 0
        task_count = await session.scalar(
            select(func.count(ProjectTask.id)).where(ProjectTask.project_id == item.id)
        ) or 0
        completed_task_count = await session.scalar(
            select(func.count(ProjectTask.id)).where(
                ProjectTask.project_id == item.id,
                ProjectTask.status == "done",
            )
        ) or 0
        plan_progress = round((completed_task_count / task_count) * 100) if task_count else (
            round((completed_deliverable_count / deliverable_count) * 100)
            if deliverable_count else 0
        )
        summaries.append(ProjectSummary(
            id=item.id,
            title=item.title,
            description=item.description or "",
            status=item.status or "active",
            profile=item.profile or {},
            owner_id=item.owner_id,
            collaborator_count=collaborator_count,
            deliverable_count=deliverable_count,
            completed_deliverable_count=completed_deliverable_count,
            task_count=task_count,
            completed_task_count=completed_task_count,
            plan_progress=plan_progress,
            created_at=item.created_at,
            updated_at=item.updated_at,
            node_count=len(item.graph.get("nodes", [])),
            edge_count=len(item.graph.get("edges", [])),
        ))
    return summaries


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectWrite,
    user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ProjectResponse:
    await authorize(session, user, action="create", resource_type="project", source_type="project")
    await ensure_project_capacity(session, user.entity_id)
    owner_id, collaborator_ids = await validated_people(payload, user, session, user.id)
    project = Project(
        owner_id=owner_id,
        entity_id=user.entity_id,
        title=payload.title,
        description=payload.description,
        status=payload.status,
        profile=payload.profile.model_dump(mode="json"),
        source_text=payload.source_text,
        graph=payload.graph.model_dump(mode="json"),
    )
    session.add(project)
    await session.flush()
    session.add_all([
        ProjectCollaborator(project_id=project.id, user_id=user_id)
        for user_id in collaborator_ids
    ])
    revision = await snapshot_project(session, project, user.id, "Created flowchart")
    record_audit_event(
        session,
        entity_id=project.entity_id,
        actor_id=user.id,
        project_id=project.id,
        action="project.created",
        details={"revision": revision.version},
    )
    webhook_jobs = await stage_webhook_event(
        session,
        entity_id=user.entity_id,
        actor_id=user.id,
        event_type="project.created",
        data={"project_id": project.id, "status": project.status, "revision": project.revision},
        settings=settings,
    )
    await session.commit()
    await asyncio.gather(*(notify_background_job(job.id) for job in webhook_jobs))
    await session.refresh(project)
    return await serialize(project, session)


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ProjectResponse:
    project = await entity_project(project_id, user, session)
    return await serialize(project, session)


@router.get("/{project_id}/attachments", response_model=list[AttachmentResponse])
async def list_attachments(
    project_id: str,
    node_id: str | None = Query(default=None, max_length=80),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[AttachmentResponse]:
    await entity_project(project_id, user, session)
    query = select(ProjectAttachment).where(
        ProjectAttachment.project_id == project_id,
        ProjectAttachment.upload_status == "complete",
    )
    if node_id:
        query = query.where(ProjectAttachment.node_id == node_id)
    attachments = await session.scalars(query.order_by(ProjectAttachment.created_at.asc()))
    return [serialize_attachment(attachment) for attachment in attachments]


@router.post(
    "/{project_id}/attachments/uploads",
    response_model=AttachmentUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_attachment_upload(
    project_id: str,
    payload: AttachmentUploadRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AttachmentUploadResponse:
    project = await entity_project(project_id, user, session)
    await require_project_editor(project, user, session)
    await authorize(
        session, user, action="upload", resource_type="file", project_id=project.id,
        classification=str((project.profile or {}).get("classification") or "internal"),
        source_type="attachment",
    )
    safe_filename = safe_attachment_filename(payload.filename)
    await validate_attachment_node(project, payload.node_id)
    if payload.size_bytes > settings.max_attachment_bytes:
        raise HTTPException(status_code=413, detail="Attachment exceeds the 10 MB limit")
    await ensure_attachment_capacity(session, user.entity_id, payload.size_bytes)
    attachment_id = str(uuid4())
    storage_key = (
        f"{user.entity_id}/{project.id}/{attachment_id}/quarantine/{safe_filename}"
    )
    attachment = ProjectAttachment(
        id=attachment_id,
        project_id=project.id,
        entity_id=user.entity_id,
        uploaded_by_id=user.id,
        node_id=payload.node_id,
        filename=safe_filename,
        content_type=payload.content_type.split(";", 1)[0][:160],
        size_bytes=payload.size_bytes,
        content=b"",
        storage_key=storage_key,
        upload_status="uploading",
        scan_status="pending",
    )
    session.add(attachment)
    await session.commit()
    await session.refresh(attachment)
    try:
        grant = await object_storage.create_upload_grant(
            attachment.id,
            storage_key,
            attachment.content_type,
            settings.max_attachment_bytes,
        )
    except ObjectStorageError as error:
        await session.delete(attachment)
        await session.commit()
        raise HTTPException(status_code=503, detail=str(error)) from error
    return AttachmentUploadResponse(
        attachment=serialize_attachment(attachment),
        upload=AttachmentUploadGrant(
            method=grant.method,
            url=grant.url,
            fields=grant.fields,
            headers=grant.headers,
            expires_at=grant.expires_at,
        ),
    )


@router.post(
    "/{project_id}/attachments/{attachment_id}/complete",
    response_model=AttachmentResponse,
)
async def complete_attachment_upload(
    project_id: str,
    attachment_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AttachmentResponse:
    project = await entity_project(project_id, user, session)
    await require_project_editor(project, user, session)
    classification = str((project.profile or {}).get("classification") or "internal")
    await authorize(
        session, user, action="upload", resource_type="file", resource_id=attachment_id,
        project_id=project.id, classification=classification, source_type="attachment",
    )
    attachment = await session.scalar(
        select(ProjectAttachment)
        .where(ProjectAttachment.id == attachment_id)
        .with_for_update()
    )
    if (
        not attachment
        or attachment.project_id != project_id
        or attachment.uploaded_by_id != user.id
        or not attachment.storage_key
    ):
        raise HTTPException(status_code=404, detail="Attachment upload not found")
    if attachment.upload_status == "complete":
        return serialize_attachment(attachment)
    try:
        metadata = await object_storage.head(attachment.storage_key)
    except ObjectNotFoundError as error:
        raise HTTPException(status_code=409, detail="Upload the file before completing it") from error
    except ObjectStorageError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    if metadata.size_bytes != attachment.size_bytes:
        await object_storage.delete(attachment.storage_key)
        raise HTTPException(status_code=400, detail="Uploaded attachment size does not match")
    inspectable = attachment.content_type.startswith("text/") or attachment.content_type in {
        "application/json", "application/xml", "application/x-yaml", "application/yaml",
        "text/csv",
    }
    if inspectable:
        try:
            raw_content = await object_storage.read(attachment.storage_key)
            await enforce_dlp(
                session, user, content=raw_content[:1_000_000].decode("utf-8", errors="replace"),
                source_type="attachment", action="upload", classification=classification,
            )
        except HTTPException:
            await object_storage.delete(attachment.storage_key)
            attachment.upload_status = "complete"
            attachment.scan_status = "blocked"
            attachment.scan_message = "Blocked by workspace data protection policy"
            project.updated_at = datetime.now(timezone.utc)
            await session.commit()
            raise
    scan_required = settings.attachment_scan_mode.lower() == "clamav"
    if not scan_required:
        promoted_key = clean_storage_key(attachment.storage_key)
        try:
            metadata = await object_storage.promote(attachment.storage_key, promoted_key)
        except ObjectStorageError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        attachment.storage_key = promoted_key
    attachment.upload_status = "complete"
    attachment.object_etag = metadata.etag
    attachment.uploaded_at = datetime.now(timezone.utc)
    attachment.scan_status = "queued" if scan_required else "clean"
    attachment.scan_message = (
        None if attachment.scan_status == "queued" else "Scanning disabled in this environment"
    )
    project.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(attachment)
    if attachment.scan_status == "queued":
        await create_background_job(
            entity_id=user.entity_id,
            created_by_id=user.id,
            kind=ATTACHMENT_SCAN_JOB,
            payload={"attachment_id": attachment.id},
            settings=settings,
        )
    return serialize_attachment(attachment)


@router.get("/{project_id}/attachments/{attachment_id}")
async def download_attachment(
    project_id: str,
    attachment_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    project = await entity_project(project_id, user, session)
    attachment = await session.get(ProjectAttachment, attachment_id)
    if not attachment or attachment.project_id != project_id:
        raise HTTPException(status_code=404, detail="Attachment not found")
    if attachment.upload_status != "complete":
        raise HTTPException(status_code=409, detail="Attachment upload is incomplete")
    if attachment.scan_status != "clean":
        raise HTTPException(status_code=423, detail="Attachment is not available until scanning succeeds")
    await authorize(
        session, user, action="download", resource_type="file", resource_id=attachment.id,
        project_id=project.id,
        classification=str((project.profile or {}).get("classification") or "internal"),
        source_type="attachment",
    )
    if attachment.storage_key:
        try:
            if object_storage.mode == "local":
                content = await object_storage.read(attachment.storage_key)
                return Response(
                    content=content,
                    media_type=attachment.content_type,
                    headers={
                        "Content-Disposition": (
                            f"attachment; filename*=UTF-8''{quote(attachment.filename)}"
                        ),
                        "X-Content-Type-Options": "nosniff",
                    },
                )
            url = await object_storage.create_download_url(
                attachment.id,
                attachment.storage_key,
                attachment.filename,
            )
        except ObjectStorageError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        return RedirectResponse(url=url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    return Response(
        content=attachment.content or b"",
        media_type=attachment.content_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(attachment.filename)}",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/{project_id}/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_attachment(
    project_id: str,
    attachment_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    project = await entity_project(project_id, user, session)
    await require_project_editor(project, user, session)
    attachment = await session.get(ProjectAttachment, attachment_id)
    if not attachment or attachment.project_id != project_id:
        raise HTTPException(status_code=404, detail="Attachment not found")
    if await is_held(session, user.entity_id, "project", project.id) or await is_held(session, user.entity_id, "file", attachment.id):
        raise HTTPException(status_code=409, detail={"message": "This attachment is preserved by an active legal hold", "code": "legal_hold"})
    await authorize(
        session, user, action="delete", resource_type="file", resource_id=attachment.id,
        project_id=project.id,
        classification=str((project.profile or {}).get("classification") or "internal"),
        source_type="attachment",
    )
    if attachment.storage_key:
        try:
            await object_storage.delete(attachment.storage_key)
        except ObjectStorageError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
    await session.delete(attachment)
    project.updated_at = datetime.now(timezone.utc)
    await session.commit()


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    payload: ProjectWrite,
    expected_revision: int | None = Header(default=None, alias="If-Match"),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ProjectResponse:
    project = await session.scalar(
        select(Project).where(Project.id == project_id).with_for_update()
    )
    if (
        not project
        or project.entity_id != user.entity_id
        or not await project_access_role(session, project, user)
    ):
        raise HTTPException(status_code=404, detail="Project not found")
    await require_project_editor(project, user, session)
    await authorize(
        session, user, action="edit", resource_type="project", resource_id=project.id,
        project_id=project.id, fields=payload.model_fields_set,
        classification=str((project.profile or {}).get("classification") or "internal"),
        source_type="project",
    )
    if expected_revision is None:
        raise HTTPException(
            status_code=428,
            detail="If-Match must contain the document revision returned by the project API",
        )
    if expected_revision != (project.revision or 0):
        raise HTTPException(
            status_code=409,
            detail={
                "message": "This flowchart changed after you opened it. Reload before saving.",
                "code": "CONFLICT",
                "current_revision": project.revision or 0,
            },
        )
    access = await project_access_role(session, project, user)
    if not can_manage_project(access) and (
        payload.owner_id not in {None, project.owner_id}
        or set(payload.collaborator_ids) != set(await project_collaborator_ids(project.id, session))
    ):
        raise HTTPException(status_code=403, detail="Only the project owner can change access")
    owner_id, collaborator_ids = await validated_people(
        payload, user, session, project.owner_id or user.id
    )
    project.title = payload.title
    project.description = payload.description
    project.status = payload.status
    project.profile = payload.profile.model_dump(mode="json")
    project.owner_id = owner_id
    project.source_text = payload.source_text
    project.graph = payload.graph.model_dump(mode="json")
    project.revision = (project.revision or 0) + 1
    if can_manage_project(access):
        await session.execute(
            delete(ProjectCollaborator).where(ProjectCollaborator.project_id == project.id)
        )
        session.add_all([
            ProjectCollaborator(project_id=project.id, user_id=user_id)
            for user_id in collaborator_ids
        ])
    revision = await snapshot_project(session, project, user.id, "Saved flowchart changes")
    project.approval_status = "draft"
    record_audit_event(
        session,
        entity_id=project.entity_id,
        actor_id=user.id,
        project_id=project.id,
        action="project.revision_created",
        target_type="project_revision",
        target_id=revision.id,
        details={"revision": revision.version},
    )
    webhook_jobs = await stage_webhook_event(
        session,
        entity_id=user.entity_id,
        actor_id=user.id,
        event_type="project.updated",
        data={"project_id": project.id, "status": project.status, "revision": project.revision},
        settings=settings,
    )
    await session.commit()
    await asyncio.gather(*(notify_background_job(job.id) for job in webhook_jobs))
    await session.refresh(project)
    return await serialize(project, session)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> None:
    project = await entity_project(project_id, user, session)
    if not can_manage_project(await project_access_role(session, project, user)):
        raise HTTPException(status_code=403, detail="Only the project owner can delete this flowchart")
    await authorize(
        session, user, action="delete", resource_type="project", resource_id=project.id,
        project_id=project.id,
        classification=str((project.profile or {}).get("classification") or "internal"),
        source_type="project",
    )
    if await is_held(session, user.entity_id, "project", project.id):
        raise HTTPException(status_code=409, detail={"message": "This project is preserved by an active legal hold", "code": "legal_hold"})
    try:
        await delete_project_objects(session, project.id, object_storage)
    except ObjectStorageError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    webhook_jobs = await stage_webhook_event(
        session,
        entity_id=user.entity_id,
        actor_id=user.id,
        event_type="project.deleted",
        data={"project_id": project.id},
        settings=settings,
    )
    await session.delete(project)
    await session.commit()
    await asyncio.gather(*(notify_background_job(job.id) for job in webhook_jobs))
