"""Azure Key Vault diagnostic log normalizer."""

from __future__ import annotations

from typing import Any

from evidence_core.models import EvidenceRecord

from .base import Connector, first, parse_time, stable_id


class KeyVaultConnector(Connector):
    source = "azure-key-vault"

    def normalize(self, item: dict[str, Any]) -> EvidenceRecord:
        properties = item.get("properties", {})
        identity = item.get("identity", {})
        if isinstance(identity, dict):
            identity = identity.get("claim", {}).get("upn") or identity.get("principalId", "")
        return EvidenceRecord(
            source=self.source,
            kind=str(first(item, "operationName", "operation_name", default="vault.audit")),
            observed_at=parse_time(first(item, "time", "TimeGenerated", "timestamp")),
            evidence_id=stable_id(self.source, item, "correlationId", "operationId"),
            payload=item,
            metadata={
                "identity": str(identity),
                "resource": str(first(item, "resourceId", "ResourceId")),
                "trace_id": str(first(item, "correlationId", "operationId")),
                "ip_address": str(properties.get("clientIpAddress", properties.get("clientInfo", ""))),
                "result": str(first(item, "resultType", "resultSignature", default="")),
            },
        )
