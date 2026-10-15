import json

from evidence_core.cli import main


def test_normalize_jsonl_command(tmp_path):
    source = tmp_path / "audit.jsonl"
    target = tmp_path / "normalized.jsonl"
    source.write_text(json.dumps({"auditID": "a1", "stageTimestamp": "2026-01-01T10:00:00Z", "verb": "get"}) + "\n")
    assert main(["normalize", "--source", "kubernetes", "--input", str(source), "--output", str(target)]) == 0
    result = json.loads(target.read_text())
    assert result["source"] == "kubernetes"
    assert result["kind"] == "kubernetes.get"
