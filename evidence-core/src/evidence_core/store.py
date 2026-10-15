"""In-memory reference index for reproducible query measurements."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from .canonical import canonical_json
from .models import EvidenceRecord


class EvidenceIndex:
    """Small reference implementation; production deployments can replace the adapter."""

    def __init__(self, records: Iterable[EvidenceRecord] = ()) -> None:
        self._records: dict[str, EvidenceRecord] = {}
        self._source: dict[str, set[str]] = defaultdict(set)
        self._kind: dict[str, set[str]] = defaultdict(set)
        self._identity: dict[str, set[str]] = defaultdict(set)
        for record in records:
            self.add(record)

    def add(self, record: EvidenceRecord) -> None:
        if record.evidence_id in self._records:
            raise ValueError(f"Duplicate evidence id: {record.evidence_id}")
        self._records[record.evidence_id] = record
        self._source[record.source].add(record.evidence_id)
        self._kind[record.kind].add(record.evidence_id)
        identity = str(record.metadata.get("identity", ""))
        if identity:
            self._identity[identity].add(record.evidence_id)

    def filter(self, *, source: str | None = None, kind: str | None = None, identity: str | None = None) -> list[EvidenceRecord]:
        candidates = set(self._records)
        if source is not None:
            candidates &= self._source.get(source, set())
        if kind is not None:
            candidates &= self._kind.get(kind, set())
        if identity is not None:
            candidates &= self._identity.get(identity, set())
        return [self._records[item] for item in sorted(candidates)]

    def keyword(self, term: str, limit: int = 100) -> list[EvidenceRecord]:
        needle = term.casefold()
        results = [record for record in self._records.values() if needle in canonical_json(record.as_dict()).decode("utf-8").casefold()]
        return sorted(results, key=lambda item: item.evidence_id)[:limit]

    def __len__(self) -> int:
        return len(self._records)
