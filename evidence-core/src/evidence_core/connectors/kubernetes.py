"""Kubernetes audit log normalizer."""

from __future__ import annotations

from typing import Any

from evidence_core.models import EvidenceRecord

from .base import Connector, first, parse_time, stable_id


class KubernetesAuditConnector(Connector):
    source = "kubernetes"

    def normalize(self, item: dict[str, Any]) -> EvidenceRecord:
        user = item.get("user", {})
        object_ref = item.get("objectRef", {})
        response = item.get("responseStatus", {})
        resource = "/".join(str(object_ref.get(key, "")) for key in ("namespace", "resource", "name") if object_ref.get(key))
        return EvidenceRecord(
            source=self.source,
            kind=f"kubernetes.{first(item, 'verb', default='audit')}",
            observed_at=parse_time(first(item, "stageTimestamp", "requestReceivedTimestamp", "timestamp")),
            evidence_id=stable_id(self.source, item, "auditID", "requestURI"),
            payload=item,
            metadata={
                "identity": str(user.get("username", "")),
                "resource": resource or str(first(item, "requestURI", default="")),
                "trace_id": str(first(item, "auditID", default="")),
                "ip_address": str((item.get("sourceIPs") or [""])[0]),
                "result": str(response.get("code", "")),
            },
        )
