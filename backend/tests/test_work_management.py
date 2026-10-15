import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from backend.app.work_management import (
    NodePlanUpdate,
    NodeWorkItemCreate,
    SprintCreate,
    WorkItemBulkUpdate,
    WorkItemCreate,
    WorkWorkflowUpdate,
    require_admin,
    validate_item_references,
    weighted_progress,
    work_workflow,
    work_prefix,
)


def test_work_item_validates_dates_and_normalizes_labels() -> None:
    item = WorkItemCreate(
        summary="  Improve onboarding  ",
        start_date="2026-09-01",
        due_date="2026-09-10",
        labels=[" customer ", "customer", "platform"],
    )

    assert item.summary == "Improve onboarding"
    assert item.labels == ["customer", "platform"]


def test_work_item_rejects_an_inverted_schedule() -> None:
    with pytest.raises(ValidationError, match="Start date"):
        WorkItemCreate(summary="Late plan", start_date="2026-09-10", due_date="2026-09-01")


def test_sprint_rejects_an_inverted_schedule() -> None:
    with pytest.raises(ValidationError, match="Sprint start date"):
        SprintCreate(name="Sprint 1", start_date="2026-09-10", end_date="2026-09-01")


def test_bulk_triage_supports_sprint_release_and_delivery_fields() -> None:
    update = WorkItemBulkUpdate(
        item_ids=["work-1", "work-2"],
        status="in_qa",
        sprint_id="sprint-2",
        release_id="release-1",
        story_points=5,
        component="Platform",
        team="Core delivery",
    )

    assert update.model_dump(exclude_unset=True) == {
        "item_ids": ["work-1", "work-2"],
        "status": "in_qa",
        "sprint_id": "sprint-2",
        "release_id": "release-1",
        "story_points": 5,
        "component": "Platform",
        "team": "Core delivery",
    }


def test_workspace_key_prefix_is_short_and_stable() -> None:
    assert work_prefix("Northwind Operations Group") == "NOG"
    assert work_prefix("Acme") == "ACME"


def test_sprint_and_release_administration_is_role_protected() -> None:
    require_admin(SimpleNamespace(role="admin"))
    with pytest.raises(HTTPException) as error:
        require_admin(SimpleNamespace(role="basic"))
    assert error.value.status_code == 403


def test_node_plan_supports_primary_work_sprint_and_subflow_together() -> None:
    plan = NodePlanUpdate(
        expected_revision=3,
        primary_work_item_id="item-1",
        sprint_id="sprint-1",
        subflow_project_id="project-2",
    )
    assert plan.model_dump() == {
        "expected_revision": 3,
        "primary_work_item_id": "item-1",
        "sprint_id": "sprint-1",
        "subflow_project_id": "project-2",
    }


def test_node_work_items_reject_invalid_story_points() -> None:
    with pytest.raises(ValidationError):
        NodeWorkItemCreate(summary="Oversized story", story_points=-1)


def test_subtask_requires_a_story_or_task_parent() -> None:
    async def scenario() -> None:
        session = SimpleNamespace(get=AsyncMock())
        user = SimpleNamespace(entity_id="entity-1")

        with pytest.raises(HTTPException, match="must belong to a story or task"):
            await validate_item_references(
                session, {"item_type": "subtask", "parent_id": None}, user,
            )

    asyncio.run(scenario())


def test_story_and_subtask_parent_types_are_enforced() -> None:
    async def scenario() -> None:
        user = SimpleNamespace(entity_id="entity-1")
        epic = SimpleNamespace(id="epic-1", entity_id="entity-1", item_type="epic", parent_id=None)
        story = SimpleNamespace(id="story-1", entity_id="entity-1", item_type="story", parent_id="epic-1")
        entity = SimpleNamespace(work_columns=None, work_item_types=None)
        session = SimpleNamespace(get=AsyncMock(side_effect=lambda _model, value: {
            "entity-1": entity, "epic-1": epic, "story-1": story,
        }[value]))

        await validate_item_references(
            session, {"item_type": "story", "parent_id": "epic-1"}, user,
        )
        await validate_item_references(
            session, {"item_type": "subtask", "parent_id": "story-1"}, user,
        )
        with pytest.raises(HTTPException, match="subtask can only belong"):
            await validate_item_references(
                session, {"item_type": "subtask", "parent_id": "epic-1"}, user,
            )

    asyncio.run(scenario())


def test_custom_workflow_requires_a_completed_stage_and_valid_type_links() -> None:
    with pytest.raises(ValidationError, match="completed column"):
        WorkWorkflowUpdate(
            columns=[
                {"id": "todo", "label": "To do", "category": "queue"},
                {"id": "working", "label": "Working", "category": "active"},
            ],
            item_types=[{"id": "case", "label": "Case"}],
        )
    with pytest.raises(ValidationError, match="unknown parent type"):
        WorkWorkflowUpdate(
            columns=[
                {"id": "todo", "label": "To do", "category": "queue"},
                {"id": "complete", "label": "Complete", "category": "done"},
            ],
            item_types=[{"id": "case", "label": "Case", "parent_types": ["missing"]}],
        )


def test_qa_status_contributes_partial_weighted_progress() -> None:
    entity = SimpleNamespace(work_columns=[
        {"id": "working", "label": "Working", "category": "active", "progress": 40},
        {"id": "quality", "label": "Quality check", "category": "qa", "progress": 80},
        {"id": "complete", "label": "Complete", "category": "done", "progress": 100},
    ], work_item_types=[{"id": "case", "label": "Case", "icon": "□", "parent_types": [], "child_type": None}])
    workflow = work_workflow(entity)
    items = [
        SimpleNamespace(status="working", story_points=2),
        SimpleNamespace(status="quality", story_points=2),
    ]
    assert weighted_progress(items, workflow) == 60
