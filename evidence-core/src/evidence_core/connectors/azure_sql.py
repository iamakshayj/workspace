"""Azure SQL audit export normalizer."""

from __future__ import annotations

from typing import Any, Iterable

from evidence_core.models import EvidenceRecord

from .base import Connector, first, parse_time, stable_id


class AzureSqlConnector(Connector):
    source = "azure-sql"

    def normalize(self, item: dict[str, Any]) -> EvidenceRecord:
        identity = str(first(item, "server_principal_name", "session_server_principal_name", "principal"))
        resource = str(first(item, "database_name", "resource_id", "server_instance_name"))
        statement = str(first(item, "statement", "query", default=""))
        return EvidenceRecord(
            evidence_id=stable_id(self.source, item, "event_id", "sequence_number"),
            source=self.source,
            kind=str(first(item, "action_name", "event_type", default="database.audit")),
            observed_at=parse_time(first(item, "event_time", "event_time_t", "timestamp")),
            payload={**item, "statement": statement},
            metadata={
                "identity": identity,
                "resource": resource,
                "session_id": str(first(item, "session_id", "session_server_principal_name")),
                "ip_address": str(first(item, "client_ip", "client_ip_s")),
                "result": str(first(item, "succeeded", "result")),
            },
        )

    def collect(self, connection: Any, query: str, parameters: tuple[Any, ...] = ()) -> list[EvidenceRecord]:
        """Collect through a caller-provided PEP-249 connection; credentials remain outside core."""
        cursor = connection.cursor()
        cursor.execute(query, parameters)
        columns = [description[0] for description in cursor.description]
        return self.normalize_many(dict(zip(columns, row, strict=True)) for row in cursor.fetchall())
