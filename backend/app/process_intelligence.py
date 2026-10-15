from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import get_current_user
from .database import (
    ProcessEvent,
    ProcessEventImport,
    ProcessInsight,
    Project,
    User,
    get_session,
)
from .governance import can_edit_project, project_access_role, record_audit_event
from .project_routes import entity_project
from .schemas import (
    ProcessAnalyticsResponse,
    ProcessEdgeMetric,
    ProcessEventImportRequest,
    ProcessEventImportResponse,
    ProcessImpactProject,
    ProcessImpactResponse,
    ProcessInsightResponse,
    ProcessNodeMetric,
)


router = APIRouter(tags=["process intelligence"])
FAILURE_STATUSES = {"failed", "failure", "error", "rejected", "cancelled", "canceled"}
DEPENDENCY_FIELDS = {
    "system": "system",
    "vendor": "vendor",
    "control_id": "control",
    "policy_reference": "policy",
    "owner": "owner",
    "backup_owner": "owner",
    "data_classification": "data_classification",
}


def as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def normalized_label(value: str) -> str:
    return "".join(character.lower() for character in value if character.isalnum())


def serialize_import(
    record: ProcessEventImport,
    *,
    mapped_event_count: int = 0,
    unmapped_activities: list[str] | None = None,
) -> ProcessEventImportResponse:
    return ProcessEventImportResponse(
        id=record.id,
        filename=record.filename,
        event_count=record.event_count,
        case_count=record.case_count,
        mapped_event_count=mapped_event_count,
        unmapped_activities=unmapped_activities or [],
        created_at=as_utc(record.created_at),
    )


def serialize_insight(insight: ProcessInsight) -> ProcessInsightResponse:
    return ProcessInsightResponse(
        id=insight.id,
        kind=insight.kind,
        severity=insight.severity,
        title=insight.title,
        description=insight.description,
        node_id=insight.node_id,
        status=insight.status,
        evidence=insight.evidence or {},
        detected_at=as_utc(insight.detected_at),
        resolved_at=as_utc(insight.resolved_at) if insight.resolved_at else None,
    )


def analytics_from_events(
    graph: dict[str, Any],
    events: list[ProcessEvent],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    nodes = {str(node["id"]): node for node in graph.get("nodes", [])}
    expected_edges = {
        (str(edge.get("source")), str(edge.get("target")))
        for edge in graph.get("edges", [])
    }
    cases: dict[str, list[ProcessEvent]] = defaultdict(list)
    for event in events:
        cases[event.case_id].append(event)
    for case_events in cases.values():
        case_events.sort(key=lambda item: as_utc(item.occurred_at))

    node_values: dict[str, dict[str, float]] = defaultdict(lambda: {
        "count": 0,
        "wait_seconds": 0,
        "wait_samples": 0,
        "failure_count": 0,
        "sla_breach_count": 0,
        "total_cost": 0,
    })
    edge_counts: dict[tuple[str, str], int] = defaultdict(int)
    unexpected_counts: dict[tuple[str, str], int] = defaultdict(int)
    total_transitions = 0
    conforming_transitions = 0
    total_cycle_seconds = 0.0
    required_nodes = {
        node_id for node_id, node in nodes.items() if node.get("required")
    }
    missing_required: dict[str, int] = defaultdict(int)

    for case_events in cases.values():
        if len(case_events) > 1:
            total_cycle_seconds += max(
                0.0,
                (as_utc(case_events[-1].occurred_at) - as_utc(case_events[0].occurred_at)).total_seconds(),
            )
        visited = {event.node_id for event in case_events if event.node_id}
        for node_id in required_nodes - visited:
            missing_required[node_id] += 1
        mapped = [event for event in case_events if event.node_id]
        for index, event in enumerate(case_events):
            if not event.node_id or event.node_id not in nodes:
                continue
            metric = node_values[event.node_id]
            metric["count"] += 1
            metric["total_cost"] += float(event.cost or 0)
            if (event.status or "").strip().lower() in FAILURE_STATUSES:
                metric["failure_count"] += 1
            if index + 1 < len(case_events):
                wait_seconds = max(
                    0.0,
                    (as_utc(case_events[index + 1].occurred_at) - as_utc(event.occurred_at)).total_seconds(),
                )
                metric["wait_seconds"] += wait_seconds
                metric["wait_samples"] += 1
                sla_minutes = nodes[event.node_id].get("sla_minutes")
                if sla_minutes and wait_seconds > float(sla_minutes) * 60:
                    metric["sla_breach_count"] += 1
        for first, second in zip(mapped, mapped[1:]):
            transition = (str(first.node_id), str(second.node_id))
            edge_counts[transition] += 1
            total_transitions += 1
            if transition in expected_edges:
                conforming_transitions += 1
            else:
                unexpected_counts[transition] += 1

    node_metrics = [
        ProcessNodeMetric(
            node_id=node_id,
            count=int(values["count"]),
            average_wait_seconds=round(
                values["wait_seconds"] / max(1, values["wait_samples"]), 2
            ),
            failure_count=int(values["failure_count"]),
            sla_breach_count=int(values["sla_breach_count"]),
            total_cost=round(values["total_cost"], 2),
        )
        for node_id, values in sorted(node_values.items())
    ]
    edge_metrics = [
        ProcessEdgeMetric(
            source=source,
            target=target,
            count=count,
            unexpected=(source, target) not in expected_edges,
        )
        for (source, target), count in sorted(edge_counts.items())
    ]
    insight_specs: list[dict[str, Any]] = []
    for (source, target), count in sorted(unexpected_counts.items(), key=lambda item: -item[1]):
        insight_specs.append({
            "kind": "unexpected_transition",
            "severity": "high",
            "title": "Unexpected process path detected",
            "description": (
                f"{count} case{'s' if count != 1 else ''} moved from "
                f"{nodes.get(source, {}).get('label', source)} to "
                f"{nodes.get(target, {}).get('label', target)} without a documented connection."
            ),
            "node_id": target,
            "evidence": {"source": source, "target": target, "case_count": count},
        })
    for node_id, count in sorted(missing_required.items(), key=lambda item: -item[1]):
        insight_specs.append({
            "kind": "required_step_skipped",
            "severity": "critical" if nodes[node_id].get("control_id") else "high",
            "title": "Required step was skipped",
            "description": (
                f"{nodes[node_id].get('label', node_id)} was missing from "
                f"{count} case{'s' if count != 1 else ''}."
            ),
            "node_id": node_id,
            "evidence": {"missing_case_count": count, "control_id": nodes[node_id].get("control_id")},
        })
    for metric in node_metrics:
        if metric.sla_breach_count:
            insight_specs.append({
                "kind": "sla_breach",
                "severity": "high",
                "title": "Step SLA is being missed",
                "description": (
                    f"{nodes[metric.node_id].get('label', metric.node_id)} exceeded its SLA in "
                    f"{metric.sla_breach_count} execution{'s' if metric.sla_breach_count != 1 else ''}."
                ),
                "node_id": metric.node_id,
                "evidence": {
                    "breach_count": metric.sla_breach_count,
                    "average_wait_seconds": metric.average_wait_seconds,
                    "sla_minutes": nodes[metric.node_id].get("sla_minutes"),
                },
            })
        if metric.failure_count:
            insight_specs.append({
                "kind": "execution_failure",
                "severity": "medium",
                "title": "Execution failures detected",
                "description": (
                    f"{nodes[metric.node_id].get('label', metric.node_id)} recorded "
                    f"{metric.failure_count} failed execution{'s' if metric.failure_count != 1 else ''}."
                ),
                "node_id": metric.node_id,
                "evidence": {"failure_count": metric.failure_count},
            })
    result = {
        "event_count": len(events),
        "case_count": len(cases),
        "mapped_event_count": sum(1 for event in events if event.node_id),
        "conformance_rate": round(
            (conforming_transitions / total_transitions * 100) if total_transitions else 100.0,
            1,
        ),
        "average_case_cycle_seconds": round(
            total_cycle_seconds / max(1, len(cases)), 2
        ),
        "node_metrics": node_metrics,
        "edge_metrics": edge_metrics,
    }
    return result, insight_specs


@router.post(
    "/projects/{project_id}/process-events/imports",
    response_model=ProcessEventImportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_process_events(
    project_id: str,
    payload: ProcessEventImportRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ProcessEventImportResponse:
    project = await entity_project(project_id, user, session)
    access = await project_access_role(session, project, user)
    if not can_edit_project(access):
        raise HTTPException(status_code=403, detail="Project editing access is required")
    nodes = {str(node["id"]): node for node in (project.graph or {}).get("nodes", [])}
    unknown_node_ids = set(payload.activity_node_map.values()) - set(nodes)
    if unknown_node_ids:
        raise HTTPException(status_code=422, detail="Activity mapping contains unknown flowchart steps")
    labels = {
        normalized_label(str(node.get("label") or "")): node_id
        for node_id, node in nodes.items()
    }
    mapping = dict(payload.activity_node_map)
    for event in payload.events:
        mapping.setdefault(event.activity, labels.get(normalized_label(event.activity)))
    mapping = {activity: node_id for activity, node_id in mapping.items() if node_id}
    record = ProcessEventImport(
        entity_id=user.entity_id,
        project_id=project.id,
        imported_by_id=user.id,
        filename=payload.filename,
        event_count=len(payload.events),
        case_count=len({event.case_id for event in payload.events}),
        activity_node_map=mapping,
    )
    session.add(record)
    await session.flush()
    imported_events = [
        ProcessEvent(
            entity_id=user.entity_id,
            project_id=project.id,
            import_id=record.id,
            case_id=event.case_id,
            activity=event.activity,
            node_id=mapping.get(event.activity),
            occurred_at=as_utc(event.occurred_at),
            status=event.status,
            owner=event.owner,
            cost=event.cost,
            attributes=event.attributes,
        )
        for event in payload.events
    ]
    session.add_all(imported_events)
    _, insight_specs = analytics_from_events(project.graph or {}, imported_events)
    for spec in insight_specs:
        session.add(ProcessInsight(
            entity_id=user.entity_id,
            project_id=project.id,
            import_id=record.id,
            **spec,
        ))
    unmapped = sorted({event.activity for event in payload.events if event.activity not in mapping})
    if unmapped:
        session.add(ProcessInsight(
            entity_id=user.entity_id,
            project_id=project.id,
            import_id=record.id,
            kind="unmapped_activity",
            severity="medium",
            title="Unmapped activities need review",
            description=(
                f"{len(unmapped)} imported activit{'y' if len(unmapped) == 1 else 'ies'} "
                "could not be matched to a documented step."
            ),
            evidence={"activities": unmapped[:100]},
        ))
    record_audit_event(
        session,
        entity_id=user.entity_id,
        actor_id=user.id,
        action="process.events_imported",
        project_id=project.id,
        target_type="process_event_import",
        target_id=record.id,
        details={
            "filename": record.filename,
            "event_count": record.event_count,
            "case_count": record.case_count,
            "unmapped_activity_count": len(unmapped),
        },
    )
    await session.commit()
    await session.refresh(record)
    return serialize_import(
        record,
        mapped_event_count=sum(1 for event in imported_events if event.node_id),
        unmapped_activities=unmapped,
    )


@router.get(
    "/projects/{project_id}/process-analytics",
    response_model=ProcessAnalyticsResponse,
)
async def process_analytics(
    project_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ProcessAnalyticsResponse:
    project = await entity_project(project_id, user, session)
    events = list(await session.scalars(
        select(ProcessEvent)
        .where(ProcessEvent.project_id == project.id, ProcessEvent.entity_id == user.entity_id)
        .order_by(ProcessEvent.case_id, ProcessEvent.occurred_at)
        .limit(100_000)
    ))
    values, _ = analytics_from_events(project.graph or {}, events)
    insights = list(await session.scalars(
        select(ProcessInsight)
        .where(ProcessInsight.project_id == project.id, ProcessInsight.entity_id == user.entity_id)
        .order_by(ProcessInsight.detected_at.desc())
        .limit(200)
    ))
    imports = list(await session.scalars(
        select(ProcessEventImport)
        .where(ProcessEventImport.project_id == project.id)
        .order_by(ProcessEventImport.created_at.desc())
        .limit(30)
    ))
    return ProcessAnalyticsResponse(
        **values,
        insights=[serialize_insight(insight) for insight in insights],
        imports=[serialize_import(record) for record in imports],
    )


@router.post(
    "/projects/{project_id}/process-insights/{insight_id}/resolve",
    response_model=ProcessInsightResponse,
)
async def resolve_process_insight(
    project_id: str,
    insight_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ProcessInsightResponse:
    project = await entity_project(project_id, user, session)
    if not can_edit_project(await project_access_role(session, project, user)):
        raise HTTPException(status_code=403, detail="Project editing access is required")
    insight = await session.get(ProcessInsight, insight_id)
    if not insight or insight.project_id != project.id or insight.entity_id != user.entity_id:
        raise HTTPException(status_code=404, detail="Process insight not found")
    insight.status = "resolved"
    insight.resolved_at = datetime.now(timezone.utc)
    insight.resolved_by_id = user.id
    record_audit_event(
        session,
        entity_id=user.entity_id,
        actor_id=user.id,
        action="process.insight_resolved",
        project_id=project.id,
        target_type="process_insight",
        target_id=insight.id,
        details={"kind": insight.kind},
    )
    await session.commit()
    await session.refresh(insight)
    return serialize_insight(insight)


@router.delete(
    "/projects/{project_id}/process-events/imports/{import_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_process_event_import(
    project_id: str,
    import_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    project = await entity_project(project_id, user, session)
    if not can_edit_project(await project_access_role(session, project, user)):
        raise HTTPException(status_code=403, detail="Project editing access is required")
    record = await session.get(ProcessEventImport, import_id)
    if not record or record.project_id != project.id or record.entity_id != user.entity_id:
        raise HTTPException(status_code=404, detail="Process event import not found")
    await session.delete(record)
    record_audit_event(
        session,
        entity_id=user.entity_id,
        actor_id=user.id,
        action="process.event_import_deleted",
        project_id=project.id,
        target_type="process_event_import",
        target_id=import_id,
        details={"filename": record.filename},
    )
    await session.commit()


@router.get("/process-impact", response_model=ProcessImpactResponse)
async def process_impact(
    query: str = Query(default="", max_length=160),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ProcessImpactResponse:
    projects = list(await session.scalars(
        select(Project)
        .where(Project.entity_id == user.entity_id)
        .order_by(Project.updated_at.desc())
        .limit(1_000)
    ))
    needle = query.strip().lower()
    matches: list[ProcessImpactProject] = []
    summary: dict[str, int] = defaultdict(int)
    for project in projects:
        if not await project_access_role(session, project, user):
            continue
        for node in (project.graph or {}).get("nodes", []):
            for field, dependency_type in DEPENDENCY_FIELDS.items():
                value = str(node.get(field) or "").strip()
                if not value or (needle and needle not in value.lower()):
                    continue
                matches.append(ProcessImpactProject(
                    project_id=project.id,
                    project_title=project.title,
                    node_id=str(node.get("id")),
                    node_label=str(node.get("label") or node.get("id")),
                    dependency_type=dependency_type,
                    dependency_value=value,
                ))
                summary[dependency_type] += 1
                if len(matches) >= 250:
                    break
            if len(matches) >= 250:
                break
        if len(matches) >= 250:
            break
    return ProcessImpactResponse(
        query=query.strip(),
        matches=matches,
        dependency_summary=dict(sorted(summary.items())),
    )
