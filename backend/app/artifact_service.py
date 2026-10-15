from datetime import date, datetime, timedelta, timezone
import csv
from hashlib import sha256
from html import escape
from io import BytesIO, StringIO
import json
import re
import textwrap
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from sqlalchemy import select

from .config import Settings
from .database import (
    AuditEvent,
    BackgroundJob,
    GeneratedArtifact,
    Project,
    ProjectApproval,
    ProjectAttachment,
    ProjectCollaborator,
    ProjectDeliverable,
    ProjectNote,
    ProjectRevision,
    ProjectTask,
    ProcessEventImport,
    ProcessInsight,
    User,
    session_factory,
)
from .object_storage import ObjectStorage
from .quota_service import ensure_artifact_capacity


PROJECT_EXPORT_JOB = "export_project"
EVIDENCE_PACKAGE_JOB = "build_evidence_package"
OPERATIONAL_PACKAGE_JOB = "build_operational_package"


def json_default(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        if isinstance(value, datetime) and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        default=json_default,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ).encode("utf-8")


def safe_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:80] or "flowchart"


def project_export_payload(project: Project) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "project": {
            "id": project.id,
            "title": project.title,
            "description": project.description,
            "status": project.status,
            "visibility": project.visibility,
            "approval_status": project.approval_status,
            "owner_id": project.owner_id,
            "profile": project.profile or {},
            "document_revision": project.revision,
            "created_at": project.created_at,
            "updated_at": project.updated_at,
        },
        "graph": project.graph,
    }


def graph_svg(project: Project) -> bytes:
    graph = project.graph or {}
    source_nodes = graph.get("nodes", [])
    nodes: list[dict[str, Any]] = []
    for index, source in enumerate(source_nodes):
        node = dict(source)
        node["x"] = float(source.get("x", 80 + (index % 4) * 260))
        node["y"] = float(source.get("y", 80 + (index // 4) * 160))
        node["width"] = float(source.get("width", 180))
        node["height"] = float(source.get("height", 76))
        nodes.append(node)
    if not nodes:
        width, height = 800, 450
    else:
        width = max(800, int(max(node["x"] + node["width"] for node in nodes) + 100))
        height = max(450, int(max(node["y"] + node["height"] for node in nodes) + 100))
    nodes_by_id = {str(node.get("id")): node for node in nodes}
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        "<defs><marker id=\"arrow\" viewBox=\"0 0 10 10\" refX=\"9\" refY=\"5\" markerWidth=\"8\" markerHeight=\"8\" orient=\"auto-start-reverse\"><path d=\"M 0 0 L 10 5 L 0 10 z\" fill=\"#475569\"/></marker></defs>",
        '<rect width="100%" height="100%" fill="#f8fafc"/>',
        f'<text x="40" y="44" font-family="Arial,sans-serif" font-size="24" font-weight="700" fill="#172033">{escape(project.title)}</text>',
    ]
    for edge in graph.get("edges", []):
        source = nodes_by_id.get(str(edge.get("source")))
        target = nodes_by_id.get(str(edge.get("target")))
        if not source or not target:
            continue
        x1 = source["x"] + source["width"] / 2
        y1 = source["y"] + source["height"] / 2
        x2 = target["x"] + target["width"] / 2
        y2 = target["y"] + target["height"] / 2
        marker_start = ' marker-start="url(#arrow)"' if edge.get("bidirectional") else ""
        parts.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="#475569" stroke-width="2" marker-end="url(#arrow)"{marker_start}/>'
        )
        if edge.get("label"):
            parts.append(
                f'<text x="{(x1 + x2) / 2:.1f}" y="{(y1 + y2) / 2 - 8:.1f}" text-anchor="middle" font-family="Arial,sans-serif" font-size="12" fill="#334155">{escape(str(edge["label"]))}</text>'
            )
    for node in nodes:
        x, y, node_width, node_height = node["x"], node["y"], node["width"], node["height"]
        color = str(node.get("color") or "#e0e7ff")
        node_type = str(node.get("type") or "process")
        if node_type == "decision" or node.get("shape") == "diamond":
            points = (
                f"{x + node_width / 2:.1f},{y:.1f} "
                f"{x + node_width:.1f},{y + node_height / 2:.1f} "
                f"{x + node_width / 2:.1f},{y + node_height:.1f} "
                f"{x:.1f},{y + node_height / 2:.1f}"
            )
            parts.append(f'<polygon points="{points}" fill="{escape(color)}" stroke="#64748b" stroke-width="2"/>')
        elif node_type in {"start", "end"} or node.get("shape") == "ellipse":
            parts.append(
                f'<ellipse cx="{x + node_width / 2:.1f}" cy="{y + node_height / 2:.1f}" rx="{node_width / 2:.1f}" ry="{node_height / 2:.1f}" fill="{escape(color)}" stroke="#64748b" stroke-width="2"/>'
            )
        else:
            parts.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{node_width:.1f}" height="{node_height:.1f}" rx="12" fill="{escape(color)}" stroke="#64748b" stroke-width="2"/>'
            )
        lines = textwrap.wrap(str(node.get("label") or "Untitled"), width=max(12, int(node_width / 9)))[:4]
        first_y = y + node_height / 2 - ((len(lines) - 1) * 8)
        for line_index, line in enumerate(lines):
            parts.append(
                f'<text x="{x + node_width / 2:.1f}" y="{first_y + line_index * 17:.1f}" text-anchor="middle" font-family="Arial,sans-serif" font-size="13" font-weight="600" fill="#172033">{escape(line)}</text>'
            )
    parts.append("</svg>")
    return "".join(parts).encode("utf-8")


def row_dict(row: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: getattr(row, field) for field in fields}


async def evidence_package(session, project: Project) -> bytes:
    revisions = list(await session.scalars(
        select(ProjectRevision).where(ProjectRevision.project_id == project.id).order_by(ProjectRevision.version)
    ))
    approvals = list(await session.scalars(
        select(ProjectApproval).where(ProjectApproval.project_id == project.id).order_by(ProjectApproval.requested_at)
    ))
    audit_events = list(await session.scalars(
        select(AuditEvent).where(AuditEvent.project_id == project.id).order_by(AuditEvent.created_at)
    ))
    access = list(await session.scalars(
        select(ProjectCollaborator).where(ProjectCollaborator.project_id == project.id)
    ))
    deliverables = list(await session.scalars(
        select(ProjectDeliverable).where(ProjectDeliverable.project_id == project.id).order_by(ProjectDeliverable.created_at)
    ))
    tasks = list(await session.scalars(
        select(ProjectTask).where(ProjectTask.project_id == project.id).order_by(ProjectTask.created_at)
    ))
    notes = list(await session.scalars(
        select(ProjectNote).where(ProjectNote.project_id == project.id).order_by(ProjectNote.created_at)
    ))
    attachments = list(await session.scalars(
        select(ProjectAttachment).where(
            ProjectAttachment.project_id == project.id,
            ProjectAttachment.upload_status == "complete",
            ProjectAttachment.scan_status == "clean",
        ).order_by(ProjectAttachment.created_at)
    ))
    process_imports = list(await session.scalars(
        select(ProcessEventImport).where(ProcessEventImport.project_id == project.id).order_by(ProcessEventImport.created_at)
    ))
    process_insights = list(await session.scalars(
        select(ProcessInsight).where(ProcessInsight.project_id == project.id).order_by(ProcessInsight.detected_at)
    ))
    user_ids = {
        value
        for value in [
            project.owner_id,
            *[row.user_id for row in access],
            *[row.created_by_id for row in revisions],
            *[row.requested_by_id for row in approvals],
            *[row.reviewer_id for row in approvals],
            *[row.actor_id for row in audit_events],
            *[row.owner_id for row in deliverables],
            *[row.assignee_id for row in tasks],
            *[row.author_id for row in notes],
            *[row.uploaded_by_id for row in attachments],
            *[row.imported_by_id for row in process_imports],
            *[row.resolved_by_id for row in process_insights],
        ]
        if value
    }
    users = list(await session.scalars(select(User).where(User.id.in_(user_ids)))) if user_ids else []
    files: dict[str, bytes] = {
        "flowchart.json": json_bytes(project_export_payload(project)),
        "revisions.json": json_bytes([row_dict(row, (
            "id", "version", "title", "description", "status", "source_text", "graph",
            "change_summary", "created_by_id", "created_at",
        )) for row in revisions]),
        "approvals.json": json_bytes([row_dict(row, (
            "id", "revision_id", "requested_by_id", "reviewer_id", "status", "request_note",
            "decision_note", "requested_at", "decided_at",
        )) for row in approvals]),
        "audit-events.json": json_bytes([row_dict(row, (
            "id", "actor_id", "action", "target_type", "target_id", "details", "created_at",
        )) for row in audit_events]),
        "access.json": json_bytes([row_dict(row, ("user_id", "access_role", "added_at")) for row in access]),
        "users.json": json_bytes([row_dict(row, ("id", "display_name", "email", "role", "created_at")) for row in users]),
        "deliverables.json": json_bytes([row_dict(row, (
            "id", "creator_id", "owner_id", "title", "description", "status", "target_date",
            "node_id", "created_at", "updated_at",
        )) for row in deliverables]),
        "tasks.json": json_bytes([row_dict(row, (
            "id", "creator_id", "assignee_id", "deliverable_id", "node_id", "title", "details",
            "status", "priority", "due_date", "created_at", "updated_at",
        )) for row in tasks]),
        "notes.json": json_bytes([row_dict(row, (
            "id", "author_id", "body", "node_id", "resolved", "resolved_at", "created_at",
        )) for row in notes]),
        "attachments-manifest.json": json_bytes([row_dict(row, (
            "id", "node_id", "filename", "content_type", "size_bytes", "uploaded_by_id",
            "scan_status", "uploaded_at", "created_at",
        )) for row in attachments]),
        "process-event-imports.json": json_bytes([row_dict(row, (
            "id", "imported_by_id", "filename", "event_count", "case_count",
            "activity_node_map", "created_at",
        )) for row in process_imports]),
        "process-insights.json": json_bytes([row_dict(row, (
            "id", "import_id", "kind", "severity", "title", "description", "node_id",
            "status", "evidence", "detected_at", "resolved_at", "resolved_by_id",
        )) for row in process_insights]),
    }
    manifest = {
        "schema_version": 1,
        "package_kind": "flowforge_evidence_package",
        "project_id": project.id,
        "project_title": project.title,
        "generated_at": datetime.now(timezone.utc),
        "note": "Attachment binaries are not embedded; attachments-manifest.json lists clean evidence objects.",
        "files": {
            name: {"size_bytes": len(content), "sha256": sha256(content).hexdigest()}
            for name, content in files.items()
        },
    }
    files["manifest.json"] = json_bytes(manifest)
    files["README.md"] = (
        f"# Evidence package: {project.title}\n\n"
        "This package records the controlled FlowForge process, revision history, approvals, "
        "audit events, access, delivery plan, process insights, and clean attachment metadata. "
        "Use manifest.json to verify file hashes.\n"
    ).encode("utf-8")
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for filename, content in sorted(files.items()):
            archive.writestr(filename, content)
    return output.getvalue()


def csv_file(headers: list[str], rows: list[list[Any]]) -> bytes:
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


async def operational_package(session, project: Project) -> bytes:
    graph = project.graph or {}
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    tasks = list(await session.scalars(
        select(ProjectTask).where(ProjectTask.project_id == project.id).order_by(ProjectTask.created_at)
    ))
    title = project.title
    revision = project.revision or 0
    graph_content = json_bytes(project_export_payload(project))
    ordered_steps = "\n".join(
        f"{index}. **{node.get('label', 'Untitled')}**"
        + (f" — {node.get('description')}" if node.get("description") else "")
        + (f" _(Owner: {node.get('owner')})_" if node.get("owner") else "")
        for index, node in enumerate(nodes, start=1)
    ) or "No documented steps."
    sop = (
        f"# Standard operating procedure: {title}\n\n"
        f"Source project: `{project.id}` · revision `{revision}`\n\n"
        f"## Purpose\n\n{project.description or 'Follow the approved process consistently.'}\n\n"
        f"## Procedure\n\n{ordered_steps}\n\n"
        "## Exceptions\n\nEscalate undocumented paths to the process owner and record the outcome.\n"
    ).encode("utf-8")
    checklist = (
        f"# Execution checklist: {title}\n\n"
        + "\n".join(
            f"- [ ] {node.get('label', 'Untitled')}"
            + (f" — evidence: {node.get('evidence_requirement')}" if node.get("evidence_requirement") else "")
            for node in nodes
        )
        + "\n"
    ).encode("utf-8")
    training = (
        f"# Training guide: {title}\n\n"
        "## Learning objective\n\nUnderstand the approved path, owners, controls, evidence, and escalation points.\n\n"
        "## Guided walkthrough\n\n"
        + "\n".join(
            f"### {index}. {node.get('label', 'Untitled')}\n"
            f"{node.get('description') or 'Complete this step according to the approved process.'}\n"
            f"- Owner: {node.get('owner') or 'Unassigned'}\n"
            f"- System: {node.get('system') or 'Not specified'}\n"
            f"- Risk: {node.get('risk_level') or 'none'}\n"
            for index, node in enumerate(nodes, start=1)
        )
    ).encode("utf-8")
    tests = (
        f"# Process test cases: {title}\n\n"
        + "\n".join(
            f"## TC-{index:03d}: {node.get('label', 'Untitled')}\n"
            f"**Expected:** The step completes"
            + (f" within {node.get('sla_minutes')} minutes" if node.get("sla_minutes") else "")
            + (f" and produces {node.get('evidence_requirement')}" if node.get("evidence_requirement") else "")
            + ".\n"
            for index, node in enumerate(nodes, start=1)
        )
    ).encode("utf-8")
    controls = csv_file(
        [
            "node_id", "step", "control_id", "risk_level", "owner", "backup_owner",
            "system", "vendor", "policy", "evidence", "segregation_rule", "sla_minutes",
            "review_date", "data_classification", "required",
        ],
        [[
            node.get("id"), node.get("label"), node.get("control_id"), node.get("risk_level"),
            node.get("owner"), node.get("backup_owner"), node.get("system"), node.get("vendor"),
            node.get("policy_reference"), node.get("evidence_requirement"),
            node.get("segregation_rule"), node.get("sla_minutes"), node.get("review_date"),
            node.get("data_classification"), bool(node.get("required")),
        ] for node in nodes],
    )
    raci = csv_file(
        ["step", "responsible", "accountable", "consulted", "informed"],
        [[
            node.get("label"), node.get("owner") or "Unassigned",
            node.get("backup_owner") or node.get("owner") or "Unassigned", "Process owner", "Collaborators",
        ] for node in nodes],
    )
    summary = (
        f"# Executive summary: {title}\n\n"
        f"- Approved process revision: {revision}\n"
        f"- Steps: {len(nodes)}\n"
        f"- Connections: {len(edges)}\n"
        f"- Controlled steps: {sum(1 for node in nodes if node.get('control_id'))}\n"
        f"- High/critical-risk steps: {sum(1 for node in nodes if node.get('risk_level') in {'high', 'critical'})}\n"
        f"- Open execution tasks: {sum(1 for task in tasks if task.status != 'done')}\n\n"
        f"{project.description or 'This package was generated from the governed process model.'}\n"
    ).encode("utf-8")
    files = {
        "source-flowchart.json": graph_content,
        "SOP.md": sop,
        "RACI.csv": raci,
        "execution-checklist.md": checklist,
        "training-guide.md": training,
        "controls.csv": controls,
        "test-cases.md": tests,
        "executive-summary.md": summary,
    }
    manifest = {
        "schema_version": 1,
        "package_kind": "flowforge_operational_package",
        "project_id": project.id,
        "source_document_revision": revision,
        "source_graph_sha256": sha256(graph_content).hexdigest(),
        "generated_at": datetime.now(timezone.utc),
        "staleness_rule": "This package is stale when the project document revision changes.",
        "files": {
            name: {"size_bytes": len(content), "sha256": sha256(content).hexdigest()}
            for name, content in files.items()
        },
    }
    files["manifest.json"] = json_bytes(manifest)
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for filename, content in sorted(files.items()):
            archive.writestr(filename, content)
    return output.getvalue()


async def build_project_artifact(
    job: BackgroundJob,
    storage: ObjectStorage,
    settings: Settings,
) -> dict[str, Any]:
    async with session_factory() as session:
        existing = await session.scalar(
            select(GeneratedArtifact).where(GeneratedArtifact.job_id == job.id)
        )
        if existing:
            return {"artifact_id": existing.id}
        project = await session.get(Project, str(job.payload.get("project_id") or ""))
        if not project or project.entity_id != job.entity_id:
            raise ValueError("Project for generated artifact was not found")
        kind = str(job.payload.get("artifact_kind") or "export")
        format_name = str(job.payload.get("format") or "json")
        if kind == "evidence_package":
            content = await evidence_package(session, project)
            extension = "zip"
            content_type = "application/zip"
        elif kind == "operational_package":
            content = await operational_package(session, project)
            extension = "zip"
            content_type = "application/zip"
        elif format_name == "svg":
            content = graph_svg(project)
            extension = "svg"
            content_type = "image/svg+xml"
        elif format_name == "json":
            content = json_bytes(project_export_payload(project))
            extension = "json"
            content_type = "application/json"
        else:
            raise ValueError("Unsupported artifact format")
        if len(content) > settings.max_artifact_bytes:
            raise ValueError("Generated artifact exceeds the configured size limit")
        suffix = {
            "evidence_package": "evidence",
            "operational_package": "operations",
        }.get(kind, "flowchart")
        filename = f"{safe_slug(project.title)}-{suffix}.{extension}"
        storage_key = (
            f"{job.entity_id}/{project.id}/generated/{job.id}/clean/{filename}"
        )
        await ensure_artifact_capacity(session, job.entity_id, len(content))
        metadata = await storage.put(storage_key, content, content_type)
        artifact = GeneratedArtifact(
            entity_id=job.entity_id,
            project_id=project.id,
            job_id=job.id,
            created_by_id=job.created_by_id,
            kind=kind,
            format=extension,
            filename=filename,
            content_type=content_type,
            size_bytes=metadata.size_bytes,
            storage_key=storage_key,
            expires_at=datetime.now(timezone.utc) + timedelta(days=settings.artifact_retention_days),
        )
        session.add(artifact)
        await session.commit()
        await session.refresh(artifact)
        return {"artifact_id": artifact.id}


async def delete_project_objects(session, project_id: str, storage: ObjectStorage) -> None:
    artifacts = list(await session.scalars(
        select(GeneratedArtifact).where(GeneratedArtifact.project_id == project_id)
    ))
    attachments = list(await session.scalars(
        select(ProjectAttachment).where(
            ProjectAttachment.project_id == project_id,
            ProjectAttachment.storage_key.is_not(None),
        )
    ))
    for record in [*artifacts, *attachments]:
        if record.storage_key:
            await storage.delete(record.storage_key)
