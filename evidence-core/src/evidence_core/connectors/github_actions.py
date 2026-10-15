"""GitHub Actions workflow export normalizer."""

from __future__ import annotations

from typing import Any

from evidence_core.models import EvidenceRecord

from .base import Connector, first, parse_time, stable_id


class GitHubActionsConnector(Connector):
    source = "github-actions"

    def normalize(self, item: dict[str, Any]) -> EvidenceRecord:
        actor = item.get("actor", {})
        repository = item.get("repository", {})
        return EvidenceRecord(
            source=self.source,
            kind=f"workflow.{first(item, 'event', default='run')}",
            observed_at=parse_time(first(item, "run_started_at", "created_at", "updated_at")),
            evidence_id=stable_id(self.source, item, "id", "run_number"),
            payload=item,
            metadata={
                "identity": str(actor.get("login", actor) if isinstance(actor, dict) else actor),
                "resource": str(repository.get("full_name", repository) if isinstance(repository, dict) else repository),
                "workflow_run_id": str(first(item, "id", "run_id", default="")),
                "trace_id": str(first(item, "check_suite_id", "node_id", default="")),
                "result": str(first(item, "conclusion", "status", default="")),
            },
        )
