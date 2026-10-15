"""Deterministic, non-PHI healthcare security evidence fixtures."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from .models import EvidenceRecord


@dataclass(frozen=True, slots=True)
class SyntheticDataset:
    records: tuple[EvidenceRecord, ...]
    incident_by_record: dict[str, str]


def healthcare_dataset(incident_count: int = 25, noise_count: int = 100, seed: int = 42) -> SyntheticDataset:
    """Create fictional events and hidden cluster labels; no patient data is represented."""
    randomizer = random.Random(seed)
    start = datetime(2026, 1, 1, 9, tzinfo=timezone.utc)
    records: list[EvidenceRecord] = []
    truth: dict[str, str] = {}
    sources = ("entra-id", "azure-key-vault", "kubernetes", "github-actions", "azure-sql")
    for incident_index in range(incident_count):
        incident_id = f"incident-{incident_index:05d}"
        identity = f"synthetic-user-{incident_index % 17:03d}@example.invalid"
        trace_id = f"trace-{seed}-{incident_index:05d}"
        base_time = start + timedelta(minutes=incident_index * 20)
        for event_index, source in enumerate(sources[: 2 + incident_index % 4]):
            evidence_id = f"syn-{incident_index:05d}-{event_index:02d}"
            records.append(EvidenceRecord(
                evidence_id=evidence_id,
                source=source,
                kind="synthetic.security-event",
                observed_at=base_time + timedelta(seconds=event_index * 45),
                payload={"outcome": "success", "synthetic": True},
                control_ids=("AC-2", "AU-6"),
                metadata={
                    "identity": identity,
                    "trace_id": trace_id,
                    "resource": f"synthetic-clinical-service-{incident_index % 8}",
                    "ip_address": f"192.0.2.{1 + incident_index % 200}",
                    "synthetic": True,
                },
            ))
            truth[evidence_id] = incident_id
    for noise_index in range(noise_count):
        evidence_id = f"noise-{noise_index:06d}"
        records.append(EvidenceRecord(
            evidence_id=evidence_id,
            source=randomizer.choice(sources),
            kind="synthetic.background-event",
            observed_at=start + timedelta(seconds=randomizer.randrange(max(1, incident_count * 1200))),
            payload={"outcome": "success", "synthetic": True},
            metadata={
                "identity": f"noise-user-{noise_index}@example.invalid",
                "resource": f"noise-resource-{noise_index}",
                "trace_id": f"noise-trace-{noise_index}",
                "synthetic": True,
            },
        ))
        truth[evidence_id] = f"noise-singleton-{noise_index:06d}"
    records.sort(key=lambda item: (item.observed_at, item.evidence_id))
    return SyntheticDataset(tuple(records), truth)


def pairs(groups: Iterable[Iterable[str]]) -> set[tuple[str, str]]:
    result: set[tuple[str, str]] = set()
    for group in groups:
        members = sorted(group)
        result.update((left, right) for index, left in enumerate(members) for right in members[index + 1 :])
    return result
