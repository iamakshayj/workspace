"""Seed a realistic, isolated enterprise playground for local demos and testing.

The script is intentionally idempotent. Re-running it refreshes the known demo
account passwords and reports the existing dataset instead of duplicating data.
It refuses to run when FLOWFORGE_ENVIRONMENT=production.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta, timezone
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import func, select

from backend.app.auth import hash_password
from backend.app.config import get_settings
from backend.app.database import (
    AgileRelease,
    AgileSprint,
    ApprovalDefinition,
    ApprovalInstance,
    AuditEvent,
    CalendarEvent,
    CalendarEventAttendee,
    CalendarEventExternalAttendee,
    CommunicationChannel,
    CommunicationChannelMember,
    CommunicationChannelMessage,
    DirectMessage,
    Entity,
    KnowledgeComment,
    KnowledgeDocument,
    KnowledgeDocumentAccess,
    KnowledgeDocumentLink,
    KnowledgeDocumentRevision,
    KnowledgeSpace,
    KnowledgeSpaceMember,
    NodePlanningBinding,
    Notification,
    NotificationPreference,
    ObjectRelationship,
    OrganizationUnit,
    OrganizationUnitMember,
    Project,
    ProjectCollaborator,
    ProjectDecision,
    ProjectDeliverable,
    ProjectGroupAccess,
    ProjectMessage,
    ProjectNote,
    ProjectRevision,
    ProjectRisk,
    ProjectTask,
    SavedWorkspaceView,
    User,
    WorkItem,
    WorkItemActivity,
    WorkItemComment,
    WorkItemLink,
    WorkspaceDashboard,
    WorkspaceFile,
    session_factory,
)


ENTITY_NAME = "Acme Enterprise Playground"
DEMO_PASSWORD = "WorkspaceDemo2026!"
SEED_VERSION = 1


def stable_id(kind: str, name: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"flowforge-demo:{SEED_VERSION}:{kind}:{name}"))


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=timezone.utc)


def graph_for(title: str, owner: str, accent: str) -> dict:
    labels = [
        ("start", "Request received", "start"),
        ("discover", "Discover requirements", "process"),
        ("review", "Review scope", "decision"),
        ("design", "Design solution", "process"),
        ("build", "Build and configure", "subprocess"),
        ("qa", "Quality verification", "process"),
        ("approve", "Business approval", "decision"),
        ("launch", "Release outcome", "end"),
    ]
    nodes = []
    for index, (node_id, label, node_type) in enumerate(labels):
        column = index if index < 3 else index - 1
        row = 1 if index in {3, 5} else 0
        nodes.append({
            "id": node_id,
            "label": label,
            "type": node_type,
            "owner": owner,
            "description": f"{label} for {title}.",
            "color": accent if node_type not in {"start", "end"} else ("#34A474" if node_type == "end" else "#4B84D8"),
            "shape": "diamond" if node_type == "decision" else "rounded",
            "x": column * 245,
            "y": row * 170,
            "width": 190,
            "height": 78,
            "risk_level": "medium" if node_id in {"review", "approve"} else "low",
            "data_classification": "confidential" if "SOC" in title or "ERP" in title else "internal",
        })
    edges = [
        {"source": "start", "target": "discover", "label": "", "is_loop": False, "bidirectional": False},
        {"source": "discover", "target": "review", "label": "ready", "is_loop": False, "bidirectional": False},
        {"source": "review", "target": "design", "label": "approved", "is_loop": False, "bidirectional": False},
        {"source": "review", "target": "discover", "label": "revise", "is_loop": True, "bidirectional": False},
        {"source": "design", "target": "build", "label": "", "is_loop": False, "bidirectional": True},
        {"source": "build", "target": "qa", "label": "candidate", "is_loop": False, "bidirectional": False},
        {"source": "qa", "target": "approve", "label": "verified", "is_loop": False, "bidirectional": False},
        {"source": "approve", "target": "launch", "label": "go", "is_loop": False, "bidirectional": False},
        {"source": "approve", "target": "build", "label": "changes", "is_loop": True, "bidirectional": False},
    ]
    return {"title": title, "nodes": nodes, "edges": edges, "questions": [], "warnings": []}


USERS = [
    ("executive", "avery.admin@acme.demo", "Avery Morgan", "admin", "Chief Operating Officer", "America/Chicago", ["Strategy", "Governance", "Portfolio"], 35),
    ("platform", "jordan.platform@acme.demo", "Jordan Lee", "admin", "Workspace Platform Admin", "America/Los_Angeles", ["Security", "Automation", "Data"], 40),
    ("program", "priya.program@acme.demo", "Priya Shah", "basic", "Senior Program Manager", "America/New_York", ["Program delivery", "Risk", "Facilitation"], 40),
    ("product", "marcus.product@acme.demo", "Marcus Chen", "basic", "Product Manager", "America/Los_Angeles", ["Discovery", "Roadmaps", "Analytics"], 40),
    ("engineering", "elena.engineering@acme.demo", "Elena Garcia", "basic", "Engineering Manager", "Europe/London", ["Architecture", "Capacity", "APIs"], 38),
    ("developer", "sam.developer@acme.demo", "Sam Wilson", "basic", "Senior Software Engineer", "America/Chicago", ["React", "Python", "PostgreSQL"], 40),
    ("qa", "nina.qa@acme.demo", "Nina Patel", "basic", "Quality Engineering Lead", "Asia/Kolkata", ["Automation", "Accessibility", "Performance"], 40),
    ("design", "leo.design@acme.demo", "Leo Martinez", "basic", "Product Designer", "America/New_York", ["Research", "Design systems", "Prototyping"], 36),
    ("analyst", "mia.analyst@acme.demo", "Mia Thompson", "basic", "Business Analyst", "America/Chicago", ["BPMN", "Requirements", "Reporting"], 40),
    ("operations", "omar.operations@acme.demo", "Omar Hassan", "basic", "Operations Manager", "Europe/Berlin", ["Process improvement", "SLA", "Vendors"], 40),
    ("sales", "sofia.sales@acme.demo", "Sofia Rossi", "basic", "Revenue Operations Manager", "America/New_York", ["CRM", "Forecasting", "Enablement"], 40),
    ("finance", "ethan.finance@acme.demo", "Ethan Brown", "basic", "Finance Business Partner", "America/Chicago", ["Budgeting", "Controls", "Procurement"], 32),
    ("people", "grace.people@acme.demo", "Grace Kim", "basic", "People Operations Partner", "America/Los_Angeles", ["Workforce planning", "Policy", "Hiring"], 40),
    ("support", "diego.support@acme.demo", "Diego Alvarez", "basic", "Customer Support Lead", "America/Denver", ["Customer support", "Knowledge", "Incident response"], 40),
    ("guest", "riley.auditor@acme.demo", "Riley Brooks", "guest", "External Compliance Auditor", "UTC", ["SOC 2", "Evidence review"], 20),
]


PROJECTS = [
    ("onboarding", "Customer Onboarding Redesign", "Deliver a faster, measurable onboarding journey across Sales, Success, and Support.", "Product", "Marcus Chen", "#5B6FEA", "on_track", 72),
    ("mobile", "Mobile App 2.0 Launch", "Launch the redesigned customer mobile experience with accessibility and reliability gates.", "Engineering", "Elena Garcia", "#8B5CF6", "at_risk", 58),
    ("soc2", "SOC 2 Type II Readiness", "Close control gaps, collect evidence, and prepare for the external audit window.", "Security", "Jordan Lee", "#D3546A", "at_risk", 64),
    ("revops", "Revenue Operations Automation", "Automate lead routing, approvals, forecasting, and renewal handoffs.", "Revenue", "Sofia Rossi", "#E89A37", "on_track", 81),
    ("erp", "ERP Finance Migration", "Move finance operations to a governed ERP with reconciled data and controls.", "Finance", "Ethan Brown", "#0E9F8A", "off_track", 43),
    ("support_ai", "Self-hosted Support Assistant", "Build a permission-aware internal assistant for agents without hosted AI APIs.", "Support", "Diego Alvarez", "#3B82F6", "on_track", 36),
    ("hiring", "2027 Workforce and Hiring Plan", "Align hiring priorities, skills gaps, capacity, and approved headcount.", "People", "Grace Kim", "#EC4899", "on_track", 49),
    ("stores", "Retail Store Rollout", "Coordinate site readiness, training, inventory, and opening milestones across regions.", "Operations", "Omar Hassan", "#F59E0B", "at_risk", 27),
]


async def dataset_counts(session, entity_id: str) -> dict[str, int]:
    models = {
        "users": User, "projects": Project, "work_items": WorkItem,
        "sprints": AgileSprint, "releases": AgileRelease, "risks": ProjectRisk,
        "meetings": CalendarEvent, "documents": KnowledgeDocument,
        "channels": CommunicationChannel, "notifications": Notification,
    }
    result = {}
    for label, model in models.items():
        result[label] = int(await session.scalar(select(func.count()).select_from(model).where(model.entity_id == entity_id)) or 0)
    return result


async def seed() -> None:
    settings = get_settings()
    if settings.environment.strip().lower() == "production":
        raise RuntimeError("Demo data seeding is disabled in production")

    today = date.today()
    now = datetime.now(timezone.utc)
    entity_id = stable_id("entity", ENTITY_NAME)

    async with session_factory() as session:
        entity = await session.scalar(select(Entity).where(Entity.name == ENTITY_NAME))
        if entity:
            for _, email, *_ in USERS:
                account = await session.scalar(select(User).where(User.email == email))
                if account:
                    account.password_hash = hash_password(DEMO_PASSWORD)
            for project in await session.scalars(select(Project).where(Project.entity_id == entity.id)):
                profile = dict(project.profile or {})
                if profile.get("template") == "enterprise":
                    profile["template"] = "general"
                profile["key"] = str(profile.get("key", "")).replace("_", "-")
                project.profile = profile
            project_ids = select(Project.id).where(Project.entity_id == entity.id)
            for revision in await session.scalars(select(ProjectRevision).where(ProjectRevision.project_id.in_(project_ids))):
                profile = dict(revision.profile or {})
                if profile.get("template") == "enterprise":
                    profile["template"] = "general"
                profile["key"] = str(profile.get("key", "")).replace("_", "-")
                revision.profile = profile
            await session.commit()
            print(f"{ENTITY_NAME} already exists; demo passwords refreshed.")
            print(await dataset_counts(session, entity.id))
            return

        entity = Entity(
            id=entity_id,
            name=ENTITY_NAME,
            max_users=500,
            max_projects=5000,
            max_monthly_generations=10000,
            max_pending_generations=100,
            governance_settings={
                "seed_version": SEED_VERSION,
                "retention_days": 2555,
                "legal_hold": False,
                "export_enabled": True,
                "demo_dataset": True,
            },
        )
        session.add(entity)

        user_by_key: dict[str, User] = {}
        for key, email, name, role, title, tz, skills, capacity in USERS:
            user = User(
                id=stable_id("user", key), email=email, display_name=name,
                password_hash=hash_password(DEMO_PASSWORD), entity_id=entity_id, role=role,
                job_title=title, timezone=tz, skills=skills, weekly_capacity_hours=capacity,
                profile={"bio": f"Demo {title} account", "location": tz.split("/")[-1].replace("_", " "),
                         "calendar": {"working_hours": {"weekdays": [1, 2, 3, 4, 5], "start": "09:00", "end": "17:00"}, "holidays": []}},
            )
            user_by_key[key] = user
            session.add(user)
        await session.flush()

        managers = {
            "platform": "executive", "program": "executive", "product": "program", "engineering": "program",
            "developer": "engineering", "qa": "engineering", "design": "product", "analyst": "program",
            "operations": "executive", "sales": "executive", "finance": "executive", "people": "executive",
            "support": "operations", "guest": "platform",
        }
        for child, manager in managers.items():
            user_by_key[child].manager_id = user_by_key[manager].id

        unit_specs = [
            ("company", "Acme Corporation", "company", None, "executive"),
            ("product_org", "Product & Technology", "business_unit", "company", "program"),
            ("engineering_team", "Platform Engineering", "team", "product_org", "engineering"),
            ("product_team", "Product Experience", "team", "product_org", "product"),
            ("quality_team", "Quality Engineering", "team", "product_org", "qa"),
            ("operations_org", "Business Operations", "business_unit", "company", "operations"),
            ("revenue_team", "Revenue Operations", "team", "operations_org", "sales"),
            ("finance_team", "Finance & Procurement", "department", "operations_org", "finance"),
            ("people_team", "People Operations", "department", "operations_org", "people"),
            ("support_team", "Customer Support", "team", "operations_org", "support"),
        ]
        unit_by_key: dict[str, OrganizationUnit] = {}
        for key, name, kind, parent_key, manager_key in unit_specs:
            unit = OrganizationUnit(
                id=stable_id("unit", key), entity_id=entity_id,
                parent_id=unit_by_key[parent_key].id if parent_key else None,
                manager_id=user_by_key[manager_key].id, name=name, unit_type=kind,
                description=f"Demo {kind.replace('_', ' ')} for enterprise testing.",
                timezone=user_by_key[manager_key].timezone, weekly_capacity_hours=200,
            )
            unit_by_key[key] = unit
            session.add(unit)
        await session.flush()

        memberships = {
            "company": ["executive", "platform", "program"],
            "engineering_team": ["engineering", "developer"],
            "product_team": ["product", "design", "analyst"],
            "quality_team": ["qa"],
            "operations_org": ["operations"],
            "revenue_team": ["sales"], "finance_team": ["finance"],
            "people_team": ["people"], "support_team": ["support"],
        }
        for unit_key, user_keys in memberships.items():
            for index, user_key in enumerate(user_keys):
                session.add(OrganizationUnitMember(
                    id=stable_id("membership", f"{unit_key}:{user_key}"), unit_id=unit_by_key[unit_key].id,
                    user_id=user_by_key[user_key].id,
                    membership_role="lead" if index == 0 else "member", allocation_percent=100,
                ))

        sprint_specs = [
            ("previous", "Sprint 24 · Foundation", "completed", today - timedelta(days=28), today - timedelta(days=15), 72),
            ("active", "Sprint 25 · Customer outcomes", "active", today - timedelta(days=7), today + timedelta(days=6), 84),
            ("next", "Sprint 26 · Reliability", "planned", today + timedelta(days=7), today + timedelta(days=20), 80),
            ("later", "Sprint 27 · Scale", "planned", today + timedelta(days=21), today + timedelta(days=34), 88),
        ]
        sprint_by_key: dict[str, AgileSprint] = {}
        for key, name, status, start, end, capacity in sprint_specs:
            sprint = AgileSprint(
                id=stable_id("sprint", key), entity_id=entity_id, created_by_id=user_by_key["program"].id,
                name=name, goal=f"Deliver measurable {key} outcomes across the portfolio.", status=status,
                start_date=start, end_date=end, capacity_points=capacity,
            )
            sprint_by_key[key] = sprint
            session.add(sprint)

        release_specs = [
            ("q3", "2026 Q3 Experience", "in_progress", today - timedelta(days=45), today + timedelta(days=20), "committed"),
            ("q4", "2026 Q4 Enterprise", "planned", today + timedelta(days=21), today + timedelta(days=100), "committed"),
            ("audit", "Audit Readiness Gate", "in_progress", today - timedelta(days=21), today + timedelta(days=35), "conservative"),
            ("pilot", "Regional Pilot", "planned", today + timedelta(days=30), today + timedelta(days=75), "optimistic"),
        ]
        release_by_key: dict[str, AgileRelease] = {}
        for key, name, status, start, target, scenario in release_specs:
            release = AgileRelease(
                id=stable_id("release", key), entity_id=entity_id, created_by_id=user_by_key["program"].id,
                name=name, description=f"Portfolio release for {name}.", status=status,
                start_date=start, target_date=target,
                baseline={"start_date": start.isoformat(), "target_date": (target - timedelta(days=7)).isoformat()},
                scenario=scenario,
            )
            release_by_key[key] = release
            session.add(release)
        await session.flush()

        project_owner_keys = ["product", "engineering", "platform", "sales", "finance", "support", "people", "operations"]
        project_team_keys = ["product_team", "engineering_team", "quality_team", "revenue_team", "finance_team", "support_team", "people_team", "operations_org"]
        project_by_key: dict[str, Project] = {}
        for index, (key, title, description, department, owner_name, accent, health, progress) in enumerate(PROJECTS):
            owner_key = project_owner_keys[index]
            graph = graph_for(title, owner_name, accent)
            project = Project(
                id=stable_id("project", key), entity_id=entity_id, owner_id=user_by_key[owner_key].id,
                title=title, description=description, status="active", visibility="restricted" if key in {"soc2", "erp", "hiring"} else "workspace",
                approval_status="approved" if progress > 70 else "in_review" if progress > 40 else "draft",
                profile={
                    "key": key.upper().replace("_", "-"), "department": department, "team": project_team_keys[index],
                    "program": "Enterprise Transformation", "priority": "high" if health != "on_track" else "medium",
                    "health": health, "progress": progress, "classification": "confidential" if key in {"soc2", "erp", "hiring"} else "internal",
                    "start_date": (today - timedelta(days=50 - index * 3)).isoformat(),
                    "target_date": (today + timedelta(days=30 + index * 12)).isoformat(),
                    "tags": [department.lower(), "demo", health], "template": "general",
                },
                settings={
                    "workflow": {"qa_required": True, "approval_required": key in {"soc2", "erp"}},
                    "fields": [{"id": "business_value", "label": "Business value", "type": "number"}, {"id": "customer_segment", "label": "Customer segment", "type": "text"}],
                    "notifications": {"risk_changes": True, "release_changes": True},
                    "integrations": {"webhook": "disabled", "calendar": "demo"},
                    "automations": [{"trigger": "risk.high", "action": "notify_owner"}],
                    "permissions": {"field_rules": {"budget": ["admin"], "status": ["admin", "basic"]}},
                },
                source_text=description, graph=graph, revision=2,
            )
            project_by_key[key] = project
            session.add(project)
            session.add(ProjectRevision(
                id=stable_id("project-revision", f"{key}:1"), project_id=project.id, version=1,
                title=title, description=description, status="active", profile=project.profile,
                source_text=description, graph=graph, change_summary="Initial enterprise workflow",
                created_by_id=user_by_key[owner_key].id, created_at=now - timedelta(days=20 + index),
            ))
            session.add(ProjectRevision(
                id=stable_id("project-revision", f"{key}:2"), project_id=project.id, version=2,
                title=title, description=description, status="active", profile=project.profile,
                source_text=description, graph=graph, change_summary="Added QA and approval controls",
                created_by_id=user_by_key["program"].id, created_at=now - timedelta(days=5 + index),
            ))
            for collaborator_key, role in [("program", "editor"), ("analyst", "commenter"), ("qa", "approver")]:
                session.add(ProjectCollaborator(project_id=project.id, user_id=user_by_key[collaborator_key].id, access_role=role))
            if key in {"soc2", "onboarding"}:
                session.add(ProjectCollaborator(project_id=project.id, user_id=user_by_key["guest"].id, access_role="viewer"))
            session.add(ProjectGroupAccess(
                id=stable_id("project-group", key), project_id=project.id,
                unit_id=unit_by_key[project_team_keys[index]].id, access_role="editor",
            ))
        await session.flush()

        work_items: list[WorkItem] = []
        work_by_project: dict[str, list[WorkItem]] = {}
        statuses = ["done", "in_qa", "review", "in_progress", "ready_for_qa", "selected", "blocked", "backlog"]
        assignee_keys = ["product", "engineering", "developer", "qa", "design", "analyst", "operations", "sales", "finance", "people", "support"]
        sequence = 1
        for project_index, (project_key, *_rest) in enumerate(PROJECTS):
            project = project_by_key[project_key]
            owner_key = project_owner_keys[project_index]
            project_items: list[WorkItem] = []
            hierarchy = [
                ("initiative", "Deliver the business outcome", None, 13, "discover"),
                ("epic", "Experience and process design", 0, 8, "design"),
                ("epic", "Implementation and rollout", 0, 13, "build"),
                ("story", "Validate user and stakeholder needs", 1, 5, "discover"),
                ("story", "Create the target-state workflow", 1, 5, "design"),
                ("story", "Implement the primary capability", 2, 8, "build"),
                ("story", "Integrate dependent systems", 2, 5, "build"),
                ("story", "Complete quality verification", 2, 3, "qa"),
                ("task", "Prepare training and communications", 2, 3, "approve"),
                ("bug", "Resolve priority release defect", 2, 3, "qa"),
                ("subtask", "Review acceptance criteria", 3, 2, "review"),
                ("subtask", "Run accessibility checks", 7, 2, "qa"),
                ("approval", "Secure business sign-off", 2, 1, "approve"),
                ("deliverable", "Publish operating package", 2, 3, "launch"),
                ("milestone", "Outcome launched", None, 1, "launch"),
                ("technical_debt", "Harden monitoring and support", 2, 3, "build"),
                ("spike", "Evaluate scale assumptions", 1, 2, "discover"),
                ("improvement", "Measure and optimize cycle time", 0, 3, "launch"),
            ]
            for item_index, (item_type, summary, parent_index, points, node_id) in enumerate(hierarchy):
                status = statuses[(item_index + project_index) % len(statuses)]
                assignee_key = assignee_keys[(item_index + project_index) % len(assignee_keys)]
                sprint_key = "previous" if status == "done" else "active" if status in {"in_progress", "in_qa", "review", "ready_for_qa", "blocked"} else "next" if status == "selected" else None
                release_key = "audit" if project_key == "soc2" else "pilot" if project_key == "stores" else "q3" if project_index < 4 else "q4"
                item = WorkItem(
                    id=stable_id("work", f"{project_key}:{item_index}"), entity_id=entity_id,
                    sequence_number=sequence, key=f"ACME-{sequence}", reporter_id=user_by_key[owner_key].id,
                    assignee_id=user_by_key[assignee_key].id, owner_id=user_by_key[owner_key].id,
                    sprint_id=sprint_by_key[sprint_key].id if sprint_key else None,
                    release_id=release_by_key[release_key].id, project_id=project.id,
                    parent_id=project_items[parent_index].id if parent_index is not None else None,
                    node_id=node_id, item_type=item_type,
                    summary=f"{project_key.upper()}: {summary}",
                    description=f"**Outcome:** {summary}\n\nCoordinate this work across the {project.profile['department']} team and document evidence.",
                    acceptance_criteria="- Owner confirms completion\n- QA evidence is attached\n- Stakeholders receive the outcome",
                    status=status, priority="highest" if status == "blocked" else "high" if item_type in {"epic", "bug"} else "medium",
                    severity="major" if item_type == "bug" else "none", story_points=points,
                    estimate_minutes=points * 120, actual_minutes=points * (90 + (item_index % 4) * 15),
                    component=project.profile["department"], team=project.profile["team"],
                    labels=[project_key, item_type, "demo"],
                    checklist=[{"id": "scope", "title": "Scope confirmed", "done": status != "backlog"}, {"id": "evidence", "title": "Evidence attached", "done": status == "done"}],
                    watcher_ids=[user_by_key["program"].id, user_by_key[owner_key].id],
                    custom_fields={"business_value": 10 - (item_index % 5), "customer_segment": "Enterprise" if project_index % 2 else "All customers"},
                    start_date=today - timedelta(days=max(0, 15 - item_index)),
                    due_date=today + timedelta(days=(item_index - 6) * 3 + project_index),
                    rank=float((item_index + 1) * 1024), revision=1,
                    created_at=now - timedelta(days=30 - min(item_index, 25)),
                )
                sequence += 1
                project_items.append(item); work_items.append(item); session.add(item)
            work_by_project[project_key] = project_items
        await session.flush()

        for project_key, project_items in work_by_project.items():
            for index, item in enumerate(project_items):
                session.add(WorkItemActivity(
                    id=stable_id("work-activity", f"{project_key}:{index}"), entity_id=entity_id,
                    work_item_id=item.id, actor_id=item.assignee_id or item.reporter_id,
                    action="created" if index % 3 else "status_changed",
                    changes={"status": item.status, "source": "enterprise-demo"},
                    created_at=now - timedelta(days=max(1, 20 - index)),
                ))
                if index % 3 == 0:
                    comment = WorkItemComment(
                        id=stable_id("work-comment", f"{project_key}:{index}"), entity_id=entity_id,
                        work_item_id=item.id, author_id=user_by_key["analyst"].id,
                        body=f"@{user_by_key['qa'].display_name} please validate the acceptance evidence for **{item.key}**.",
                        reactions={"👍": [user_by_key["qa"].id], "✅": [user_by_key["program"].id]},
                        attachments=[{"name": "Acceptance evidence", "url": "https://example.com/demo/evidence"}],
                        created_at=now - timedelta(days=4, hours=index),
                    )
                    session.add(comment)
                    if index % 6 == 0:
                        session.add(WorkItemComment(
                            id=stable_id("work-comment-reply", f"{project_key}:{index}"), entity_id=entity_id,
                            work_item_id=item.id, author_id=user_by_key["qa"].id, parent_id=comment.id,
                            body="Validation is scheduled. I added accessibility and regression coverage.",
                            reactions={"✅": [user_by_key["analyst"].id]}, created_at=now - timedelta(days=3, hours=index),
                        ))
            for link_index in range(3, 10):
                session.add(WorkItemLink(
                    id=stable_id("work-link", f"{project_key}:{link_index}"), entity_id=entity_id,
                    source_id=project_items[link_index - 1].id, target_id=project_items[link_index].id,
                    link_type="blocks" if link_index % 3 == 0 else "depends_on",
                    created_by_id=user_by_key["program"].id,
                ))
                session.add(ObjectRelationship(
                    id=stable_id("relationship", f"{project_key}:{link_index}"), entity_id=entity_id,
                    source_type="work_item", source_id=project_items[link_index - 1].id,
                    target_type="work_item", target_id=project_items[link_index].id,
                    relationship_type="blocks" if link_index % 3 == 0 else "depends_on",
                    metadata_json={"seed": True, "project": project_key}, created_by_id=user_by_key["platform"].id,
                ))
            for node_index, node_id in enumerate(["discover", "design", "build", "qa", "approve"]):
                session.add(NodePlanningBinding(
                    id=stable_id("node-binding", f"{project_key}:{node_id}"), entity_id=entity_id,
                    project_id=project_by_key[project_key].id, node_id=node_id,
                    primary_work_item_id=project_items[node_index + 3].id,
                    sprint_id=sprint_by_key["active"].id, created_by_id=user_by_key["program"].id,
                ))

        for project_index, (project_key, *_rest) in enumerate(PROJECTS):
            project = project_by_key[project_key]
            owner_key = project_owner_keys[project_index]
            for risk_index in range(3):
                probability = 2 + ((project_index + risk_index) % 4)
                impact = 2 + ((project_index * 2 + risk_index) % 4)
                session.add(ProjectRisk(
                    id=stable_id("risk", f"{project_key}:{risk_index}"), entity_id=entity_id,
                    project_id=project.id, owner_id=user_by_key[owner_key].id,
                    title=["Resource capacity pressure", "External dependency delay", "Data quality variance"][risk_index],
                    description="A realistic demonstration risk connected to delivery planning.",
                    probability=probability, impact=impact,
                    status="mitigating" if risk_index == 0 else "open" if risk_index == 1 else "accepted",
                    mitigation=["Rebalance capacity weekly", "Add contract milestone and fallback", "Run reconciliation and sampling controls"][risk_index],
                    due_date=today + timedelta(days=7 + risk_index * 10 + project_index),
                ))
            for decision_index in range(2):
                decision = ProjectDecision(
                    id=stable_id("decision", f"{project_key}:{decision_index}"), entity_id=entity_id,
                    project_id=project.id, owner_id=user_by_key[owner_key].id,
                    title=["Approve target operating model", "Select rollout strategy"][decision_index],
                    context="Stakeholders evaluated cost, customer impact, delivery risk, and operational readiness.",
                    decision="Use a phased rollout with measurable exit criteria." if decision_index else "Adopt the documented target-state workflow.",
                    alternatives=["Big-bang launch", "Maintain current process", "Limited pilot"],
                    consequences="The team will review metrics at each gate and can pause without losing completed work.",
                    status="accepted" if decision_index == 0 else "proposed",
                    decided_at=now - timedelta(days=project_index + 2) if decision_index == 0 else None,
                )
                session.add(decision)
            deliverable = ProjectDeliverable(
                id=stable_id("deliverable", project_key), project_id=project.id,
                creator_id=user_by_key["program"].id, owner_id=user_by_key[owner_key].id,
                title=f"{project.title} operating package", description="Approved workflow, training, controls, and launch evidence.",
                status="in_progress", target_date=today + timedelta(days=20 + project_index * 5), node_id="launch",
            )
            session.add(deliverable)
            session.add(ProjectTask(
                id=stable_id("project-task", project_key), project_id=project.id,
                creator_id=user_by_key["program"].id, assignee_id=user_by_key[owner_key].id,
                deliverable_id=deliverable.id, node_id="approve", title="Complete executive readiness review",
                details="Confirm risks, evidence, support ownership, and measurable launch criteria.",
                status="todo" if project_index % 2 else "in_progress", priority="high",
                due_date=today + timedelta(days=5 + project_index),
            ))
            session.add(ProjectNote(
                id=stable_id("project-note", project_key), project_id=project.id,
                author_id=user_by_key["analyst"].id, node_id="review",
                body=f"@{user_by_key[owner_key].display_name} confirm the decision owner before the next steering review.",
                resolved=project_index % 3 == 0,
            ))
            session.add(ProjectMessage(
                id=stable_id("project-message", project_key), project_id=project.id,
                user_id=user_by_key["program"].id,
                body="The weekly project review is ready. Please update blockers and evidence before the meeting.",
            ))

        space_specs = [
            ("company", "Company Handbook", "Policies, operating principles, and onboarding knowledge", "workspace"),
            ("product", "Product & Engineering", "Architecture, product discovery, and delivery practices", "workspace"),
            ("operations", "Operations Playbooks", "Standard operating procedures and controls", "workspace"),
            ("restricted", "Audit Room", "Restricted compliance evidence and audit records", "restricted"),
        ]
        space_by_key: dict[str, KnowledgeSpace] = {}
        for key, name, description, visibility in space_specs:
            space = KnowledgeSpace(
                id=stable_id("space", key), entity_id=entity_id, name=name, description=description,
                visibility=visibility, created_by_id=user_by_key["platform"].id,
            )
            space_by_key[key] = space; session.add(space)
        await session.flush()
        for user_key in ["platform", "program", "qa", "guest"]:
            session.add(KnowledgeSpaceMember(
                id=stable_id("space-member", f"restricted:{user_key}"), space_id=space_by_key["restricted"].id,
                user_id=user_by_key[user_key].id, role="editor" if user_key in {"platform", "qa"} else "viewer",
            ))

        docs: list[KnowledgeDocument] = []
        doc_templates = [
            ("company", "Operating Principles", "policy"), ("company", "New Hire Guide", "blank"),
            ("product", "Architecture Decision Log", "decision_record"), ("product", "Definition of Done", "policy"),
            ("operations", "Incident Response SOP", "sop"), ("operations", "Vendor Onboarding", "sop"),
            ("restricted", "SOC 2 Evidence Index", "policy"), ("restricted", "Quarterly Access Review", "meeting_notes"),
        ]
        for index in range(24):
            space_key, base_title, template = doc_templates[index % len(doc_templates)]
            title = f"{base_title} {index // len(doc_templates) + 1}" if index >= len(doc_templates) else base_title
            document = KnowledgeDocument(
                id=stable_id("document", str(index)), entity_id=entity_id, space_id=space_by_key[space_key].id,
                owner_id=user_by_key["platform" if space_key == "restricted" else "analyst"].id,
                title=title, slug=f"demo-{index}-{base_title.lower().replace(' ', '-')}",
                summary=f"Reusable enterprise example for {base_title.lower()}.",
                body=f"# {title}\n\nThis demo page captures decisions, owners, controls, and review evidence.\n\n## Related work\n\nSee [[doc:{stable_id('document', str((index + 1) % 24))}]].\n\n- Owner: @{user_by_key['analyst'].display_name}\n- Review cadence: Quarterly",
                status="published" if index % 5 else "draft",
                visibility="restricted" if space_key == "restricted" else "workspace",
                classification="restricted" if space_key == "restricted" else "internal", template=template,
                review_due_at=today + timedelta(days=30 + index), expires_at=today + timedelta(days=365 + index), revision=2,
            )
            docs.append(document); session.add(document)
            session.add(KnowledgeDocumentRevision(
                id=stable_id("document-revision", f"{index}:1"), document_id=document.id, version=1,
                title=title, summary=document.summary, body=document.body, status=document.status,
                classification=document.classification, change_summary="Initial demo version",
                created_by_id=document.owner_id, created_at=now - timedelta(days=20 - min(index, 18)),
            ))
        await session.flush()
        for index, document in enumerate(docs):
            next_document = docs[(index + 1) % len(docs)]
            session.add(KnowledgeDocumentLink(
                id=stable_id("document-link", str(index)), source_document_id=document.id,
                target_document_id=next_document.id,
            ))
            if document.visibility == "restricted":
                session.add(KnowledgeDocumentAccess(
                    id=stable_id("document-access", str(index)), document_id=document.id,
                    user_id=user_by_key["guest"].id, role="viewer",
                ))
            if index % 2 == 0:
                comment = KnowledgeComment(
                    id=stable_id("knowledge-comment", str(index)), document_id=document.id,
                    author_id=user_by_key["program"].id,
                    body=f"@{user_by_key['analyst'].display_name} please confirm the owner and next review date.",
                    resolved=index % 4 == 0,
                )
                session.add(comment)

        events: list[CalendarEvent] = []
        event_titles = ["Portfolio stand-up", "Sprint planning", "Customer journey review", "Architecture review", "QA triage", "Release readiness", "Risk committee", "Operations metrics", "Hiring calibration", "Audit evidence review"]
        for index in range(30):
            day = today + timedelta(days=(index % 16) - 5)
            organizer_key = ["program", "product", "engineering", "qa", "operations"][index % 5]
            event = CalendarEvent(
                id=stable_id("event", str(index)), entity_id=entity_id, organizer_id=user_by_key[organizer_key].id,
                title=f"{event_titles[index % len(event_titles)]} · {index // len(event_titles) + 1}",
                description="Demo meeting with decisions, actions, reminders, and shared availability.",
                event_type="personal" if index % 9 == 0 else "meeting",
                starts_at=at(day, 14 + (index % 3)), ends_at=at(day, 15 + (index % 3)), timezone="UTC",
                location="Workspace video room" if index % 2 else "Conference Room Atlas",
                meeting_url=f"https://example.com/demo/meeting/{index}",
                agenda="1. Progress\n2. Risks and dependencies\n3. Decisions\n4. Next actions",
                notes="Decision: Proceed with the phased option.\nAction: Update the release evidence by Friday.\nRisk: Capacity is constrained during the migration window.",
                action_items=[{"id": f"action-{index}", "text": "Update the release evidence by Friday", "status": "open"}],
                transcript="Decision: Proceed with the phased option.\nAction: Update the release evidence by Friday.\nRisk: Capacity is constrained during the migration window.",
                recording_url=f"https://example.com/demo/recordings/{index}" if index % 4 == 0 else "",
                series_id=stable_id("series", event_titles[index % len(event_titles)]) if index % 5 == 0 else None,
                recurrence_frequency="weekly" if index % 5 == 0 else None,
                recurrence_count=8 if index % 5 == 0 else None, occurrence_index=index // 5 if index % 5 == 0 else 0,
            )
            events.append(event); session.add(event)
        await session.flush()
        attendee_keys = ["executive", "program", "product", "engineering", "developer", "qa", "analyst", "operations", "sales", "finance", "people", "support"]
        for index, event in enumerate(events):
            if event.event_type == "personal":
                continue
            for offset in range(4):
                attendee_key = attendee_keys[(index + offset) % len(attendee_keys)]
                session.add(CalendarEventAttendee(
                    id=stable_id("event-attendee", f"{index}:{attendee_key}"), event_id=event.id,
                    user_id=user_by_key[attendee_key].id,
                    response=["accepted", "accepted", "tentative", "pending"][offset], reminder_minutes=[15, 30, 60, None][offset],
                ))
            if index % 7 == 0:
                session.add(CalendarEventExternalAttendee(
                    id=stable_id("external-attendee", str(index)), event_id=event.id,
                    email=f"partner{index}@example.com", response="pending", status="active", delivery_status="sent",
                ))

        channel_specs = [
            ("general", "General", "Workspace announcements and cross-team updates", "channel", "workspace"),
            ("product", "product-delivery", "Product and engineering delivery", "channel", "workspace"),
            ("releases", "release-readiness", "Cross-functional release coordination", "channel", "workspace"),
            ("support", "customer-operations", "Support trends and operating issues", "channel", "workspace"),
            ("leadership", "Leadership planning", "Private leadership planning group", "group", "private"),
            ("audit", "Audit working group", "Restricted evidence coordination", "group", "private"),
        ]
        channel_by_key: dict[str, CommunicationChannel] = {}
        all_member_keys = [key for key, *_ in USERS if key != "guest"]
        for key, name, description, kind, visibility in channel_specs:
            channel = CommunicationChannel(
                id=stable_id("channel", key), entity_id=entity_id, created_by_id=user_by_key["platform"].id,
                name=name, description=description, channel_type=kind, visibility=visibility,
            )
            channel_by_key[key] = channel; session.add(channel)
        await session.flush()
        for channel_key, channel in channel_by_key.items():
            member_keys = all_member_keys if channel.visibility == "workspace" else (["executive", "platform", "program", "finance"] if channel_key == "leadership" else ["platform", "program", "qa", "guest"])
            for index, member_key in enumerate(member_keys):
                session.add(CommunicationChannelMember(
                    id=stable_id("channel-member", f"{channel_key}:{member_key}"), channel_id=channel.id,
                    user_id=user_by_key[member_key].id, role="owner" if index == 0 else "member",
                    last_read_at=now - timedelta(hours=index % 4),
                ))
            for message_index in range(18):
                sender_key = member_keys[message_index % len(member_keys)]
                session.add(CommunicationChannelMessage(
                    id=stable_id("channel-message", f"{channel_key}:{message_index}"), entity_id=entity_id,
                    channel_id=channel.id, sender_id=user_by_key[sender_key].id,
                    body=[
                        "Weekly update: delivery is moving, but please review the linked blockers.",
                        "Decision: use the phased rollout and keep the rollback gate measurable.",
                        "@Priya Shah can you confirm the steering review agenda?",
                        "QA evidence is ready. The remaining defect is documented on the release board.",
                        "Please update owners and due dates before tomorrow's checkpoint.",
                        "The new dashboard shows cycle time improving across the active sprint.",
                    ][message_index % 6],
                    reactions={"👍": [user_by_key[member_keys[(message_index + 1) % len(member_keys)]].id]} if message_index % 4 == 0 else {},
                    pinned=message_index == 1,
                    attachments=[{"name": "Demo release dashboard", "url": "https://example.com/demo/dashboard"}] if message_index % 7 == 0 else [],
                    created_at=now - timedelta(hours=(18 - message_index) * 2),
                ))

        for index in range(36):
            sender_key = all_member_keys[index % len(all_member_keys)]
            recipient_key = all_member_keys[(index + 3) % len(all_member_keys)]
            session.add(DirectMessage(
                id=stable_id("direct-message", str(index)), entity_id=entity_id,
                sender_id=user_by_key[sender_key].id, recipient_id=user_by_key[recipient_key].id,
                body=f"Demo follow-up {index + 1}: please review the delivery update and reply with any blocker.",
                reactions={"✅": [user_by_key[recipient_key].id]} if index % 5 == 0 else {},
                read_at=now - timedelta(hours=1) if index % 3 else None,
                created_at=now - timedelta(hours=40 - index),
            ))

        for kind in ["assignment", "mention", "comment", "deadline", "approval", "meeting", "risk", "dependency", "workflow", "chat"]:
            session.add(NotificationPreference(
                id=stable_id("notification-preference", f"program:{kind}"), user_id=user_by_key["program"].id,
                kind=kind, in_app=True, email=kind in {"approval", "deadline", "risk"},
                push=kind in {"assignment", "meeting"}, digest="daily" if kind in {"comment", "workflow"} else "none",
            ))
        for user_index, user_key in enumerate([key for key, *_ in USERS]):
            for notification_index in range(6):
                item = work_items[(user_index * 7 + notification_index) % len(work_items)]
                session.add(Notification(
                    id=stable_id("notification", f"{user_key}:{notification_index}"), entity_id=entity_id,
                    user_id=user_by_key[user_key].id, actor_id=user_by_key["program"].id,
                    kind=["assignment", "mention", "deadline", "risk", "approval", "meeting"][notification_index],
                    title=["New assignment", "You were mentioned", "Deadline approaching", "Risk score changed", "Approval requested", "Meeting updated"][notification_index],
                    body=f"Demo activity for {item.key} · {item.summary}", project_id=item.project_id,
                    work_item_id=item.id if notification_index < 5 else None,
                    calendar_event_id=events[notification_index].id if notification_index == 5 else None,
                    group_key=f"demo:{user_key}:{notification_index}",
                    read_at=now - timedelta(days=1) if notification_index == 0 else None,
                    created_at=now - timedelta(hours=notification_index + user_index % 3),
                ))

        folder = WorkspaceFile(
            id=stable_id("file", "program-folder"), entity_id=entity_id, owner_id=user_by_key["program"].id,
            name="Enterprise Program Office", item_type="folder", provider="workspace", tags=["portfolio", "demo"],
            description="Shared program files, evidence, and planning artifacts.", shared_with_ids=[user_by_key["executive"].id],
        )
        session.add(folder)
        await session.flush()
        for index in range(24):
            session.add(WorkspaceFile(
                id=stable_id("file", str(index)), entity_id=entity_id,
                owner_id=user_by_key[["program", "analyst", "qa", "finance"][index % 4]].id,
                parent_id=folder.id if index < 12 else None,
                name=["Project brief", "Risk register", "Test evidence", "Release checklist", "Budget model", "Training plan"][index % 6] + f" {index + 1}",
                item_type="external", mime_type="text/html", external_url=f"https://example.com/demo/files/{index}",
                provider=["workspace", "dropbox", "box", "google_drive"][index % 4], classification="confidential" if index % 5 == 0 else "internal",
                tags=[["planning", "demo"], ["risk", "governance"], ["qa", "evidence"]][index % 3],
                version=1 + index % 4, visibility="restricted" if index % 7 == 0 else "workspace",
                description="Searchable demonstration file metadata.", content_text="Owners milestones risks decisions evidence approval launch",
                preview_url=f"https://example.com/demo/previews/{index}",
                shared_with_ids=[user_by_key["guest"].id] if index % 7 == 0 else [],
            ))

        for index, (name, widgets) in enumerate([
            ("Executive portfolio", ["work_kpi", "risk_exposure", "release_burnup", "team_capacity"]),
            ("Delivery health", ["sprint_velocity", "upcoming_meetings", "risk_exposure"]),
            ("Quality command center", ["work_kpi", "sprint_velocity", "release_burnup"]),
        ]):
            session.add(WorkspaceDashboard(
                id=stable_id("dashboard", str(index)), entity_id=entity_id,
                owner_id=user_by_key[["executive", "program", "qa"][index]].id, name=name,
                widgets=[{"type": widget, "title": widget.replace("_", " ").title()} for widget in widgets],
                layout=[{"widget": widget, "x": position % 2, "y": position // 2, "w": 1, "h": 1} for position, widget in enumerate(widgets)],
                shared=True, delivery={"frequency": "weekly", "recipients": [user_by_key["executive"].id]},
            ))
        for index, (name, view_type, config) in enumerate([
            ("My active sprint", "board", {"mine": True, "active_sprint": True, "swimlane": "project"}),
            ("Team QA queue", "board", {"mine": False, "active_sprint": True, "swimlane": "team"}),
            ("Risk by status", "report", {"object_type": "risk", "group_by": "status", "measure": "risk_score"}),
            ("Release work", "bulk_selection", {"release_id": release_by_key["q3"].id, "item_ids": [item.id for item in work_items[:20]]}),
        ]):
            session.add(SavedWorkspaceView(
                id=stable_id("saved-view", str(index)), entity_id=entity_id, owner_id=user_by_key["program"].id,
                name=name, view_type=view_type, config=config, shared=index != 0, is_default=index == 0,
            ))

        approval_definition = ApprovalDefinition(
            id=stable_id("approval-definition", "enterprise-gate"), entity_id=entity_id,
            name="Enterprise delivery gate", target_types=["project", "release", "risk", "document", "file"],
            stages=[
                {"name": "Delivery review", "mode": "parallel", "approver_ids": [user_by_key["program"].id, user_by_key["qa"].id]},
                {"name": "Executive approval", "mode": "sequential", "approver_ids": [user_by_key["executive"].id]},
            ], reminder_hours=24, escalation_hours=48, created_by_id=user_by_key["platform"].id,
        )
        session.add(approval_definition)
        await session.flush()
        approval_targets = [("project", project_by_key["mobile"].id), ("release", release_by_key["q3"].id), ("document", docs[6].id), ("risk", stable_id("risk", "erp:0"))]
        for index, (target_type, target_id) in enumerate(approval_targets):
            session.add(ApprovalInstance(
                id=stable_id("approval-instance", str(index)), entity_id=entity_id,
                definition_id=approval_definition.id, target_type=target_type, target_id=target_id,
                requested_by_id=user_by_key["program"].id, current_stage=0,
                status="approved" if index == 0 else "pending",
                decisions=[{"stage": 0, "user_id": user_by_key["qa"].id, "decision": "approved", "note": "Evidence reviewed", "at": now.isoformat()}] if index == 0 else [],
                due_at=now + timedelta(days=2 + index),
            ))

        for project_index, (project_key, *_rest) in enumerate(PROJECTS):
            project = project_by_key[project_key]
            meeting = events[project_index]
            document = docs[project_index]
            for relationship_index, (target_type, target_id, relationship_type) in enumerate([
                ("document", document.id, "documented_by"),
                ("meeting", meeting.id, "discussed_in"),
                ("release", release_by_key["q3" if project_index < 4 else "q4"].id, "contributes_to"),
            ]):
                session.add(ObjectRelationship(
                    id=stable_id("project-relationship", f"{project_key}:{relationship_index}"), entity_id=entity_id,
                    source_type="project", source_id=project.id, target_type=target_type, target_id=target_id,
                    relationship_type=relationship_type, metadata_json={"seed": True},
                    created_by_id=user_by_key["platform"].id,
                ))
            session.add(AuditEvent(
                id=stable_id("audit", project_key), entity_id=entity_id, project_id=project.id,
                actor_id=user_by_key[project_owner_keys[project_index]].id, action="project.demo_seeded",
                target_type="project", target_id=project.id,
                details={"title": project.title, "work_items": len(work_by_project[project_key])},
                request_id=f"demo-seed-{project_index}", created_at=now - timedelta(minutes=20 - project_index),
            ))

        await session.commit()
        print(f"Created {ENTITY_NAME}.")
        print(await dataset_counts(session, entity_id))
        print(f"Password for every demo account: {DEMO_PASSWORD}")


if __name__ == "__main__":
    asyncio.run(seed())
