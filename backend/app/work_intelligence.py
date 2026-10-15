"""Permission-aware, deterministic work intelligence.

This module intentionally does not require a model. It turns existing workspace
facts into explainable recommendations and rechecks the current user's access
before exposing any source object.
"""
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import get_current_user
from .database import (
    CalendarEvent,
    CalendarEventAttendee,
    Entity,
    KnowledgeDocument,
    Notification,
    OrganizationUnitMember,
    Project,
    ProjectCollaborator,
    ProjectGroupAccess,
    ProjectRisk,
    User,
    WorkItem,
    WorkItemLink,
    get_session,
)
from .knowledge import require_document
from .policy_engine import (
    PolicyContext,
    evaluate_policy,
    load_policy_snapshot,
    require_entitlement,
)
from .work_management import work_workflow


router = APIRouter(prefix="/intelligence", tags=["work intelligence"])
PRIORITY_WEIGHT = {"highest": 5, "high": 4, "medium": 3, "low": 2, "lowest": 1}
SEVERITY_ORDER = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(timezone.utc)


def iso(value: datetime | None) -> str | None:
    return utc(value).isoformat() if value else None


def user_today(user: User, now: datetime) -> date:
    try:
        return utc(now).astimezone(ZoneInfo(user.timezone or "UTC")).date()
    except ZoneInfoNotFoundError:
        return now.date()


def source(
    object_type: str,
    object_id: str,
    label: str,
    url: str,
    observed_at: datetime | None,
) -> dict[str, Any]:
    return {
        "type": object_type,
        "id": object_id,
        "label": label,
        "url": url,
        "observed_at": iso(observed_at),
    }


def recommendation(
    *,
    kind: str,
    source_item: dict[str, Any],
    severity: str,
    title: str,
    explanation: str,
    confidence: float,
    action_label: str,
    action_url: str,
    now: datetime,
    evidence: list[str],
) -> dict[str, Any]:
    observed_at = source_item.get("observed_at")
    observed = datetime.fromisoformat(observed_at) if observed_at else now
    age_hours = max(0, round((now - utc(observed)).total_seconds() / 3600, 1))
    return {
        "id": f"{kind}:{source_item['type']}:{source_item['id']}",
        "kind": kind,
        "severity": severity,
        "title": title,
        "explanation": explanation,
        "confidence": confidence,
        "freshness": {
            "observed_at": observed_at,
            "age_hours": age_hours,
            "state": "fresh" if age_hours <= 24 else "recent" if age_hours <= 168 else "stale",
        },
        "permission_scope": {
            "audience": "current_user",
            "authorization": "evaluated_at_request_time",
            "source_count": 1,
        },
        "sources": [source_item],
        "evidence": evidence,
        "proposed_action": {
            "label": action_label,
            "url": action_url,
            "mutation": False,
            "requires_review": True,
        },
    }


def project_access_filter(user: User):
    base = Project.entity_id == user.entity_id
    if user.role == "admin":
        return base
    collaborator_ids = select(ProjectCollaborator.project_id).where(
        ProjectCollaborator.user_id == user.id
    )
    group_ids = select(ProjectGroupAccess.project_id).join(
        OrganizationUnitMember,
        OrganizationUnitMember.unit_id == ProjectGroupAccess.unit_id,
    ).where(OrganizationUnitMember.user_id == user.id)
    explicit = or_(
        Project.owner_id == user.id,
        Project.id.in_(collaborator_ids),
        Project.id.in_(group_ids),
    )
    return base & (explicit if user.role == "guest" else or_(Project.visibility == "workspace", explicit))


@router.get("/briefing")
async def work_intelligence_briefing(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await require_entitlement(session, user.entity_id, "work_intelligence")
    now = datetime.now(timezone.utc)
    today = user_today(user, now)
    snapshot = await load_policy_snapshot(session, user)
    entity = await session.get(Entity, user.entity_id)
    workflow = work_workflow(entity)
    done_statuses = {
        column["id"] for column in workflow["columns"] if column.get("category") == "done"
    }

    candidate_projects = list(await session.scalars(
        select(Project).where(project_access_filter(user)).order_by(Project.updated_at.desc()).limit(250)
    ))
    projects: list[Project] = []
    for project in candidate_projects:
        decision = await evaluate_policy(session, user, PolicyContext(
            action="read", resource_type="project", resource_id=project.id,
            project_id=project.id,
            classification=str((project.profile or {}).get("classification") or "internal"),
            source_type="intelligence", preauthorized=True,
        ), snapshot)
        if decision.allowed:
            projects.append(project)
    project_ids = {project.id for project in projects}

    assigned_candidates = list(await session.scalars(select(WorkItem).where(
        WorkItem.entity_id == user.entity_id,
        WorkItem.assignee_id == user.id,
        WorkItem.archived.is_(False),
        WorkItem.status.not_in(done_statuses),
    ).order_by(WorkItem.due_date.asc(), WorkItem.rank.asc()).limit(300)))
    assigned: list[WorkItem] = []
    for item in assigned_candidates:
        if item.project_id and item.project_id not in project_ids:
            continue
        decision = await evaluate_policy(session, user, PolicyContext(
            action="read", resource_type="work_item", resource_id=item.id,
            project_id=item.project_id, source_type="intelligence", preauthorized=True,
        ), snapshot)
        if decision.allowed:
            assigned.append(item)

    project_work = list(await session.scalars(select(WorkItem).where(
        WorkItem.entity_id == user.entity_id,
        WorkItem.project_id.in_(project_ids) if project_ids else WorkItem.id == "",
        WorkItem.archived.is_(False),
    ).limit(3_000)))
    permitted_work: list[WorkItem] = []
    for item in project_work:
        decision = await evaluate_policy(session, user, PolicyContext(
            action="read", resource_type="work_item", resource_id=item.id,
            project_id=item.project_id, source_type="intelligence", preauthorized=True,
        ), snapshot)
        if decision.allowed:
            permitted_work.append(item)
    work_ids = {item.id for item in permitted_work}
    links = list(await session.scalars(select(WorkItemLink).where(
        WorkItemLink.entity_id == user.entity_id,
        WorkItemLink.source_id.in_(work_ids) if work_ids else WorkItemLink.id == "",
        WorkItemLink.target_id.in_(work_ids) if work_ids else WorkItemLink.id == "",
        WorkItemLink.link_type.in_(("blocks", "depends_on")),
    ).limit(3_000)))
    blocked_ids = {link.target_id for link in links}

    risks = list(await session.scalars(select(ProjectRisk).where(
        ProjectRisk.entity_id == user.entity_id,
        ProjectRisk.project_id.in_(project_ids) if project_ids else ProjectRisk.id == "",
        ProjectRisk.status.not_in(("closed", "accepted")),
    ).order_by(ProjectRisk.updated_at.desc()).limit(1_000)))
    permitted_risks: list[ProjectRisk] = []
    for risk in risks:
        decision = await evaluate_policy(session, user, PolicyContext(
            action="read", resource_type="risk", resource_id=risk.id,
            project_id=risk.project_id, source_type="intelligence", preauthorized=True,
        ), snapshot)
        if decision.allowed:
            permitted_risks.append(risk)

    attendee_event_ids = select(CalendarEventAttendee.event_id).where(
        CalendarEventAttendee.user_id == user.id
    )
    meetings = list(await session.scalars(select(CalendarEvent).where(
        CalendarEvent.entity_id == user.entity_id,
        or_(CalendarEvent.organizer_id == user.id, CalendarEvent.id.in_(attendee_event_ids)),
        CalendarEvent.status != "cancelled",
        CalendarEvent.starts_at >= now - timedelta(days=14),
        CalendarEvent.starts_at <= now + timedelta(days=2),
    ).order_by(CalendarEvent.starts_at.asc()).limit(100)))
    permitted_meetings: list[CalendarEvent] = []
    for meeting in meetings:
        decision = await evaluate_policy(session, user, PolicyContext(
            action="read", resource_type="meeting", resource_id=meeting.id,
            source_type="intelligence", preauthorized=True,
        ), snapshot)
        if decision.allowed:
            permitted_meetings.append(meeting)

    document_candidates = list(await session.scalars(select(KnowledgeDocument).where(
        KnowledgeDocument.entity_id == user.entity_id,
        KnowledgeDocument.status == "published",
        or_(
            KnowledgeDocument.review_due_at <= today,
            KnowledgeDocument.expires_at <= today,
            KnowledgeDocument.updated_at < now - timedelta(days=180),
        ),
    ).order_by(KnowledgeDocument.review_due_at.asc(), KnowledgeDocument.updated_at.asc()).limit(100)))
    documents: list[KnowledgeDocument] = []
    for document in document_candidates:
        try:
            await require_document(session, document.id, user)
        except HTTPException:
            continue
        documents.append(document)

    recommendations: list[dict[str, Any]] = []
    for item in assigned:
        item_source = source("work_item", item.id, f"{item.key} · {item.summary}", f"/work?item={item.id}", item.updated_at)
        days_overdue = (today - item.due_date).days if item.due_date and item.due_date < today else 0
        if days_overdue:
            recommendations.append(recommendation(
                kind="overdue_work", source_item=item_source,
                severity="critical" if days_overdue >= 7 else "high",
                title=f"{item.key} is {days_overdue} day{'s' if days_overdue != 1 else ''} overdue",
                explanation="This assigned item is unfinished and its due date has passed.",
                confidence=1.0, action_label="Review work item", action_url=f"/work?item={item.id}", now=now,
                evidence=[f"Due {item.due_date.isoformat()}", f"Current status: {item.status.replace('_', ' ')}"],
            ))
        elif item.id in blocked_ids:
            recommendations.append(recommendation(
                kind="blocked_work", source_item=item_source, severity="high",
                title=f"Resolve the dependency blocking {item.key}",
                explanation="A declared work dependency is preventing progress on an assigned item.",
                confidence=0.98, action_label="Inspect dependencies", action_url=f"/work?item={item.id}", now=now,
                evidence=["Active blocks/depends-on relationship", f"Current status: {item.status.replace('_', ' ')}"],
            ))
        elif item.due_date and item.due_date <= today + timedelta(days=2):
            recommendations.append(recommendation(
                kind="due_soon", source_item=item_source, severity="medium",
                title=f"{item.key} is due soon",
                explanation="This assigned item is due within two days and is not in a completed workflow state.",
                confidence=1.0, action_label="Open work item", action_url=f"/work?item={item.id}", now=now,
                evidence=[f"Due {item.due_date.isoformat()}", f"Priority: {item.priority}"],
            ))

    for risk in permitted_risks:
        score = risk.probability * risk.impact
        if score < 8:
            continue
        risk_source = source("risk", risk.id, risk.title, f"/operations?project={risk.project_id}&tab=overview", risk.updated_at)
        recommendations.append(recommendation(
            kind="project_risk", source_item=risk_source,
            severity="critical" if score >= 20 else "high" if score >= 15 else "medium",
            title=f"Mitigate: {risk.title}",
            explanation="An open project risk has material probability × impact exposure.",
            confidence=0.95, action_label="Review risk", action_url=f"/operations?project={risk.project_id}&tab=overview", now=now,
            evidence=[f"Exposure score: {score}/25", f"Status: {risk.status}", "Mitigation recorded" if risk.mitigation else "No mitigation recorded"],
        ))

    for meeting in permitted_meetings:
        meeting_source = source("meeting", meeting.id, meeting.title, f"/calendar?event={meeting.id}", meeting.updated_at)
        if utc(meeting.ends_at) < now and not (meeting.notes or meeting.transcript or meeting.action_items):
            recommendations.append(recommendation(
                kind="meeting_followup", source_item=meeting_source, severity="medium",
                title=f"Capture outcomes from {meeting.title}",
                explanation="The meeting ended without durable notes, transcript, or action items.",
                confidence=0.92, action_label="Add meeting outcomes", action_url=f"/calendar?event={meeting.id}", now=now,
                evidence=[f"Ended {iso(meeting.ends_at)}", "No notes or action items found"],
            ))
        elif utc(meeting.starts_at) > now and utc(meeting.starts_at) <= now + timedelta(hours=24) and not meeting.agenda:
            recommendations.append(recommendation(
                kind="meeting_preparation", source_item=meeting_source, severity="low",
                title=f"Prepare an agenda for {meeting.title}",
                explanation="This meeting starts within 24 hours and has no agenda.",
                confidence=0.9, action_label="Prepare meeting", action_url=f"/calendar?event={meeting.id}", now=now,
                evidence=[f"Starts {iso(meeting.starts_at)}", "Agenda is empty"],
            ))

    for document in documents:
        document_source = source("document", document.id, document.title, f"/knowledge?document={document.id}", document.updated_at)
        expired = bool(document.expires_at and document.expires_at <= today)
        review_due = bool(document.review_due_at and document.review_due_at <= today)
        recommendations.append(recommendation(
            kind="stale_knowledge", source_item=document_source,
            severity="high" if expired else "medium",
            title=f"{'Renew or archive' if expired else 'Review'}: {document.title}",
            explanation="Published knowledge is past its expiry or review threshold." if (expired or review_due) else "Published knowledge has not been updated for more than 180 days.",
            confidence=1.0 if (expired or review_due) else 0.85,
            action_label="Review document", action_url=f"/knowledge?document={document.id}", now=now,
            evidence=[
                f"Expired {document.expires_at.isoformat()}" if expired else f"Review due {document.review_due_at.isoformat()}" if review_due else f"Last updated {document.updated_at.date().isoformat()}",
                f"Classification: {document.classification}",
            ],
        ))

    project_health: list[dict[str, Any]] = []
    for project in projects:
        items = [item for item in permitted_work if item.project_id == project.id]
        open_items = [item for item in items if item.status not in done_statuses]
        overdue = [item for item in open_items if item.due_date and item.due_date < today]
        blocked = [item for item in open_items if item.id in blocked_ids]
        project_risks = [risk for risk in permitted_risks if risk.project_id == project.id]
        risk_exposure = sum(risk.probability * risk.impact for risk in project_risks)
        maximum_risk = max((risk.probability * risk.impact for risk in project_risks), default=0)
        completed = len(items) - len(open_items)
        progress = round(completed / len(items) * 100) if items else int((project.profile or {}).get("progress") or 0)
        open_count = max(1, len(open_items))
        score = round(max(0, min(100,
            100
            - min(35, len(overdue) / open_count * 35)
            - min(25, len(blocked) / open_count * 25)
            - min(25, maximum_risk)
        )))
        project_health.append({
            "project_id": project.id,
            "title": project.title,
            "health": "off_track" if score < 45 else "at_risk" if score < 70 else "on_track",
            "score": score,
            "progress": progress,
            "metrics": {
                "open_work": len(open_items),
                "overdue_work": len(overdue),
                "blocked_work": len(blocked),
                "risk_exposure": risk_exposure,
            },
            "evidence": [
                source("project", project.id, project.title, f"/projects/{project.id}", project.updated_at),
            ],
            "proposed_action": {
                "label": "Review project" if score < 75 else "Open project",
                "url": f"/operations?project={project.id}&tab=overview" if score < 75 else f"/projects/{project.id}",
                "mutation": False,
                "requires_review": True,
            },
        })

    recommendations.sort(key=lambda item: (
        -SEVERITY_ORDER.get(item["severity"], 0),
        -item["confidence"],
        item["title"],
    ))
    project_health.sort(key=lambda item: (item["score"], item["title"]))
    unread_count = int(await session.scalar(select(func.count(Notification.id)).where(
        Notification.entity_id == user.entity_id,
        Notification.user_id == user.id,
        Notification.read_at.is_(None),
        or_(Notification.snoozed_until.is_(None), Notification.snoozed_until <= now),
    )) or 0)
    today_meetings = sum(user_today(user, meeting.starts_at) == today for meeting in permitted_meetings)
    return {
        "generated_at": now.isoformat(),
        "engine": "deterministic",
        "model_required": False,
        "permission_scope": "current_user",
        "summary": {
            "attention_count": len(recommendations),
            "critical_count": sum(item["severity"] == "critical" for item in recommendations),
            "overdue_assigned": sum(bool(item.due_date and item.due_date < today) for item in assigned),
            "meetings_today": today_meetings,
            "unread_notifications": unread_count,
            "stale_documents": len(documents),
            "at_risk_projects": sum(item["health"] != "on_track" for item in project_health),
        },
        "recommendations": recommendations[:50],
        "project_health": project_health[:50],
        "coverage": {
            "projects": len(projects),
            "assigned_work": len(assigned),
            "project_work": len(permitted_work),
            "risks": len(permitted_risks),
            "meetings": len(permitted_meetings),
            "documents": len(documents),
            "policy_rules_evaluated": len(snapshot.rules),
        },
    }
