from datetime import datetime, timezone
from types import SimpleNamespace

from backend.app.process_intelligence import analytics_from_events


def event(case_id: str, node_id: str | None, occurred_at: str, *, status: str = "completed", cost: float = 0):
    return SimpleNamespace(
        case_id=case_id,
        node_id=node_id,
        occurred_at=datetime.fromisoformat(occurred_at).replace(tzinfo=timezone.utc),
        status=status,
        cost=cost,
    )


def test_process_analytics_detects_drift_required_steps_sla_and_failures() -> None:
    graph = {
        "nodes": [
            {"id": "start", "label": "Request", "sla_minutes": 5},
            {"id": "review", "label": "Controlled review", "required": True, "control_id": "CTRL-1"},
            {"id": "approve", "label": "Approve"},
        ],
        "edges": [
            {"source": "start", "target": "review"},
            {"source": "review", "target": "approve"},
        ],
    }
    events = [
        event("case-1", "start", "2026-08-29T10:00:00", cost=2),
        event("case-1", "approve", "2026-08-29T10:20:00", status="failed", cost=4),
        event("case-2", "start", "2026-08-29T11:00:00"),
        event("case-2", "review", "2026-08-29T11:03:00"),
        event("case-2", "approve", "2026-08-29T11:04:00"),
    ]

    analytics, insights = analytics_from_events(graph, events)

    assert analytics["case_count"] == 2
    assert analytics["event_count"] == 5
    assert analytics["conformance_rate"] == 66.7
    assert next(item for item in analytics["node_metrics"] if item.node_id == "start").sla_breach_count == 1
    assert next(item for item in analytics["node_metrics"] if item.node_id == "approve").failure_count == 1
    assert any(item["kind"] == "unexpected_transition" for item in insights)
    assert any(item["kind"] == "required_step_skipped" and item["severity"] == "critical" for item in insights)
    assert any(item["kind"] == "sla_breach" for item in insights)
    assert any(item["kind"] == "execution_failure" for item in insights)
