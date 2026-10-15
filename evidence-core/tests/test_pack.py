import json
import zipfile
from datetime import datetime, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from evidence_core import ControlVersion, EvidenceRecord, create_evidence_pack, verify_evidence_pack


def _fixture():
    moment = datetime(2026, 1, 1, tzinfo=timezone.utc)
    record = EvidenceRecord("test", "audit", moment, {"result": "success"}, evidence_id="record-1")
    control = ControlVersion("AU-1", "Example", "1", "Audit", ("Collect events",), moment)
    return record, control


def test_pack_signature_hashes_and_timestamp_verify(tmp_path):
    record, control = _fixture()
    signer = Ed25519PrivateKey.generate()
    timestamp_authority = Ed25519PrivateKey.generate()
    pack = tmp_path / "evidence.zip"
    create_evidence_pack(pack, (record,), (control,), signer, "pytest", ("test-authority", timestamp_authority))
    result = verify_evidence_pack(pack, signer.public_key(), timestamp_authority.public_key())
    assert result.valid
    assert result.record_count == 1
    assert result.signer_trusted
    assert result.timestamp_verified
    assert result.timestamp_trusted


def test_embedded_timestamp_can_verify_without_being_trusted(tmp_path):
    record, control = _fixture()
    signer = Ed25519PrivateKey.generate()
    timestamp_authority = Ed25519PrivateKey.generate()
    pack = tmp_path / "evidence.zip"
    create_evidence_pack(pack, (record,), (control,), signer, "pytest", ("untrusted-test-authority", timestamp_authority))
    result = verify_evidence_pack(pack, signer.public_key())
    assert result.valid
    assert result.timestamp_verified
    assert not result.timestamp_trusted


def test_modified_evidence_is_detected(tmp_path):
    record, control = _fixture()
    signer = Ed25519PrivateKey.generate()
    original = tmp_path / "original.zip"
    tampered = tmp_path / "tampered.zip"
    create_evidence_pack(original, (record,), (control,), signer, "pytest")
    with zipfile.ZipFile(original) as source, zipfile.ZipFile(tampered, "w") as target:
        for entry in source.infolist():
            content = source.read(entry.filename)
            if entry.filename == "evidence/record-1.json":
                payload = json.loads(content)
                payload["payload"]["result"] = "tampered"
                content = json.dumps(payload).encode()
            target.writestr(entry, content)
    result = verify_evidence_pack(tampered, signer.public_key())
    assert not result.valid
    assert any("Hash mismatch" in error for error in result.errors)
    assert any("Merkle root mismatch" in error for error in result.errors)


def test_untrusted_signer_is_rejected(tmp_path):
    record, control = _fixture()
    pack = tmp_path / "evidence.zip"
    create_evidence_pack(pack, (record,), (control,), Ed25519PrivateKey.generate(), "pytest")
    result = verify_evidence_pack(pack, Ed25519PrivateKey.generate().public_key())
    assert not result.valid
    assert "Pack signer is not trusted" in result.errors


def test_pack_creation_rejects_duplicate_record_ids(tmp_path):
    record, control = _fixture()
    with pytest.raises(ValueError, match="unique"):
        create_evidence_pack(tmp_path / "duplicate.zip", (record, record), (control,), Ed25519PrivateKey.generate(), "pytest")
