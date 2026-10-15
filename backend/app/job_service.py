import asyncio
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import hmac
from ipaddress import ip_address
import json
import logging
import socket
import struct
from time import monotonic, perf_counter
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import httpx

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import delete, or_, select

from .config import Settings, get_settings
from .auth import hash_invitation_token
from .artifact_service import (
    EVIDENCE_PACKAGE_JOB,
    OPERATIONAL_PACKAGE_JOB,
    PROJECT_EXPORT_JOB,
    build_project_artifact,
)
from .calendar_reminders import dispatch_due_calendar_reminders
from .database import (
    BackgroundJob,
    CalendarEventExternalAttendee,
    Entity,
    GeneratedArtifact,
    IntegrationConnection,
    Invitation,
    ProjectAttachment,
    User,
    WebhookDelivery,
    WebhookSubscription,
    session_factory,
)
from .email_service import EmailService
from .graph_service import validate_and_layout
from .model_client import LocalModelClient, ModelOutputError, ModelUnavailableError
from .object_storage import (
    ObjectNotFoundError,
    ObjectStorage,
    ObjectStorageError,
    clean_storage_key,
    object_storage,
)
from .policy_engine import is_held
from .quota_service import ensure_generation_capacity
from .secret_box import SecretBox, SecretBoxError
from .telemetry import metrics


logger = logging.getLogger("flowforge.jobs")
GENERATION_JOB = "generate_flowchart"
ATTACHMENT_SCAN_JOB = "scan_attachment"
INVITATION_EMAIL_JOB = "send_invitation_email"
MEETING_EMAIL_JOB = "send_meeting_email"
CONNECTOR_SYNC_JOB = "sync_integration"
WEBHOOK_DELIVERY_JOB = "deliver_webhook"


class JobQueueUnavailableError(RuntimeError):
    pass


class AttachmentScanError(RuntimeError):
    pass


class EmailDeliveryError(RuntimeError):
    pass


class WebhookDeliveryError(RuntimeError):
    pass


async def assert_public_webhook_target(url: str) -> None:
    hostname = urlparse(url).hostname or ""
    if hostname.lower().rstrip(".") == "localhost" or hostname.lower().rstrip(".").endswith(".local"):
        raise WebhookDeliveryError("Webhook target is not a public network address")
    try:
        records = await asyncio.to_thread(socket.getaddrinfo, hostname, None, type=socket.SOCK_STREAM)
    except OSError as error:
        raise WebhookDeliveryError("Webhook target DNS resolution failed") from error
    addresses = {record[4][0] for record in records}
    if not addresses or any(not ip_address(address).is_global for address in addresses):
        raise WebhookDeliveryError("Webhook target resolved to a private, local, or reserved address")


class DurableJobQueue:
    """Redis wake-up queue; PostgreSQL remains the durable job source of truth."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.redis: Redis | None = None
        self.local_event = asyncio.Event()
        self.started = False

    @property
    def mode(self) -> str:
        return "redis" if self.settings.redis_url else "database"

    async def start(self) -> None:
        if self.started:
            return
        if self.settings.redis_url:
            try:
                self.redis = Redis.from_url(
                    self.settings.redis_url,
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=10,
                    health_check_interval=30,
                )
                await self.redis.ping()
            except (OSError, RedisError) as error:
                if self.redis:
                    await self.redis.aclose()
                self.redis = None
                raise JobQueueUnavailableError("The background job queue is unavailable.") from error
        self.started = True

    async def stop(self) -> None:
        if self.redis:
            await self.redis.aclose()
            self.redis = None
        self.local_event.set()
        self.started = False

    async def is_ready(self) -> bool:
        if not self.started:
            return False
        if not self.redis:
            return True
        try:
            return bool(await self.redis.ping())
        except (OSError, RedisError):
            return False

    async def notify(self, job_id: str) -> None:
        if not self.started:
            raise JobQueueUnavailableError("The background job queue has not started.")
        if self.redis:
            try:
                await self.redis.lpush(self.settings.job_queue_name, job_id)
                return
            except (OSError, RedisError) as error:
                raise JobQueueUnavailableError("Could not enqueue background work.") from error
        self.local_event.set()

    async def wait(self) -> None:
        if self.redis:
            try:
                await self.redis.brpop(
                    self.settings.job_queue_name,
                    timeout=max(1, round(self.settings.job_poll_seconds)),
                )
                return
            except (OSError, RedisError):
                logger.exception("Redis job wake-up failed; falling back to database polling")
        try:
            await asyncio.wait_for(
                self.local_event.wait(),
                timeout=self.settings.job_poll_seconds,
            )
        except TimeoutError:
            pass
        finally:
            self.local_event.clear()


async def create_background_job(
    *,
    entity_id: str,
    created_by_id: str,
    kind: str,
    payload: dict[str, Any],
    settings: Settings,
) -> BackgroundJob:
    job = new_background_job(
        entity_id=entity_id,
        created_by_id=created_by_id,
        kind=kind,
        payload=payload,
        settings=settings,
    )
    async with session_factory() as session:
        if kind == GENERATION_JOB:
            await ensure_generation_capacity(session, entity_id)
        session.add(job)
        await session.commit()
        await session.refresh(job)
    await notify_background_job(job.id)
    return job


def new_background_job(
    *,
    entity_id: str,
    created_by_id: str,
    kind: str,
    payload: dict[str, Any],
    settings: Settings,
) -> BackgroundJob:
    return BackgroundJob(
        id=str(uuid4()),
        entity_id=entity_id,
        created_by_id=created_by_id,
        kind=kind,
        status="queued",
        payload=payload,
        max_attempts=settings.job_max_attempts,
    )


async def notify_background_job(job_id: str) -> None:
    try:
        await job_queue.notify(job_id)
    except JobQueueUnavailableError:
        logger.exception("Job wake-up failed; durable database polling will recover %s", job_id)


async def stage_webhook_event(
    session,
    *,
    entity_id: str,
    actor_id: str,
    event_type: str,
    data: dict[str, Any],
    settings: Settings,
) -> list[BackgroundJob]:
    """Stage webhook deliveries and jobs in the caller's database transaction.

    Webhook deliveries are an outbox: a business mutation and every matching
    delivery either commit together or roll back together. The durable worker's
    database polling means notification is only a latency optimization.
    """
    subscriptions = list(await session.scalars(select(WebhookSubscription).where(
        WebhookSubscription.entity_id == entity_id,
        WebhookSubscription.status == "active",
    )))
    matching = [
        subscription for subscription in subscriptions
        if any(
            configured == "*"
            or configured == event_type
            or (configured.endswith(".*") and event_type.startswith(configured[:-1]))
            for configured in (subscription.event_types or [])
        )
    ]
    if not matching:
        return []
    now = datetime.now(timezone.utc)
    event_id = str(uuid4())
    envelope = {
        "id": event_id,
        "type": event_type,
        "occurred_at": now.isoformat(),
        "entity_id": entity_id,
        "data": data,
    }
    jobs: list[BackgroundJob] = []
    for subscription in matching:
        delivery = WebhookDelivery(
            entity_id=entity_id,
            subscription_id=subscription.id,
            event_id=event_id,
            event_type=event_type,
            payload=envelope,
            status="queued",
            next_attempt_at=now,
        )
        session.add(delivery)
        await session.flush()
        job = new_background_job(
            entity_id=entity_id,
            created_by_id=actor_id,
            kind=WEBHOOK_DELIVERY_JOB,
            payload={"delivery_id": delivery.id},
            settings=settings,
        )
        session.add(job)
        jobs.append(job)
    return jobs


class JobWorker:
    def __init__(
        self,
        settings: Settings,
        queue: DurableJobQueue,
        storage: ObjectStorage,
    ) -> None:
        self.settings = settings
        self.queue = queue
        self.storage = storage
        self.model = LocalModelClient(settings)
        self.email = EmailService(settings)
        self.secret_box = SecretBox(settings.auth_secret)
        self.stopping = False
        self.last_maintenance_at = 0.0
        self.last_reminder_check_at = 0.0

    async def run_forever(self) -> None:
        self.stopping = False
        while not self.stopping:
            if monotonic() - self.last_reminder_check_at >= 30:
                try:
                    async with session_factory() as session:
                        reminders = await dispatch_due_calendar_reminders(session)
                    if reminders:
                        logger.info("Dispatched %s calendar reminders", len(reminders))
                except Exception:
                    logger.exception("Calendar reminder delivery failed and will retry")
                self.last_reminder_check_at = monotonic()
            if monotonic() - self.last_maintenance_at >= self.settings.maintenance_interval_seconds:
                try:
                    await self.run_maintenance()
                except Exception:
                    logger.exception("Background maintenance failed and will retry")
                self.last_maintenance_at = monotonic()
            processed = await self.run_once()
            if not processed:
                await self.queue.wait()

    async def run_once(self) -> bool:
        job = await self._claim()
        if not job:
            return False
        started = perf_counter()
        try:
            result = await self._execute(job)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            outcome = await self._fail_or_retry(job.id, error)
        else:
            await self._succeed(job.id, result)
            outcome = "succeeded"
        metrics.record_job(job.kind, outcome, perf_counter() - started)
        return True

    def stop(self) -> None:
        self.stopping = True

    async def _claim(self) -> BackgroundJob | None:
        now = datetime.now(timezone.utc)
        stale_before = now - timedelta(seconds=self.settings.job_lease_seconds)
        async with session_factory() as session:
            job = await session.scalar(
                select(BackgroundJob)
                .where(
                    or_(
                        (
                            (BackgroundJob.status == "queued")
                            & (BackgroundJob.available_at <= now)
                        ),
                        (
                            (BackgroundJob.status == "running")
                            & (BackgroundJob.started_at < stale_before)
                        ),
                    )
                )
                .order_by(BackgroundJob.available_at.asc(), BackgroundJob.created_at.asc())
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if not job:
                return None
            job.status = "running"
            job.started_at = now
            job.completed_at = None
            job.attempts = (job.attempts or 0) + 1
            job.error_code = None
            job.error_message = None
            await session.commit()
            return job

    async def _execute(self, job: BackgroundJob) -> dict[str, Any]:
        if job.kind == GENERATION_JOB:
            graph = await self.model.generate_graph(
                str(job.payload["text"]),
                job.payload.get("title"),
            )
            nodes, edges, warnings = validate_and_layout(graph)
            return {
                "title": graph.title,
                "nodes": [node.model_dump(mode="json") for node in nodes],
                "edges": [edge.model_dump(mode="json") for edge in edges],
                "questions": graph.questions,
                "warnings": [warning.model_dump(mode="json") for warning in warnings],
            }
        if job.kind == ATTACHMENT_SCAN_JOB:
            return await self._scan_attachment(str(job.payload["attachment_id"]))
        if job.kind == INVITATION_EMAIL_JOB:
            return await self._send_invitation_email(job)
        if job.kind == MEETING_EMAIL_JOB:
            return await self._send_meeting_email(job)
        if job.kind == CONNECTOR_SYNC_JOB:
            return await self._sync_integration(job)
        if job.kind == WEBHOOK_DELIVERY_JOB:
            return await self._deliver_webhook(job)
        if job.kind in {PROJECT_EXPORT_JOB, EVIDENCE_PACKAGE_JOB, OPERATIONAL_PACKAGE_JOB}:
            return await build_project_artifact(job, self.storage, self.settings)
        raise ValueError(f"Unsupported background job kind: {job.kind}")

    async def _sync_integration(self, job: BackgroundJob) -> dict[str, Any]:
        """Validate connector state and advance its durable cursor idempotently.

        Provider adapters can replace the bounded validation step without changing the
        persisted retry, cursor, health, or audit contracts owned by the job system.
        """
        integration_id = str(job.payload.get("integration_id") or "")
        async with session_factory() as session:
            integration = await session.get(IntegrationConnection, integration_id)
            if not integration or integration.entity_id != job.entity_id:
                return {"status": "skipped", "reason": "integration_missing"}
            if integration.status == "disconnected":
                return {"status": "skipped", "reason": "integration_disconnected"}
            if integration.credentials_encrypted:
                try:
                    credentials = json.loads(self.secret_box.decrypt(
                        integration.credentials_encrypted,
                        f"integration:{integration.id}",
                    ))
                except (SecretBoxError, json.JSONDecodeError) as error:
                    integration.status = "error"
                    integration.failure_count += 1
                    integration.last_error = "Encrypted connector credentials could not be validated"
                    await session.commit()
                    raise ValueError(integration.last_error) from error
                if not isinstance(credentials, dict):
                    raise ValueError("Connector credentials have an invalid shape")
            now = datetime.now(timezone.utc)
            previous_cursor = integration.sync_cursor
            cursor_seed = f"{integration.id}:{previous_cursor or 'initial'}:{now.isoformat()}"
            integration.sync_cursor = sha256(cursor_seed.encode()).hexdigest()
            integration.status = "connected"
            integration.failure_count = 0
            integration.last_error = ""
            integration.last_sync_at = now
            integration.next_sync_at = now + timedelta(minutes=15)
            await session.commit()
            return {
                "status": "validated",
                "integration_id": integration.id,
                "provider": integration.provider,
                "cursor_advanced": True,
                "records_processed": 0,
                "provider_execution_operationally_pending": integration.provider != "custom",
            }

    async def _deliver_webhook(self, job: BackgroundJob) -> dict[str, Any]:
        delivery_id = str(job.payload.get("delivery_id") or "")
        async with session_factory() as session:
            delivery = await session.get(WebhookDelivery, delivery_id)
            if not delivery or delivery.entity_id != job.entity_id:
                return {"status": "skipped", "reason": "delivery_missing"}
            subscription = await session.get(WebhookSubscription, delivery.subscription_id)
            if not subscription or subscription.status != "active":
                delivery.status = "cancelled"
                await session.commit()
                return {"status": "skipped", "reason": "subscription_inactive"}
            if delivery.status == "delivered":
                return {"status": "delivered", "idempotent": True}
            secret = self.secret_box.decrypt(subscription.signing_secret_encrypted, f"webhook:{subscription.id}")
            body = json.dumps(delivery.payload, sort_keys=True, separators=(",", ":")).encode()
            signature = hmac.new(secret.encode(), body, sha256).hexdigest()
            target_url = subscription.target_url
            event_id = delivery.event_id
            event_type = delivery.event_type
            delivery.attempts += 1
            delivery.status = "sending"
            await session.commit()
        try:
            await assert_public_webhook_target(target_url)
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0), follow_redirects=False) as client:
                response = await client.post(target_url, content=body, headers={
                    "Content-Type": "application/json",
                    "User-Agent": "Workspace-Webhook/1.0",
                    "X-Workspace-Event": event_type,
                    "X-Workspace-Event-ID": event_id,
                    "X-Workspace-Signature-256": f"sha256={signature}",
                })
            response.raise_for_status()
        except (httpx.HTTPError, OSError, WebhookDeliveryError) as error:
            async with session_factory() as session:
                delivery = await session.get(WebhookDelivery, delivery_id)
                subscription = await session.get(WebhookSubscription, delivery.subscription_id) if delivery else None
                if delivery:
                    delivery.status = "retrying"
                    delivery.status_code = getattr(getattr(error, "response", None), "status_code", None)
                    delivery.response_excerpt = type(error).__name__
                    delivery.next_attempt_at = datetime.now(timezone.utc) + timedelta(minutes=min(60, 2 ** max(1, delivery.attempts)))
                if subscription:
                    subscription.failure_count += 1
                    subscription.last_status_code = delivery.status_code if delivery else None
                await session.commit()
            raise WebhookDeliveryError("Webhook delivery failed") from error
        async with session_factory() as session:
            delivery = await session.get(WebhookDelivery, delivery_id)
            subscription = await session.get(WebhookSubscription, delivery.subscription_id) if delivery else None
            now = datetime.now(timezone.utc)
            if delivery:
                delivery.status = "delivered"; delivery.status_code = response.status_code
                delivery.response_excerpt = ""; delivery.delivered_at = now
            if subscription:
                subscription.failure_count = 0; subscription.last_delivery_at = now
                subscription.last_status_code = response.status_code
            await session.commit()
        return {"status": "delivered", "status_code": response.status_code, "event_id": event_id}

    async def _send_invitation_email(self, job: BackgroundJob) -> dict[str, Any]:
        invitation_id = str(job.payload.get("invitation_id") or "")
        encrypted_token = str(job.payload.get("encrypted_token") or "")
        try:
            token = self.secret_box.decrypt(encrypted_token, "invitation_email")
        except SecretBoxError as error:
            raise EmailDeliveryError("Invitation delivery secret is invalid") from error
        token_hash = hash_invitation_token(token)
        async with session_factory() as session:
            invitation = await session.get(Invitation, invitation_id)
            if not invitation or invitation.entity_id != job.entity_id:
                return {"delivery": "skipped", "reason": "invitation_missing"}
            expires_at = invitation.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if (
                invitation.status != "pending"
                or invitation.token_hash != token_hash
                or expires_at <= datetime.now(timezone.utc)
            ):
                return {"delivery": "skipped", "reason": "invitation_stale"}
            entity = await session.get(Entity, invitation.entity_id)
            inviter = await session.get(User, invitation.invited_by_id)
            if not entity or not inviter:
                raise EmailDeliveryError("Invitation sender or workspace is unavailable")
            invitation.delivery_status = "sending"
            await session.commit()
            email_values = {
                "recipient_email": invitation.email,
                "recipient_name": invitation.display_name,
                "entity_name": entity.name,
                "inviter_name": inviter.display_name,
                "role": invitation.role,
                "setup_url": (
                    f"{self.settings.frontend_url.rstrip('/')}"
                    f"/accept-invite?token={token}"
                ),
                "expires_at": expires_at,
            }
        try:
            delivery = await self.email.send_invitation(**email_values)
        except Exception as error:
            async with session_factory() as session:
                invitation = await session.get(Invitation, invitation_id)
                if invitation and invitation.token_hash == token_hash:
                    invitation.delivery_status = "retrying"
                    await session.commit()
            raise EmailDeliveryError("Invitation email delivery failed") from error
        async with session_factory() as session:
            invitation = await session.get(Invitation, invitation_id)
            if invitation and invitation.token_hash == token_hash:
                invitation.delivery_status = delivery
                await session.commit()
        return {"delivery": delivery}

    async def _send_meeting_email(self, job: BackgroundJob) -> dict[str, Any]:
        attendee_id = str(job.payload.get("external_attendee_id") or "")
        email_values = {
            key: str(job.payload.get(key) or "")
            for key in (
                "recipient_email", "organizer_name", "title", "starts_at", "ends_at",
                "timezone_name", "action", "description", "location", "meeting_url",
                "recurrence",
            )
        }
        try:
            delivery = await self.email.send_meeting_invitation(**email_values)
        except Exception as error:
            async with session_factory() as session:
                attendee = await session.get(CalendarEventExternalAttendee, attendee_id)
                if attendee:
                    attendee.delivery_status = "retrying"
                    await session.commit()
            raise EmailDeliveryError("Meeting email delivery failed") from error
        async with session_factory() as session:
            attendee = await session.get(CalendarEventExternalAttendee, attendee_id)
            if attendee:
                attendee.delivery_status = delivery
                attendee.updated_at = datetime.now(timezone.utc)
                await session.commit()
        return {"delivery": delivery}

    async def _scan_attachment(self, attachment_id: str) -> dict[str, Any]:
        async with session_factory() as session:
            attachment = await session.get(ProjectAttachment, attachment_id)
            if not attachment or not attachment.storage_key:
                raise ObjectStorageError("Attachment metadata or object key is missing.")
            if attachment.scan_status == "clean":
                return {
                    "attachment_id": attachment_id,
                    "clean": True,
                    "message": attachment.scan_message or "No malware detected",
                }
            if attachment.scan_status == "blocked":
                return {
                    "attachment_id": attachment_id,
                    "clean": False,
                    "message": attachment.scan_message or "Attachment was blocked",
                }
            storage_key = attachment.storage_key

        try:
            content = await self.storage.read(storage_key)
        except ObjectNotFoundError:
            recovered_key = clean_storage_key(storage_key)
            content = await self.storage.read(recovered_key)
            async with session_factory() as session:
                attachment = await session.get(ProjectAttachment, attachment_id)
                if attachment:
                    attachment.storage_key = recovered_key
                    attachment.scan_status = "clean"
                    attachment.scan_message = "Recovered completed security scan"
                    await session.commit()
            return {
                "attachment_id": attachment_id,
                "clean": True,
                "message": "Recovered completed security scan",
            }
        if self.settings.attachment_scan_mode.lower() == "clamav":
            clean, message = await scan_with_clamav(content, self.settings)
        else:
            clean, message = True, "Scanning disabled in this environment"

        if not clean:
            await self.storage.delete(storage_key)
            promoted_key = storage_key
        else:
            promoted_key = clean_storage_key(storage_key)
            await self.storage.promote(storage_key, promoted_key)
        async with session_factory() as session:
            attachment = await session.get(ProjectAttachment, attachment_id)
            if attachment:
                attachment.scan_status = "clean" if clean else "blocked"
                attachment.scan_message = message[:240]
                if clean:
                    attachment.storage_key = promoted_key
                await session.commit()
            elif clean:
                await self.storage.delete(promoted_key)
        return {"attachment_id": attachment_id, "clean": clean, "message": message}

    async def _succeed(self, job_id: str, result: dict[str, Any]) -> None:
        async with session_factory() as session:
            job = await session.get(BackgroundJob, job_id)
            if not job:
                return
            job.status = "succeeded"
            job.result = result
            if job.kind in {INVITATION_EMAIL_JOB, MEETING_EMAIL_JOB}:
                job.payload = {}
            job.completed_at = datetime.now(timezone.utc)
            await session.commit()

    async def _fail_or_retry(self, job_id: str, error: Exception) -> str:
        retryable = isinstance(
            error,
            (
                ModelUnavailableError,
                ObjectStorageError,
                AttachmentScanError,
                EmailDeliveryError,
                WebhookDeliveryError,
                OSError,
            ),
        )
        async with session_factory() as session:
            job = await session.get(BackgroundJob, job_id)
            if not job:
                return "missing"
            job.error_code = error_code(error)
            job.error_message = str(error)[:500] or "Background work failed."
            if retryable and job.attempts < job.max_attempts:
                job.status = "queued"
                job.available_at = datetime.now(timezone.utc) + timedelta(
                    seconds=min(60, 2 ** max(1, job.attempts))
                )
                job.started_at = None
            else:
                job.status = "failed"
                job.completed_at = datetime.now(timezone.utc)
                if job.kind == ATTACHMENT_SCAN_JOB:
                    attachment_id = str(job.payload.get("attachment_id") or "")
                    attachment = await session.get(ProjectAttachment, attachment_id)
                    if attachment:
                        attachment.scan_status = "error"
                        attachment.scan_message = job.error_message[:240]
                if job.kind == INVITATION_EMAIL_JOB:
                    invitation_id = str(job.payload.get("invitation_id") or "")
                    invitation = await session.get(Invitation, invitation_id)
                    if invitation:
                        invitation.delivery_status = "failed"
                    job.payload = {}
                    job.purged_at = datetime.now(timezone.utc)
                if job.kind == WEBHOOK_DELIVERY_JOB:
                    delivery_id = str(job.payload.get("delivery_id") or "")
                    delivery = await session.get(WebhookDelivery, delivery_id)
                    if delivery:
                        delivery.status = "failed"
                        delivery.next_attempt_at = datetime.now(timezone.utc)
            await session.commit()
            outcome = job.status
        if outcome == "queued":
            try:
                await self.queue.notify(job_id)
            except JobQueueUnavailableError:
                logger.exception("Could not wake a retry; durable database polling will recover it")
        logger.warning("Background job %s failed: %s", job_id, error)
        return outcome

    async def run_maintenance(self) -> dict[str, int]:
        now = datetime.now(timezone.utc)
        upload_cutoff = now - timedelta(hours=self.settings.attachment_upload_expiry_hours)
        result_cutoff = now - timedelta(days=self.settings.job_result_retention_days)
        history_cutoff = now - timedelta(days=self.settings.job_history_retention_days)
        cleaned_uploads = 0
        purged_results = 0
        deleted_history = 0
        deleted_artifacts = 0
        preserved_by_hold = 0

        async with session_factory() as session:
            expired_artifacts = list(await session.scalars(
                select(GeneratedArtifact).where(GeneratedArtifact.expires_at < now)
            ))
            for artifact in expired_artifacts:
                if (
                    await is_held(session, artifact.entity_id, "entity", artifact.entity_id)
                    or await is_held(session, artifact.entity_id, "project", artifact.project_id)
                    or await is_held(session, artifact.entity_id, "file", artifact.id)
                ):
                    preserved_by_hold += 1
                    continue
                try:
                    await self.storage.delete(artifact.storage_key)
                except ObjectStorageError:
                    logger.exception("Could not remove an expired generated artifact")
                    continue
                await session.delete(artifact)
                deleted_artifacts += 1

            stale_uploads = list(await session.scalars(
                select(ProjectAttachment).where(
                    ProjectAttachment.upload_status == "uploading",
                    ProjectAttachment.created_at < upload_cutoff,
                )
            ))
            for attachment in stale_uploads:
                if (
                    await is_held(session, attachment.entity_id, "entity", attachment.entity_id)
                    or await is_held(session, attachment.entity_id, "project", attachment.project_id)
                    or await is_held(session, attachment.entity_id, "file", attachment.id)
                ):
                    preserved_by_hold += 1
                    continue
                if attachment.storage_key:
                    try:
                        await self.storage.delete(attachment.storage_key)
                    except ObjectStorageError:
                        logger.exception("Could not remove a stale quarantine object")
                        continue
                await session.delete(attachment)
                cleaned_uploads += 1

            completed_jobs = list(await session.scalars(
                select(BackgroundJob).where(
                    BackgroundJob.status.in_(("succeeded", "failed")),
                    BackgroundJob.completed_at < result_cutoff,
                    BackgroundJob.purged_at.is_(None),
                )
            ))
            for job in completed_jobs:
                job.payload = {}
                job.result = None
                job.error_message = None
                job.purged_at = now
                purged_results += 1

            delete_result = await session.execute(
                delete(BackgroundJob).where(
                    BackgroundJob.status.in_(("succeeded", "failed")),
                    BackgroundJob.completed_at < history_cutoff,
                ).execution_options(synchronize_session=False)
            )
            deleted_history = max(0, int(delete_result.rowcount or 0))
            await session.commit()

        metrics.record_maintenance("stale_uploads_removed", cleaned_uploads)
        metrics.record_maintenance("job_results_purged", purged_results)
        metrics.record_maintenance("job_history_deleted", deleted_history)
        metrics.record_maintenance("generated_artifacts_deleted", deleted_artifacts)
        metrics.record_maintenance("records_preserved_by_legal_hold", preserved_by_hold)
        if cleaned_uploads or purged_results or deleted_history or deleted_artifacts or preserved_by_hold:
            logging.getLogger("flowforge.maintenance").info(
                "Background retention completed",
                extra={
                    "event": "maintenance.completed",
                    "resource": (
                        f"uploads={cleaned_uploads},results={purged_results},"
                        f"history={deleted_history}"
                        f",artifacts={deleted_artifacts},holds={preserved_by_hold}"
                    ),
                },
            )
        return {
            "stale_uploads_removed": cleaned_uploads,
            "job_results_purged": purged_results,
            "job_history_deleted": deleted_history,
            "generated_artifacts_deleted": deleted_artifacts,
            "records_preserved_by_legal_hold": preserved_by_hold,
        }


def error_code(error: Exception) -> str:
    if isinstance(error, ModelUnavailableError):
        return "model_unavailable"
    if isinstance(error, ModelOutputError):
        return "invalid_model_output"
    if isinstance(error, AttachmentScanError):
        return "scanner_unavailable"
    if isinstance(error, ObjectStorageError):
        return "storage_unavailable"
    if isinstance(error, EmailDeliveryError):
        return "email_unavailable"
    return "job_failed"


async def scan_with_clamav(content: bytes, settings: Settings) -> tuple[bool, str]:
    if not settings.clamav_host:
        raise AttachmentScanError("ClamAV host is not configured.")
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(settings.clamav_host, settings.clamav_port),
            timeout=settings.clamav_timeout_seconds,
        )
        writer.write(b"zINSTREAM\0")
        for offset in range(0, len(content), 1024 * 1024):
            chunk = content[offset : offset + 1024 * 1024]
            writer.write(struct.pack(">I", len(chunk)))
            writer.write(chunk)
            await writer.drain()
        writer.write(struct.pack(">I", 0))
        await writer.drain()
        response = await asyncio.wait_for(
            reader.readuntil(b"\0"),
            timeout=settings.clamav_timeout_seconds,
        )
        writer.close()
        await writer.wait_closed()
    except (OSError, TimeoutError, asyncio.IncompleteReadError) as error:
        raise AttachmentScanError("ClamAV could not scan the attachment.") from error
    result = response.rstrip(b"\0").decode("utf-8", "replace")
    if result.endswith(" OK"):
        return True, "No malware detected"
    if result.endswith(" FOUND"):
        return False, result.rsplit(": ", 1)[-1]
    raise AttachmentScanError(f"ClamAV returned an unexpected response: {result[:180]}")


settings = get_settings()
job_queue = DurableJobQueue(settings)
job_worker = JobWorker(settings, job_queue, object_storage)
