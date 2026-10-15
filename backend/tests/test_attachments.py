import asyncio
from datetime import datetime, timezone

from backend.app.config import Settings
from backend.app.database import ProjectAttachment
from backend.app.object_storage import LocalObjectStorage
from backend.app.project_routes import serialize_attachment


def test_attachment_metadata_is_serialized_without_file_content() -> None:
    attachment = ProjectAttachment(
        id="attachment-1",
        project_id="project-1",
        uploaded_by_id="user-1",
        node_id="approval",
        filename="approval-policy.pdf",
        content_type="application/pdf",
        size_bytes=2048,
        content=b"private file content",
        created_at=datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc),
    )

    serialized = serialize_attachment(attachment)

    assert serialized.filename == "approval-policy.pdf"
    assert serialized.node_id == "approval"
    assert serialized.size_bytes == 2048
    assert serialized.upload_status == "complete"
    assert serialized.scan_status == "clean"
    assert "content" not in serialized.model_dump()


def test_local_upload_grant_keeps_authorization_out_of_the_url(tmp_path) -> None:
    storage = LocalObjectStorage(Settings(storage_local_path=str(tmp_path)))
    grant = asyncio.run(storage.create_upload_grant(
        "attachment-1",
        "entity/project/quarantine/attachment-1",
        "application/pdf",
        4096,
    ))

    assert grant.url == "/api/v1/storage/uploads/attachment-1"
    token = grant.headers["X-FlowForge-Storage-Token"]
    authorization = storage.verify_upload_token("attachment-1", token)
    assert authorization["storage_key"] == "entity/project/quarantine/attachment-1"
