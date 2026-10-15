"""Creation and verification of frozen evidence-pack archives."""

from __future__ import annotations

import base64
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable
from uuid import uuid4

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .canonical import canonical_json, merkle_root, sha256_bytes, utc_now, isoformat
from .controls import ControlVersion
from .models import EvidenceRecord
from .signing import fingerprint, load_public_key, public_pem, signed_timestamp_receipt, verify_timestamp_receipt


@dataclass(frozen=True, slots=True)
class PackVerification:
    valid: bool
    errors: tuple[str, ...]
    pack_id: str | None
    record_count: int
    signer_fingerprint: str | None
    signer_trusted: bool
    timestamp_verified: bool
    timestamp_trusted: bool


def _safe_path(path: str) -> bool:
    parsed = PurePosixPath(path)
    return bool(path) and not parsed.is_absolute() and ".." not in parsed.parts and "\\" not in path


def _write_entry(archive: zipfile.ZipFile, name: str, content: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    archive.writestr(info, content)


def create_evidence_pack(
    output: str | Path,
    records: Iterable[EvidenceRecord],
    controls: Iterable[ControlVersion],
    signer: Ed25519PrivateKey,
    producer: str,
    timestamp_authority: tuple[str, Ed25519PrivateKey] | None = None,
) -> dict:
    record_items = sorted(records, key=lambda item: item.evidence_id)
    control_items = sorted(controls, key=lambda item: (item.control_id, item.version))
    if not producer.strip():
        raise ValueError("producer is required")
    if len({item.evidence_id for item in record_items}) != len(record_items):
        raise ValueError("Evidence record identifiers must be unique")
    if len({(item.control_id, item.version) for item in control_items}) != len(control_items):
        raise ValueError("Control identifiers and versions must be unique")
    files: dict[str, bytes] = {}
    manifest_records = []
    manifest_controls = []
    for record in record_items:
        path = f"evidence/{record.evidence_id}.json"
        content = canonical_json(record.as_dict())
        files[path] = content
        manifest_records.append({
            "evidence_id": record.evidence_id,
            "path": path,
            "sha256": sha256_bytes(content),
            "source": record.source,
            "kind": record.kind,
            "observed_at": record.as_dict()["observed_at"],
        })
    for control in control_items:
        path = f"controls/{control.control_id}/{control.version}.json"
        content = canonical_json(control.as_dict())
        files[path] = content
        manifest_controls.append({
            "control_id": control.control_id,
            "version": control.version,
            "path": path,
            "sha256": sha256_bytes(content),
            "snapshot_hash": control.snapshot_hash,
        })
    file_hashes = [sha256_bytes(content) for content in files.values()]
    manifest = {
        "format": "verifiable-evidence-pack",
        "format_version": "1.0",
        "pack_id": str(uuid4()),
        "created_at": isoformat(utc_now()),
        "producer": producer,
        "hash_algorithm": "SHA-256",
        "signature_algorithm": "Ed25519",
        "merkle_root": merkle_root(file_hashes),
        "records": manifest_records,
        "controls": manifest_controls,
    }
    manifest_bytes = canonical_json(manifest)
    manifest_hash = sha256_bytes(manifest_bytes)
    signature = signer.sign(manifest_bytes)
    signature_document = {
        "algorithm": "Ed25519",
        "manifest_sha256": manifest_hash,
        "public_key_pem": public_pem(signer.public_key()),
        "signer_fingerprint": fingerprint(signer.public_key()),
        "signature": base64.b64encode(signature).decode("ascii"),
    }
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w") as archive:
        for name in sorted(files):
            _write_entry(archive, name, files[name])
        _write_entry(archive, "manifest.json", manifest_bytes)
        _write_entry(archive, "signature.json", canonical_json(signature_document))
        if timestamp_authority:
            authority, authority_key = timestamp_authority
            receipt = signed_timestamp_receipt(manifest_hash, authority_key, authority)
            _write_entry(archive, "timestamp.json", canonical_json(receipt))
    return manifest


def verify_evidence_pack(
    source: str | Path,
    trusted_signer: Ed25519PublicKey | None = None,
    trusted_timestamp_authority: Ed25519PublicKey | None = None,
    max_files: int = 100_000,
    max_uncompressed_bytes: int = 2 * 1024 * 1024 * 1024,
) -> PackVerification:
    errors: list[str] = []
    pack_id = None
    record_count = 0
    signer_fingerprint = None
    signer_trusted = False
    timestamp_verified = False
    timestamp_trusted = False
    try:
        with zipfile.ZipFile(source, "r") as archive:
            members = archive.infolist()
            if len(members) > max_files:
                raise ValueError(f"Archive exceeds the {max_files} file safety limit")
            if sum(item.file_size for item in members) > max_uncompressed_bytes:
                raise ValueError("Archive exceeds the uncompressed-size safety limit")
            names = [item.filename for item in members]
            if len(names) != len(set(names)):
                errors.append("Archive contains duplicate paths")
            if any(not _safe_path(name) for name in names):
                errors.append("Archive contains an unsafe path")
            if "manifest.json" not in names or "signature.json" not in names:
                errors.append("Manifest or signature is missing")
                raise ValueError(errors[-1])
            manifest_bytes = archive.read("manifest.json")
            manifest = json.loads(manifest_bytes)
            signature_document = json.loads(archive.read("signature.json"))
            if manifest.get("format") != "verifiable-evidence-pack" or manifest.get("format_version") != "1.0":
                errors.append("Unsupported evidence-pack format")
            if manifest.get("hash_algorithm") != "SHA-256" or manifest.get("signature_algorithm") != "Ed25519":
                errors.append("Unsupported manifest algorithm")
            if signature_document.get("algorithm") != "Ed25519":
                errors.append("Unsupported signature algorithm")
            canonical_manifest = canonical_json(manifest)
            if canonical_manifest != manifest_bytes:
                errors.append("Manifest is not canonically encoded")
            manifest_hash = sha256_bytes(canonical_manifest)
            if signature_document.get("manifest_sha256") != manifest_hash:
                errors.append("Signature references a different manifest")
            included_signer = load_public_key(signature_document["public_key_pem"].encode("ascii"))
            signer_fingerprint = fingerprint(included_signer)
            if signature_document.get("signer_fingerprint") != signer_fingerprint:
                errors.append("Signer fingerprint is inconsistent")
            if trusted_signer:
                signer_trusted = fingerprint(trusted_signer) == signer_fingerprint
                if not signer_trusted:
                    errors.append("Pack signer is not trusted")
            try:
                included_signer.verify(base64.b64decode(signature_document["signature"], validate=True), canonical_manifest)
            except (InvalidSignature, ValueError):
                errors.append("Manifest signature is invalid")

            declared = {}
            for item in manifest.get("records", []) + manifest.get("controls", []):
                path = item.get("path", "")
                if not _safe_path(path) or path in declared:
                    errors.append(f"Invalid or duplicate manifest path: {path}")
                    continue
                declared[path] = item.get("sha256")
            expected_names = set(declared) | {"manifest.json", "signature.json"}
            if "timestamp.json" in names:
                expected_names.add("timestamp.json")
            extras = set(names) - expected_names
            missing = expected_names - set(names)
            if extras:
                errors.append(f"Undeclared files: {', '.join(sorted(extras))}")
            if missing:
                errors.append(f"Missing files: {', '.join(sorted(missing))}")
            verified_hashes = []
            for path, expected_hash in declared.items():
                if path not in names:
                    continue
                actual_hash = sha256_bytes(archive.read(path))
                verified_hashes.append(actual_hash)
                if actual_hash != expected_hash:
                    errors.append(f"Hash mismatch: {path}")
            if merkle_root(verified_hashes) != manifest.get("merkle_root"):
                errors.append("Merkle root mismatch")
            if "timestamp.json" in names:
                try:
                    verify_timestamp_receipt(json.loads(archive.read("timestamp.json")), manifest_hash, trusted_timestamp_authority)
                    timestamp_verified = True
                    timestamp_trusted = trusted_timestamp_authority is not None
                except (InvalidSignature, KeyError, TypeError, ValueError) as error:
                    errors.append(f"Timestamp receipt is invalid: {error}")
            pack_id = manifest.get("pack_id")
            record_count = len(manifest.get("records", []))
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        if str(error) not in errors:
            errors.append(f"Pack cannot be verified: {error}")
    return PackVerification(not errors, tuple(errors), pack_id, record_count, signer_fingerprint, signer_trusted, timestamp_verified, timestamp_trusted)
