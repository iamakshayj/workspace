import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from starlette.requests import Request
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.app.config import Settings
from backend.app.database import (
    BackgroundJob,
    Base,
    Entity,
    LegalHold,
    Project,
    ProjectAttachment,
    User,
)
from backend.app.job_service import DurableJobQueue, GENERATION_JOB, JobWorker
import backend.app.job_service as job_service_module
from backend.app.object_storage import LocalObjectStorage, ObjectNotFoundError
from backend.app.quota_service import (
    QuotaExceededError,
    ensure_attachment_capacity,
    ensure_generation_capacity,
    ensure_project_capacity,
)
from backend.app.rate_limit import RequestRateLimiter
from backend.app.telemetry import MetricsRegistry, request_identifiers


async def database_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, factory


def test_generation_and_project_quotas_are_enforced_from_durable_state() -> None:
    async def scenario() -> None:
        engine, factory = await database_factory()
        async with factory() as session:
            entity = Entity(
                id="entity-1",
                name="Limited workspace",
                max_projects=1,
                max_monthly_generations=1,
                max_pending_generations=1,
            )
            user = User(
                id="user-1",
                entity_id=entity.id,
                email="owner@example.com",
                display_name="Owner",
                password_hash="unused",
                role="admin",
            )
            session.add_all([entity, user])
            session.add(Project(
                id="project-1",
                owner_id=user.id,
                entity_id=entity.id,
                title="Existing",
                graph={"title": "Existing", "nodes": [], "edges": []},
            ))
            session.add(BackgroundJob(
                id="job-1",
                entity_id=entity.id,
                created_by_id=user.id,
                kind=GENERATION_JOB,
                status="queued",
                payload={"text": "private"},
            ))
            await session.commit()

            with pytest.raises(QuotaExceededError, match="projects"):
                await ensure_project_capacity(session, entity.id)
            with pytest.raises(QuotaExceededError, match="monthly generations"):
                await ensure_generation_capacity(session, entity.id)
        await engine.dispose()

    asyncio.run(scenario())


def test_attachment_quota_reserves_incomplete_direct_uploads() -> None:
    async def scenario() -> None:
        engine, factory = await database_factory()
        async with factory() as session:
            entity = Entity(id="entity-1", name="Storage", max_storage_bytes=100)
            user = User(
                id="user-1",
                entity_id=entity.id,
                email="owner@example.com",
                display_name="Owner",
                password_hash="unused",
                role="admin",
            )
            project = Project(
                id="project-1",
                owner_id=user.id,
                entity_id=entity.id,
                title="Existing",
                graph={"title": "Existing", "nodes": [], "edges": []},
            )
            session.add_all([entity, user, project])
            session.add(ProjectAttachment(
                id="attachment-1",
                entity_id=entity.id,
                project_id=project.id,
                uploaded_by_id=user.id,
                filename="reserved.bin",
                content_type="application/octet-stream",
                size_bytes=80,
                upload_status="uploading",
                scan_status="pending",
            ))
            await session.commit()

            with pytest.raises(QuotaExceededError) as error:
                await ensure_attachment_capacity(session, entity.id, 21)
            assert error.value.resource == "storage"
            await ensure_attachment_capacity(session, entity.id, 20)
        await engine.dispose()

    asyncio.run(scenario())


def test_request_limiter_returns_standard_window_information() -> None:
    async def scenario() -> None:
        settings = Settings(request_rate_limit=10, request_rate_window_seconds=60)
        limiter = RequestRateLimiter(settings)
        request = Request({
            "type": "http",
            "method": "GET",
            "path": "/api/v1/projects",
            "headers": [],
            "client": ("192.0.2.1", 1234),
        })
        results = [await limiter.check(request) for _ in range(11)]

        assert all(allowed for allowed, _, _ in results[:10])
        assert results[9][1] == 0
        assert results[10][0] is False
        assert 1 <= results[10][2] <= 60

    asyncio.run(scenario())


def test_telemetry_uses_bounded_route_labels_and_validated_trace_ids() -> None:
    registry = MetricsRegistry()
    registry.record_http("GET", "/api/v1/projects/{project_id}", 200, 0.05)
    rendered = registry.render()
    request_id, trace_id = request_identifiers("bad id with spaces", None)

    assert '/api/v1/projects/{project_id}' in rendered
    assert "project-123-secret" not in rendered
    assert request_id != "bad id with spaces"
    assert len(trace_id) == 32


def test_maintenance_purges_private_results_and_stale_quarantine_uploads(
    monkeypatch,
    tmp_path,
) -> None:
    async def scenario() -> None:
        engine, factory = await database_factory()
        monkeypatch.setattr(job_service_module, "session_factory", factory)
        now = datetime.now(timezone.utc)
        settings = Settings(
            storage_local_path=str(tmp_path),
            attachment_upload_expiry_hours=24,
            job_result_retention_days=7,
            job_history_retention_days=90,
        )
        storage = LocalObjectStorage(settings)
        await storage.start()
        stale_key = "entity-1/project-1/attachment-1/quarantine/stale.txt"
        await storage.put(stale_key, b"stale", "text/plain")
        async with factory() as session:
            entity = Entity(id="entity-1", name="Recovery")
            user = User(
                id="user-1",
                entity_id=entity.id,
                email="owner@example.com",
                display_name="Owner",
                password_hash="unused",
                role="admin",
            )
            project = Project(
                id="project-1",
                owner_id=user.id,
                entity_id=entity.id,
                title="Recovery",
                graph={"title": "Recovery", "nodes": [], "edges": []},
            )
            session.add_all([entity, user, project])
            session.add(ProjectAttachment(
                id="attachment-1",
                entity_id=entity.id,
                project_id=project.id,
                uploaded_by_id=user.id,
                filename="stale.txt",
                content_type="text/plain",
                size_bytes=5,
                storage_key=stale_key,
                upload_status="uploading",
                scan_status="pending",
                created_at=now - timedelta(days=2),
            ))
            session.add_all([
                BackgroundJob(
                    id="job-result",
                    entity_id=entity.id,
                    created_by_id=user.id,
                    kind=GENERATION_JOB,
                    status="succeeded",
                    payload={"text": "private process"},
                    result={"title": "private result"},
                    completed_at=now - timedelta(days=8),
                    created_at=now - timedelta(days=8),
                ),
                BackgroundJob(
                    id="job-history",
                    entity_id=entity.id,
                    created_by_id=user.id,
                    kind=GENERATION_JOB,
                    status="failed",
                    payload={"text": "old private process"},
                    completed_at=now - timedelta(days=100),
                    created_at=now - timedelta(days=100),
                ),
            ])
            await session.commit()

        worker = JobWorker(settings, DurableJobQueue(settings), storage)
        outcome = await worker.run_maintenance()

        assert outcome == {
            "stale_uploads_removed": 1,
            "job_results_purged": 2,
            "job_history_deleted": 1,
            "generated_artifacts_deleted": 0,
            "records_preserved_by_legal_hold": 0,
        }
        async with factory() as session:
            assert await session.get(ProjectAttachment, "attachment-1") is None
            retained = await session.get(BackgroundJob, "job-result")
            assert retained is not None
            assert retained.payload == {}
            assert retained.result is None
            assert retained.purged_at is not None
            assert await session.get(BackgroundJob, "job-history") is None
        with pytest.raises(ObjectNotFoundError):
            await storage.read(stale_key)
        await engine.dispose()

    asyncio.run(scenario())


def test_maintenance_preserves_stale_files_covered_by_a_legal_hold(monkeypatch, tmp_path) -> None:
    async def scenario() -> None:
        engine, factory = await database_factory()
        monkeypatch.setattr(job_service_module, "session_factory", factory)
        settings = Settings(storage_local_path=str(tmp_path), attachment_upload_expiry_hours=1)
        storage = LocalObjectStorage(settings)
        await storage.start()
        storage_key = "entity-1/project-1/attachment-held/quarantine/evidence.txt"
        await storage.put(storage_key, b"preserve", "text/plain")
        async with factory() as session:
            entity = Entity(id="entity-1", name="Legal")
            user = User(id="user-1", entity_id=entity.id, email="legal@example.com", display_name="Legal", password_hash="x", role="admin")
            project = Project(id="project-1", owner_id=user.id, entity_id=entity.id, title="Matter", graph={"title": "Matter", "nodes": [], "edges": []})
            attachment = ProjectAttachment(
                id="attachment-held", entity_id=entity.id, project_id=project.id,
                uploaded_by_id=user.id, filename="evidence.txt", content_type="text/plain",
                size_bytes=8, storage_key=storage_key, upload_status="uploading",
                scan_status="pending", created_at=datetime.now(timezone.utc) - timedelta(days=1),
            )
            hold = LegalHold(
                id="hold-1", entity_id=entity.id, name="Matter hold", scope_type="project",
                scope_id=project.id, reason="Preserve evidence", created_by_id=user.id,
            )
            session.add_all([entity, user, project, attachment, hold])
            await session.commit()

        outcome = await JobWorker(settings, DurableJobQueue(settings), storage).run_maintenance()
        assert outcome["stale_uploads_removed"] == 0
        assert outcome["records_preserved_by_legal_hold"] == 1
        async with factory() as session:
            assert await session.get(ProjectAttachment, "attachment-held") is not None
        assert await storage.read(storage_key) == b"preserve"
        await engine.dispose()

    asyncio.run(scenario())
