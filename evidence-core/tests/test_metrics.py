import json

from evidence_core import ImpactLedger


def test_impact_ledger_detects_tampering(tmp_path):
    path = tmp_path / "metrics.jsonl"
    ledger = ImpactLedger(path)
    ledger.append("evidence_records_processed", 10, "benchmark", "file://result.json")
    ledger.append("audit_hours_saved", 2, "signed-pilot-report", "https://example.invalid/report")
    assert ledger.verify() == (True, None)
    assert ledger.totals()["evidence_records_processed"] == 10
    entries = ledger.entries()
    entries[0]["value"] = 999
    path.write_text("\n".join(json.dumps(entry) for entry in entries) + "\n")
    assert ledger.verify()[0] is False
