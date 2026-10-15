import asyncio
from datetime import datetime, timedelta, timezone

from backend.app.config import Settings
from backend.app.database import BackgroundJob, Base, Entity, User
import backend.app.job_service as job_service_module
from backend.app.job_routes import serialize_job
from backend.app.job_service import DurableJobQueue, GENERATION_JOB, JobWorker, scan_with_clamav
from backend.app.object_storage import (
    LocalObjectStorage,
    S3ObjectStorage,
    clean_storage_key,
)
from backend.app.schemas import FlowGraph
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


class GeneratedModel:
    async def generate_graph(self, _text, _title):
        return FlowGraph.model_validate({
            "title": "Approval",
            "nodes": [
                {"id": "start", "label": "Start", "type": "start"},
                {"id": "approve", "label": "Approve", "type": "process"},
            ],
            "edges": [{"source": "start", "target": "approve"}],
            "questions": [],
        })


def test_generation_worker_produces_the_versioned_graph_result() -> None:
    async def scenario() -> None:
        settings = Settings()
        queue = DurableJobQueue(settings)
        storage = LocalObjectStorage(settings)
        worker = JobWorker(settings, queue, storage)
        worker.model = GeneratedModel()
        job = BackgroundJob(
            id="job-1",
            entity_id="entity-1",
            created_by_id="user-1",
            kind=GENERATION_JOB,
            status="running",
            payload={"text": "Start then approve", "title": None},
            attempts=1,
            max_attempts=3,
        )

        result = await worker._execute(job)

        assert result["title"] == "Approval"
        assert [node["id"] for node in result["nodes"]] == ["start", "approve"]
        assert result["edges"][0]["source"] == "start"
        assert result["edges"][0]["target"] == "approve"

    asyncio.run(scenario())


def test_worker_claims_and_persists_a_durable_generation_job(monkeypatch) -> None:
    async def scenario() -> None:
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            poolclass=StaticPool,
        )
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with factory() as session:
            session.add(Entity(id="entity-1", name="Test workspace"))
            session.add(User(
                id="user-1",
                entity_id="entity-1",
                email="owner@example.com",
                display_name="Owner",
                password_hash="unused",
                role="admin",
            ))
            session.add(BackgroundJob(
                id="job-1",
                entity_id="entity-1",
                created_by_id="user-1",
                kind=GENERATION_JOB,
                status="queued",
                payload={"text": "Start then approve", "title": None},
                max_attempts=3,
            ))
            await session.commit()
        monkeypatch.setattr(job_service_module, "session_factory", factory)
        settings = Settings()
        worker = JobWorker(
            settings,
            DurableJobQueue(settings),
            LocalObjectStorage(settings),
        )
        worker.model = GeneratedModel()

        assert await worker.run_once() is True

        async with factory() as session:
            job = await session.get(BackgroundJob, "job-1")
            assert job.status == "succeeded"
            assert job.attempts == 1
            assert job.result["title"] == "Approval"
            assert job.completed_at is not None
        await engine.dispose()

    asyncio.run(scenario())


def test_worker_reclaims_a_running_job_after_its_lease_expires(monkeypatch) -> None:
    async def scenario() -> None:
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            poolclass=StaticPool,
        )
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with factory() as session:
            session.add(Entity(id="entity-1", name="Recovery workspace"))
            session.add(User(
                id="user-1",
                entity_id="entity-1",
                email="owner@example.com",
                display_name="Owner",
                password_hash="unused",
                role="admin",
            ))
            session.add(BackgroundJob(
                id="job-stale",
                entity_id="entity-1",
                created_by_id="user-1",
                kind=GENERATION_JOB,
                status="running",
                payload={"text": "Recover this job"},
                attempts=1,
                max_attempts=3,
                started_at=datetime.now(timezone.utc) - timedelta(minutes=10),
            ))
            await session.commit()
        monkeypatch.setattr(job_service_module, "session_factory", factory)
        settings = Settings(job_lease_seconds=60)
        worker = JobWorker(
            settings,
            DurableJobQueue(settings),
            LocalObjectStorage(settings),
        )

        claimed = await worker._claim()

        assert claimed is not None
        assert claimed.id == "job-stale"
        assert claimed.status == "running"
        assert claimed.attempts == 2
        assert claimed.started_at is not None
        await engine.dispose()

    asyncio.run(scenario())


def test_local_storage_uses_expiring_grants_and_quarantine_promotion(tmp_path) -> None:
    async def scenario() -> None:
        settings = Settings(
            storage_local_path=str(tmp_path),
            auth_secret="test-secret-that-is-long-enough-for-signed-storage-grants",
        )
        storage = LocalObjectStorage(settings)
        await storage.start()
        quarantine_key = "entity/project/file/quarantine/policy.pdf"

        grant = await storage.create_upload_grant(
            "attachment-1",
            quarantine_key,
            "application/pdf",
            1024,
        )
        token = grant.headers["X-FlowForge-Storage-Token"]
        authorization = storage.verify_upload_token("attachment-1", token)
        await storage.put(authorization["storage_key"], b"policy", "application/pdf")

        clean_key = clean_storage_key(quarantine_key)
        metadata = await storage.promote(quarantine_key, clean_key)

        assert grant.method == "PUT"
        assert metadata.size_bytes == 6
        assert await storage.read(clean_key) == b"policy"
        assert not (tmp_path / quarantine_key).exists()

    asyncio.run(scenario())


def test_s3_upload_grant_enforces_content_type_and_size_without_credentials_in_browser() -> None:
    async def scenario() -> None:
        settings = Settings(
            storage_backend="s3",
            storage_endpoint_url="http://minio:9000",
            storage_public_endpoint_url="https://storage.example.com",
            storage_access_key_id="storage-user",
            storage_secret_access_key="storage-secret",
        )
        storage = S3ObjectStorage(settings)

        grant = await storage.create_upload_grant(
            "attachment-1",
            "entity/project/attachment/quarantine/policy.pdf",
            "application/pdf",
            10_485_760,
        )

        assert grant.method == "POST"
        assert grant.url.startswith("https://storage.example.com/")
        assert grant.fields["Content-Type"] == "application/pdf"
        assert "storage-secret" not in str(grant.fields)

    asyncio.run(scenario())


def test_clamav_scanner_uses_framed_instream_protocol(monkeypatch) -> None:
    class Reader:
        async def readuntil(self, _separator):
            return b"stream: OK\0"

    class Writer:
        def __init__(self):
            self.writes = []

        def write(self, content):
            self.writes.append(content)

        async def drain(self):
            return None

        def close(self):
            return None

        async def wait_closed(self):
            return None

    writer = Writer()

    async def open_connection(_host, _port):
        return Reader(), writer

    monkeypatch.setattr(asyncio, "open_connection", open_connection)

    async def scenario() -> None:
        clean, message = await scan_with_clamav(
            b"safe attachment",
            Settings(attachment_scan_mode="clamav", clamav_host="clamav"),
        )

        assert clean is True
        assert message == "No malware detected"
        assert writer.writes[0] == b"zINSTREAM\0"
        assert writer.writes[-1] == b"\x00\x00\x00\x00"
        assert b"safe attachment" in writer.writes

    asyncio.run(scenario())


def test_job_response_never_exposes_the_private_job_payload() -> None:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    job = BackgroundJob(
        id="job-1",
        entity_id="entity-1",
        created_by_id="user-1",
        kind=GENERATION_JOB,
        status="queued",
        payload={"text": "private process description"},
        attempts=0,
        max_attempts=3,
        created_at=now,
        updated_at=now,
    )

    serialized = serialize_job(job).model_dump()

    assert "payload" not in serialized
    assert "private process description" not in str(serialized)
