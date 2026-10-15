import asyncio
import logging
from uuid import uuid4

from sqlalchemy import select

from .config import get_settings
from .database import Project, ProjectAttachment, session_factory, verify_database_revision
from .job_service import ATTACHMENT_SCAN_JOB, create_background_job, job_queue
from .object_storage import clean_storage_key, object_storage


logger = logging.getLogger("flowforge.attachment_migration")


async def migrate_legacy_attachments() -> int:
    settings = get_settings()
    if settings.environment.strip().lower() == "production":
        await verify_database_revision()
    await object_storage.start()
    await job_queue.start()
    migrated = 0
    try:
        while True:
            async with session_factory() as session:
                row = (
                    await session.execute(
                        select(ProjectAttachment, Project)
                        .join(Project, Project.id == ProjectAttachment.project_id)
                        .where(
                            ProjectAttachment.storage_key.is_(None),
                            ProjectAttachment.content.is_not(None),
                        )
                        .order_by(ProjectAttachment.created_at.asc())
                        .limit(1)
                        .with_for_update(skip_locked=True)
                    )
                ).first()
                if not row:
                    break
                attachment, project = row
                content = attachment.content or b""
                if not content:
                    attachment.content = None
                    await session.commit()
                    continue
                key_id = attachment.id or str(uuid4())
                quarantine_key = (
                    f"{project.entity_id}/{project.id}/{key_id}/quarantine/"
                    f"{attachment.filename}"
                )
                metadata = await object_storage.put(
                    quarantine_key,
                    content,
                    attachment.content_type,
                )
                scan_required = settings.attachment_scan_mode.lower() == "clamav"
                storage_key = quarantine_key
                if not scan_required:
                    storage_key = clean_storage_key(quarantine_key)
                    metadata = await object_storage.promote(quarantine_key, storage_key)
                attachment.storage_key = storage_key
                attachment.entity_id = project.entity_id
                attachment.content = None
                attachment.upload_status = "complete"
                attachment.scan_status = "queued" if scan_required else "clean"
                attachment.scan_message = (
                    None if scan_required else "Migrated to object storage"
                )
                attachment.object_etag = metadata.etag
                attachment.uploaded_at = attachment.created_at
                await session.commit()
                entity_id = project.entity_id
                uploader_id = attachment.uploaded_by_id
                attachment_id = attachment.id
            if scan_required:
                await create_background_job(
                    entity_id=entity_id,
                    created_by_id=uploader_id,
                    kind=ATTACHMENT_SCAN_JOB,
                    payload={"attachment_id": attachment_id},
                    settings=settings,
                )
            migrated += 1
            logger.info("Migrated attachment %s", attachment_id)
    finally:
        await job_queue.stop()
    return migrated


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    count = asyncio.run(migrate_legacy_attachments())
    logger.info("Migrated %s legacy attachments", count)


if __name__ == "__main__":
    main()
