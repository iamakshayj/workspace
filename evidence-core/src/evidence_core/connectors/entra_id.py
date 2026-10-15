"""Microsoft Entra ID audit and sign-in export normalizer."""

from __future__ import annotations

from typing import Any

from evidence_core.models import EvidenceRecord

from .base import Connector, first, parse_time, stable_id


class EntraIdConnector(Connector):
    source = "entra-id"

    def normalize(self, item: dict[str, Any]) -> EvidenceRecord:
        user = item.get("userPrincipalName") or item.get("initiatedBy", {}).get("user", {}).get("userPrincipalName", "")
        targets = item.get("targetResources") or [{}]
        resource = item.get("resourceDisplayName") or targets[0].get("displayName", "")
        status = item.get("status") or item.get("result", "")
        if isinstance(status, dict):
            status = status.get("errorCode", status.get("status", ""))
        return EvidenceRecord(
            source=self.source,
            kind=str(first(item, "activityDisplayName", "riskEventType", default="identity.audit")),
            observed_at=parse_time(first(item, "createdDateTime", "activityDateTime", "timestamp")),
            evidence_id=stable_id(self.source, item, "id", "correlationId"),
            payload=item,
            metadata={
                "identity": str(user),
                "resource": str(resource),
                "session_id": str(first(item, "sessionId", "originalRequestId")),
                "trace_id": str(first(item, "correlationId", "requestId")),
                "ip_address": str(first(item, "ipAddress", default="")),
                "result": str(status),
            },
        )
