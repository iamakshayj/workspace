from datetime import datetime, timedelta, timezone

import pytest

from evidence_core import ControlRegistry, ControlVersion, EventCorrelator, EvidenceIndex, EvidenceRecord, LineageGraph
from evidence_core.synthetic import healthcare_dataset, pairs
from evidence_core.benchmark import modeled_cost_comparison


UTC = timezone.utc


def test_control_registry_resolves_time_appropriate_version():
    old = ControlVersion("AC-2", "Example", "1", "Accounts", ("Review",), datetime(2025, 1, 1, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC))
    current = ControlVersion("AC-2", "Example", "2", "Accounts", ("Review quarterly",), datetime(2026, 1, 1, tzinfo=UTC))
    registry = ControlRegistry((old, current))
    assert registry.resolve("AC-2", datetime(2025, 6, 1, tzinfo=UTC)).version == "1"
    assert registry.resolve("AC-2", datetime(2026, 6, 1, tzinfo=UTC)).version == "2"


def test_control_registry_rejects_overlaps():
    registry = ControlRegistry((ControlVersion("A", "F", "1", "A", ("a",), datetime(2025, 1, 1, tzinfo=UTC)),))
    with pytest.raises(ValueError, match="Overlapping"):
        registry.register(ControlVersion("A", "F", "2", "A", ("a",), datetime(2026, 1, 1, tzinfo=UTC)))


def test_lineage_is_bidirectional_and_cycle_safe():
    graph = LineageGraph()
    graph.add("raw", "normalized")
    graph.add("normalized", "finding")
    assert graph.descendants("raw") == {"normalized", "finding"}
    assert graph.ancestors("finding") == {"normalized", "raw"}
    with pytest.raises(ValueError, match="cycle"):
        graph.add("finding", "raw")


def test_correlation_recovers_synthetic_ground_truth_without_false_pairs():
    dataset = healthcare_dataset(8, 20, seed=7)
    clusters = EventCorrelator().correlate(dataset.records)
    predicted = pairs(cluster.record_ids for cluster in clusters)
    labels = {}
    for record_id, incident_id in dataset.incident_by_record.items():
        labels.setdefault(incident_id, []).append(record_id)
    actual = pairs(labels.values())
    assert predicted == actual


def test_records_have_stable_canonical_hashes():
    record = EvidenceRecord("test", "login", datetime(2026, 1, 1, tzinfo=UTC), {"b": 2, "a": 1}, evidence_id="same")
    reordered = EvidenceRecord("test", "login", datetime(2026, 1, 1, tzinfo=UTC), {"a": 1, "b": 2}, evidence_id="same", collected_at=record.collected_at)
    assert record.content_hash == reordered.content_hash


def test_record_rejects_naive_timestamp():
    with pytest.raises(ValueError, match="timezone-aware"):
        EvidenceRecord("test", "login", datetime(2026, 1, 1), {})


def test_index_filters_and_rejects_duplicate_ids():
    dataset = healthcare_dataset(2, 2)
    index = EvidenceIndex(dataset.records)
    assert index.filter(source="entra-id")
    assert all(item.source == "entra-id" for item in index.filter(source="entra-id"))
    assert index.keyword("synthetic")
    with pytest.raises(ValueError, match="Duplicate"):
        index.add(dataset.records[0])


def test_cost_model_is_explicitly_labeled_and_calculated():
    comparison = modeled_cost_comparison(120, 30, 100, 5)
    assert comparison["status"] == "modeled-from-user-supplied-assumptions"
    assert comparison["modeled_manual_cost"] == 200
    assert comparison["modeled_assisted_cost"] == 55
    assert comparison["modeled_savings"] == 145
