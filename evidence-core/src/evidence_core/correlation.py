"""Explainable, deterministic event correlation."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from typing import Iterable

from .models import EvidenceRecord


SIGNALS = ("identity", "resource", "session_id", "trace_id", "ip_address", "workflow_run_id")


@dataclass(frozen=True, slots=True)
class CorrelationCluster:
    cluster_id: str
    record_ids: tuple[str, ...]
    reasons: tuple[str, ...]
    confidence: float


class EventCorrelator:
    def __init__(self, window: timedelta = timedelta(minutes=15), minimum_score: float = 0.45) -> None:
        self.window = window
        self.minimum_score = minimum_score

    @staticmethod
    def _values(record: EvidenceRecord) -> dict[str, str]:
        metadata = record.metadata
        payload = record.payload
        return {signal: str(metadata.get(signal) or payload.get(signal) or "") for signal in SIGNALS}

    def _score(self, left: EvidenceRecord, right: EvidenceRecord) -> tuple[float, list[str]]:
        delta = abs((left.observed_at - right.observed_at).total_seconds())
        if delta > self.window.total_seconds():
            return 0.0, []
        left_values, right_values = self._values(left), self._values(right)
        weights = {"trace_id": .55, "session_id": .45, "workflow_run_id": .45, "identity": .28, "resource": .25, "ip_address": .12}
        reasons = [signal for signal in SIGNALS if left_values[signal] and left_values[signal] == right_values[signal]]
        score = min(1.0, sum(weights[reason] for reason in reasons) + .1 * (1 - delta / self.window.total_seconds()))
        return score, reasons

    def correlate(self, records: Iterable[EvidenceRecord]) -> list[CorrelationCluster]:
        items = sorted(records, key=lambda item: (item.observed_at, item.evidence_id))
        parent = list(range(len(items)))
        reasons_by_root: dict[int, set[str]] = {index: set() for index in range(len(items))}
        scores_by_root: dict[int, list[float]] = {index: [] for index in range(len(items))}

        def find(index: int) -> int:
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        def union(left: int, right: int, score: float, reasons: list[str]) -> None:
            left_root, right_root = find(left), find(right)
            if left_root != right_root:
                parent[right_root] = left_root
                reasons_by_root[left_root].update(reasons_by_root.pop(right_root, set()))
                scores_by_root[left_root].extend(scores_by_root.pop(right_root, []))
            root = find(left)
            reasons_by_root[root].update(reasons)
            scores_by_root[root].append(score)

        for left in range(len(items)):
            for right in range(left + 1, len(items)):
                if items[right].observed_at - items[left].observed_at > self.window:
                    break
                score, reasons = self._score(items[left], items[right])
                if score >= self.minimum_score:
                    union(left, right, score, reasons)

        groups: dict[int, list[EvidenceRecord]] = defaultdict(list)
        for index, item in enumerate(items):
            groups[find(index)].append(item)
        clusters = []
        for root, members in groups.items():
            scores = scores_by_root.get(find(root), [])
            clusters.append(CorrelationCluster(
                cluster_id=f"cluster-{min(item.evidence_id for item in members)}",
                record_ids=tuple(sorted(item.evidence_id for item in members)),
                reasons=tuple(sorted(reasons_by_root.get(find(root), set()))),
                confidence=round(sum(scores) / len(scores), 4) if scores else 0.0,
            ))
        return sorted(clusters, key=lambda item: item.cluster_id)
