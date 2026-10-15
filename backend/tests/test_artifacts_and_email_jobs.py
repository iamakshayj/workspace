import asyncio
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
from zipfile import ZipFile

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.app.artifact_service import (
    EVIDENCE_PACKAGE_JOB,
    OPERATIONAL_PACKAGE_JOB,
    PROJECT_EXPORT_JOB,
    build_project_artifact,
)
import backend.app.artifact_service as artifact_service_module
from backend.app.auth import hash_invitation_token
from backend.app.config import Settings
from backend.app.database import (
    BackgroundJob,
    Base,
    CalendarEvent,
    CalendarEventExternalAttendee,
    Entity,
    GeneratedArtifact,
    Invitation,
    Project,
    ProjectRevision,
    User,
)
from backend.app.job_service import (
    DurableJobQueue,
    INVITATION_EMAIL_JOB,
    JobWorker,
    MEETING_EMAIL_JOB,
)
import backend.app.job_service as job_service_module
from backend.app.object_storage import LocalObjectStorage, ObjectNotFoundError
from backend.app.secret_box import SecretBox, SecretBoxError


async def database_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, factory


def test_secret_box_uses_authenticated_purpose_bound_encryption() -> None:
    box = SecretBox("test-secret-with-sufficient-entropy")
    envelope = box.encrypt("invitation-token", "invitation_email")

    assert "invitation-token" not in envelope
    assert box.decrypt(envelope, "invitation_email") == "invitation-token"
    with pytest.raises(SecretBoxError):
        box.decrypt(envelope, "another_purpose")
    with pytest.raises(SecretBoxError):
        box.decrypt(envelope[:-2] + "aa", "invitation_email")
    with pytest.raises(SecretBoxError):
        box.decrypt("v1.not-base64!", "invitation_email")


def test_invitation_email_job_decrypts_only_in_worker_and_redacts_payload(
    monkeypatch,
    tmp_path,
) -> None:
    class CapturingEmail:
        def __init__(self):
            self.values = None

        async def send_invitation(self, **values):
            self.values = values
            return "sent"

    async def scenario() -> None:
        engine, factory = await database_factory()
        monkeypatch.setattr(job_service_module, "session_factory", factory)
        settings = Settings(
            auth_secret="test-secret-with-sufficient-entropy-for-email-jobs",
            storage_local_path=str(tmp_path),
        )
        token = "one-time-setup-token"
        encrypted = SecretBox(settings.auth_secret).encrypt(token, "invitation_email")
        async with factory() as session:
            session.add(Entity(id="entity-1", name="Northwind"))
            session.add(User(
                id="user-1",
                entity_id="entity-1",
                email="owner@example.com",
                display_name="Avery Admin",
                password_hash="unused",
                role="admin",
            ))
            session.add(Invitation(
                id="invitation-1",
                entity_id="entity-1",
                invited_by_id="user-1",
                email="new.member@example.com",
                display_name="New Member",
                role="basic",
                status="pending",
                token_hash=hash_invitation_token(token),
                delivery_status="queued",
                expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            ))
            session.add(BackgroundJob(
                id="job-email",
                entity_id="entity-1",
                created_by_id="user-1",
                kind=INVITATION_EMAIL_JOB,
                status="queued",
                payload={"invitation_id": "invitation-1", "encrypted_token": encrypted},
            ))
            await session.commit()
        worker = JobWorker(
            settings,
            DurableJobQueue(settings),
            LocalObjectStorage(settings),
        )
        email = CapturingEmail()
        worker.email = email

        assert await worker.run_once() is True

        assert email.values["setup_url"].endswith(f"token={token}")
        async with factory() as session:
            invitation = await session.get(Invitation, "invitation-1")
            job = await session.get(BackgroundJob, "job-email")
            assert invitation.delivery_status == "sent"
            assert job.status == "succeeded"
            assert job.payload == {}
            assert token not in json.dumps(job.result)
        await engine.dispose()

    asyncio.run(scenario())


def test_external_meeting_email_job_updates_delivery_status(monkeypatch, tmp_path) -> None:
    class CapturingEmail:
        def __init__(self):
            self.values = None

        async def send_meeting_invitation(self, **values):
            self.values = values
            return "sent"

    async def scenario() -> None:
        engine, factory = await database_factory()
        monkeypatch.setattr(job_service_module, "session_factory", factory)
        settings = Settings(storage_local_path=str(tmp_path))
        starts_at = datetime(2026, 9, 3, 15, 0, tzinfo=timezone.utc)
        async with factory() as session:
            session.add(Entity(id="entity-meeting", name="Northwind"))
            session.add(User(
                id="meeting-owner", entity_id="entity-meeting", email="owner@example.com",
                display_name="Avery Admin", password_hash="unused", role="admin",
            ))
            session.add(CalendarEvent(
                id="meeting-1", entity_id="entity-meeting", organizer_id="meeting-owner",
                title="Client review", starts_at=starts_at,
                ends_at=starts_at + timedelta(minutes=30), timezone="America/Chicago",
            ))
            session.add(CalendarEventExternalAttendee(
                id="external-1", event_id="meeting-1", email="client@example.net",
                delivery_status="queued",
            ))
            session.add(BackgroundJob(
                id="job-meeting-email", entity_id="entity-meeting", created_by_id="meeting-owner",
                kind=MEETING_EMAIL_JOB, status="queued",
                payload={
                    "external_attendee_id": "external-1",
                    "recipient_email": "client@example.net",
                    "organizer_name": "Avery Admin",
                    "title": "Client review",
                    "starts_at": starts_at.isoformat(),
                    "ends_at": (starts_at + timedelta(minutes=30)).isoformat(),
                    "timezone_name": "America/Chicago",
                    "action": "invitation",
                    "description": "Review the launch plan",
                    "location": "Online",
                    "meeting_url": "https://meet.example.com/client-review",
                },
            ))
            await session.commit()
        worker = JobWorker(settings, DurableJobQueue(settings), LocalObjectStorage(settings))
        email = CapturingEmail()
        worker.email = email

        assert await worker.run_once() is True
        assert email.values["recipient_email"] == "client@example.net"
        async with factory() as session:
            attendee = await session.get(CalendarEventExternalAttendee, "external-1")
            job = await session.get(BackgroundJob, "job-meeting-email")
            assert attendee.delivery_status == "sent"
            assert job.status == "succeeded"
            assert job.payload == {}
        await engine.dispose()

    asyncio.run(scenario())


def test_worker_builds_svg_json_and_checksum_evidence_artifacts(
    monkeypatch,
    tmp_path,
) -> None:
    async def scenario() -> None:
        engine, factory = await database_factory()
        monkeypatch.setattr(artifact_service_module, "session_factory", factory)
        monkeypatch.setattr(job_service_module, "session_factory", factory)
        settings = Settings(storage_local_path=str(tmp_path), artifact_retention_days=7)
        storage = LocalObjectStorage(settings)
        await storage.start()
        graph = {
            "title": "Approval",
            "nodes": [
                {"id": "start", "label": "Start", "type": "start", "x": 40, "y": 80},
                {"id": "approve", "label": "Approve", "type": "process", "x": 320, "y": 80,
                 "owner": "Finance", "control_id": "CTRL-1", "risk_level": "high",
                 "evidence_requirement": "Approval record"},
            ],
            "edges": [{"source": "start", "target": "approve", "label": "Next"}],
            "questions": [],
            "warnings": [],
        }
        async with factory() as session:
            session.add(Entity(id="entity-1", name="Northwind"))
            session.add(User(
                id="user-1",
                entity_id="entity-1",
                email="owner@example.com",
                display_name="Owner",
                password_hash="unused",
                role="admin",
            ))
            session.add(Project(
                id="project-1",
                entity_id="entity-1",
                owner_id="user-1",
                title="Approval",
                source_text="Start then approve",
                graph=graph,
            ))
            session.add(ProjectRevision(
                id="revision-1",
                project_id="project-1",
                version=1,
                title="Approval",
                source_text="Start then approve",
                graph=graph,
                created_by_id="user-1",
            ))
            await session.commit()

        jobs = [
            BackgroundJob(
                id="job-svg",
                entity_id="entity-1",
                created_by_id="user-1",
                kind=PROJECT_EXPORT_JOB,
                status="running",
                payload={"project_id": "project-1", "artifact_kind": "export", "format": "svg"},
            ),
            BackgroundJob(
                id="job-json",
                entity_id="entity-1",
                created_by_id="user-1",
                kind=PROJECT_EXPORT_JOB,
                status="running",
                payload={"project_id": "project-1", "artifact_kind": "export", "format": "json"},
            ),
            BackgroundJob(
                id="job-evidence",
                entity_id="entity-1",
                created_by_id="user-1",
                kind=EVIDENCE_PACKAGE_JOB,
                status="running",
                payload={
                    "project_id": "project-1",
                    "artifact_kind": "evidence_package",
                    "format": "zip",
                },
            ),
            BackgroundJob(
                id="job-operations",
                entity_id="entity-1",
                created_by_id="user-1",
                kind=OPERATIONAL_PACKAGE_JOB,
                status="running",
                payload={
                    "project_id": "project-1",
                    "artifact_kind": "operational_package",
                    "format": "zip",
                },
            ),
        ]
        async with factory() as session:
            session.add_all(jobs)
            await session.commit()
        results = [await build_project_artifact(job, storage, settings) for job in jobs]

        async with factory() as session:
            svg = await session.get(GeneratedArtifact, results[0]["artifact_id"])
            json_artifact = await session.get(GeneratedArtifact, results[1]["artifact_id"])
            evidence = await session.get(GeneratedArtifact, results[2]["artifact_id"])
            operations = await session.get(GeneratedArtifact, results[3]["artifact_id"])
            svg_content = await storage.read(svg.storage_key)
            json_content = json.loads(await storage.read(json_artifact.storage_key))
            evidence_content = await storage.read(evidence.storage_key)
            operations_content = await storage.read(operations.storage_key)
            evidence_key = evidence.storage_key
            evidence.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            await session.commit()

        assert svg_content.startswith(b"<svg")
        assert b"Approval" in svg_content
        assert json_content["project"]["id"] == "project-1"
        with ZipFile(BytesIO(evidence_content)) as archive:
            names = set(archive.namelist())
            assert {"manifest.json", "flowchart.json", "revisions.json", "audit-events.json"} <= names
            manifest = json.loads(archive.read("manifest.json"))
            assert manifest["package_kind"] == "flowforge_evidence_package"
            assert len(manifest["files"]["flowchart.json"]["sha256"]) == 64
        with ZipFile(BytesIO(operations_content)) as archive:
            names = set(archive.namelist())
            assert {"SOP.md", "RACI.csv", "controls.csv", "test-cases.md", "manifest.json"} <= names
            manifest = json.loads(archive.read("manifest.json"))
            assert manifest["package_kind"] == "flowforge_operational_package"
            assert b"CTRL-1" in archive.read("controls.csv")

        worker = JobWorker(settings, DurableJobQueue(settings), storage)
        cleanup = await worker.run_maintenance()
        assert cleanup["generated_artifacts_deleted"] == 1
        with pytest.raises(ObjectNotFoundError):
            await storage.read(evidence_key)
        await engine.dispose()

    asyncio.run(scenario())
