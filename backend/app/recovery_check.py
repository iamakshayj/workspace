import argparse
import asyncio
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from .config import get_settings
from .database import (
    AuditEvent,
    BackgroundJob,
    Entity,
    EXPECTED_DATABASE_REVISION,
    GeneratedArtifact,
    Project,
    ProjectAttachment,
    ProjectRevision,
    ProcessEvent,
    ProcessEventImport,
    ProcessInsight,
    User,
    session_factory,
    verify_database_revision,
)
from .object_storage import object_storage


COUNT_MODELS = {
    "entities": Entity,
    "users": User,
    "projects": Project,
    "project_revisions": ProjectRevision,
    "audit_events": AuditEvent,
    "project_attachments": ProjectAttachment,
    "background_jobs": BackgroundJob,
    "generated_artifacts": GeneratedArtifact,
    "process_event_imports": ProcessEventImport,
    "process_events": ProcessEvent,
    "process_insights": ProcessInsight,
}

COMPARABLE_FIELDS = (
    "expected_database_revision",
    "counts",
    "attachment_bytes",
    "artifact_bytes",
    "projects_by_entity",
    "unassigned_projects",
)


def snapshot_digest(values: dict[str, Any]) -> str:
    stable = {field: values.get(field) for field in COMPARABLE_FIELDS}
    return sha256(
        json.dumps(stable, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


async def collect_snapshot() -> dict[str, Any]:
    async with session_factory() as session:
        counts = {
            name: int(await session.scalar(select(func.count(model.id))) or 0)
            for name, model in COUNT_MODELS.items()
        }
        attachment_bytes = int(
            await session.scalar(
                select(func.coalesce(func.sum(ProjectAttachment.size_bytes), 0)).where(
                    ProjectAttachment.upload_status == "complete"
                )
            )
            or 0
        )
        artifact_bytes = int(
            await session.scalar(
                select(func.coalesce(func.sum(GeneratedArtifact.size_bytes), 0))
            )
            or 0
        )
        entity_rows = (
            await session.execute(
                select(Entity.id, func.count(Project.id))
                .outerjoin(Project, Project.entity_id == Entity.id)
                .group_by(Entity.id)
                .order_by(Entity.id)
            )
        ).all()
        unassigned_projects = int(
            await session.scalar(
                select(func.count(Project.id)).where(Project.entity_id.is_(None))
            )
            or 0
        )
    stable = {
        "expected_database_revision": EXPECTED_DATABASE_REVISION,
        "counts": counts,
        "attachment_bytes": attachment_bytes,
        "artifact_bytes": artifact_bytes,
        "projects_by_entity": {entity_id: int(count) for entity_id, count in entity_rows},
        "unassigned_projects": unassigned_projects,
    }
    digest = snapshot_digest(stable)
    return {
        "schema_version": 1,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "snapshot_sha256": digest,
        **stable,
    }


async def verify_objects(limit: int) -> list[str]:
    failures: list[str] = []
    async with session_factory() as session:
        attachment_keys = list(await session.scalars(
            select(ProjectAttachment.storage_key).where(
                ProjectAttachment.upload_status == "complete",
                ProjectAttachment.scan_status == "clean",
                ProjectAttachment.storage_key.is_not(None),
            ).order_by(ProjectAttachment.id).limit(limit if limit > 0 else None)
        ))
        artifact_keys = list(await session.scalars(
            select(GeneratedArtifact.storage_key)
            .order_by(GeneratedArtifact.id)
            .limit(limit if limit > 0 else None)
        ))
    for storage_key in [*attachment_keys, *artifact_keys]:
        try:
            await object_storage.head(str(storage_key))
        except Exception:
            failures.append(str(storage_key))
    return failures


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    if settings.environment.strip().lower() == "production":
        await verify_database_revision()
    current = await collect_snapshot()
    if args.command == "snapshot":
        print(json.dumps(current, indent=2, sort_keys=True))
        return 0

    expected = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    differences = {
        field: {"expected": expected.get(field), "actual": current.get(field)}
        for field in COMPARABLE_FIELDS
        if expected.get(field) != current.get(field)
    }
    expected_digest = snapshot_digest(expected)
    if expected.get("snapshot_sha256") != expected_digest:
        differences["manifest_snapshot_sha256"] = {
            "expected": expected_digest,
            "actual": expected.get("snapshot_sha256"),
        }
    await object_storage.start()
    missing_objects = await verify_objects(args.sample_objects)
    report = {
        "status": "passed" if not differences and not missing_objects else "failed",
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "differences": differences,
        "missing_objects": missing_objects,
        "actual_snapshot_sha256": current["snapshot_sha256"],
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("snapshot")
    verify = subparsers.add_parser("verify")
    verify.add_argument("--manifest", required=True)
    verify.add_argument(
        "--sample-objects",
        type=int,
        default=100,
        help="Maximum objects to HEAD per category; use 0 for all.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(parse_args())))
