"""Reproducible benchmark with synthetic ground truth."""

from __future__ import annotations

import json
import os
import platform
import sys
import tempfile
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .correlation import EventCorrelator
from .pack import create_evidence_pack, verify_evidence_pack
from .synthetic import healthcare_dataset, pairs
from .store import EvidenceIndex


def _rate(count: int, elapsed: float) -> float:
    return round(count / max(elapsed, 1e-9), 2)


def modeled_cost_comparison(manual_minutes: float, assisted_minutes: float, hourly_cost: float, compute_cost: float) -> dict[str, Any]:
    if min(manual_minutes, assisted_minutes, hourly_cost, compute_cost) < 0:
        raise ValueError("Cost model inputs cannot be negative")
    manual_cost = manual_minutes / 60 * hourly_cost
    assisted_cost = assisted_minutes / 60 * hourly_cost + compute_cost
    savings = manual_cost - assisted_cost
    return {
        "status": "modeled-from-user-supplied-assumptions",
        "observed_human_study": False,
        "assumptions": {
            "manual_minutes": manual_minutes,
            "assisted_minutes": assisted_minutes,
            "reviewer_hourly_cost": hourly_cost,
            "compute_cost": compute_cost,
        },
        "modeled_manual_cost": round(manual_cost, 2),
        "modeled_assisted_cost": round(assisted_cost, 2),
        "modeled_savings": round(savings, 2),
        "modeled_savings_percent": round(100 * savings / manual_cost, 2) if manual_cost else None,
        "note": "These values are a scenario, not an observed outcome. Replace assumptions with signed pilot measurements.",
    }


def run_benchmark(
    incident_count: int = 250,
    noise_count: int = 1000,
    seed: int = 42,
    manual_minutes: float | None = None,
    assisted_minutes: float | None = None,
    hourly_cost: float | None = None,
    compute_cost: float | None = None,
) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    start = time.perf_counter()
    dataset = healthcare_dataset(incident_count, noise_count, seed)
    generation_seconds = time.perf_counter() - start

    start = time.perf_counter()
    clusters = EventCorrelator().correlate(dataset.records)
    correlation_seconds = time.perf_counter() - start

    start = time.perf_counter()
    index = EvidenceIndex(dataset.records)
    indexing_seconds = time.perf_counter() - start
    query_repetitions = 1000
    start = time.perf_counter()
    for query_index in range(query_repetitions):
        index.filter(source=("entra-id", "azure-key-vault", "kubernetes", "github-actions", "azure-sql")[query_index % 5])
    query_seconds = time.perf_counter() - start

    predicted_pairs = pairs(cluster.record_ids for cluster in clusters)
    truth_groups: dict[str, list[str]] = defaultdict(list)
    for record_id, incident_id in dataset.incident_by_record.items():
        truth_groups[incident_id].append(record_id)
    actual_pairs = pairs(truth_groups.values())
    true_positives = len(predicted_pairs & actual_pairs)
    false_positives = len(predicted_pairs - actual_pairs)
    false_negatives = len(actual_pairs - predicted_pairs)
    precision = true_positives / max(1, true_positives + false_positives)
    recall = true_positives / max(1, true_positives + false_negatives)

    signing_key = Ed25519PrivateKey.generate()
    timestamp_key = Ed25519PrivateKey.generate()
    with tempfile.TemporaryDirectory() as temporary_directory:
        pack_path = Path(temporary_directory) / "benchmark.evidence.zip"
        start = time.perf_counter()
        create_evidence_pack(pack_path, dataset.records, (), signing_key, "evidence-core-benchmark", ("benchmark-local-authority", timestamp_key))
        pack_seconds = time.perf_counter() - start
        pack_bytes = pack_path.stat().st_size
        start = time.perf_counter()
        verification = verify_evidence_pack(pack_path, signing_key.public_key(), timestamp_key.public_key())
        verification_seconds = time.perf_counter() - start

    count = len(dataset.records)
    supplied_costs = (manual_minutes, assisted_minutes, hourly_cost, compute_cost)
    if any(value is not None for value in supplied_costs) and not all(value is not None for value in supplied_costs):
        raise ValueError("Provide all four cost-model inputs or none")
    comparison = modeled_cost_comparison(*supplied_costs) if all(value is not None for value in supplied_costs) else {
        "status": "not-provided",
        "observed_human_study": False,
        "note": "Supply explicit assumptions or, preferably, independently observed pilot inputs; no savings claim is made.",
    }
    return {
        "schema_version": "1.0",
        "started_at": started_at,
        "environment": {
            "python": sys.version.split()[0],
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "logical_cpu_count": os.cpu_count(),
        },
        "dataset": {
            "type": "deterministic-synthetic-healthcare-security",
            "contains_phi": False,
            "seed": seed,
            "incident_count": incident_count,
            "noise_count": noise_count,
            "record_count": count,
        },
        "results": {
            "generation_seconds": round(generation_seconds, 6),
            "generation_records_per_second": _rate(count, generation_seconds),
            "correlation_seconds": round(correlation_seconds, 6),
            "correlation_records_per_second": _rate(count, correlation_seconds),
            "indexing_seconds": round(indexing_seconds, 6),
            "indexing_records_per_second": _rate(count, indexing_seconds),
            "indexed_filter_query_count": query_repetitions,
            "indexed_filter_queries_per_second": _rate(query_repetitions, query_seconds),
            "pair_precision": round(precision, 6),
            "pair_recall": round(recall, 6),
            "false_positive_pairs": false_positives,
            "false_negative_pairs": false_negatives,
            "pack_creation_seconds": round(pack_seconds, 6),
            "pack_records_per_second": _rate(count, pack_seconds),
            "pack_bytes": pack_bytes,
            "pack_verification_seconds": round(verification_seconds, 6),
            "verification_records_per_second": _rate(count, verification_seconds),
            "pack_valid": verification.valid,
            "signer_trusted": verification.signer_trusted,
            "timestamp_verified": verification.timestamp_verified,
            "timestamp_trusted": verification.timestamp_trusted,
        },
        "manual_comparison": comparison,
        "environment_note": "Also record physical CPU/RAM, git commit, dependency lock, and exact command when publishing results.",
    }


def write_benchmark(output: str | Path, **options: Any) -> dict[str, Any]:
    result = run_benchmark(**options)
    Path(output).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result
