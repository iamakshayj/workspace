"""Ed25519 signing and timestamp receipt helpers."""

from __future__ import annotations

import base64
from datetime import datetime
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .canonical import canonical_json, isoformat, sha256_bytes, utc_now


def generate_keypair(private_path: str | Path, public_path: str | Path) -> None:
    private_key = Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_bytes = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    private_target, public_target = Path(private_path), Path(public_path)
    private_target.parent.mkdir(parents=True, exist_ok=True)
    public_target.parent.mkdir(parents=True, exist_ok=True)
    private_target.write_bytes(private_bytes)
    private_target.chmod(0o600)
    public_target.write_bytes(public_bytes)


def load_private_key(value: str | Path | bytes) -> Ed25519PrivateKey:
    raw = value if isinstance(value, bytes) else Path(value).read_bytes()
    key = serialization.load_pem_private_key(raw, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise TypeError("An Ed25519 private key is required")
    return key


def load_public_key(value: str | Path | bytes) -> Ed25519PublicKey:
    raw = value if isinstance(value, bytes) else Path(value).read_bytes()
    key = serialization.load_pem_public_key(raw)
    if not isinstance(key, Ed25519PublicKey):
        raise TypeError("An Ed25519 public key is required")
    return key


def public_pem(key: Ed25519PublicKey) -> str:
    return key.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode("ascii")


def fingerprint(key: Ed25519PublicKey) -> str:
    raw = key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return f"SHA256:{sha256_bytes(raw)}"


def signed_timestamp_receipt(
    manifest_sha256: str,
    authority_private_key: Ed25519PrivateKey,
    authority: str,
    issued_at: datetime | None = None,
) -> dict[str, Any]:
    payload = {
        "version": "1",
        "authority": authority,
        "issued_at": isoformat(issued_at or utc_now()),
        "manifest_sha256": manifest_sha256,
    }
    signature = authority_private_key.sign(canonical_json(payload))
    return {
        "payload": payload,
        "algorithm": "Ed25519",
        "public_key_pem": public_pem(authority_private_key.public_key()),
        "authority_fingerprint": fingerprint(authority_private_key.public_key()),
        "signature": base64.b64encode(signature).decode("ascii"),
    }


def verify_timestamp_receipt(receipt: dict[str, Any], manifest_sha256: str, trusted_key: Ed25519PublicKey | None = None) -> None:
    if receipt.get("algorithm") != "Ed25519" or receipt.get("payload", {}).get("manifest_sha256") != manifest_sha256:
        raise ValueError("Timestamp receipt does not reference this manifest")
    included = load_public_key(receipt["public_key_pem"].encode("ascii"))
    if not receipt.get("payload", {}).get("authority"):
        raise ValueError("Timestamp authority name is missing")
    issued_at = datetime.fromisoformat(str(receipt["payload"]["issued_at"]).replace("Z", "+00:00"))
    if issued_at.tzinfo is None:
        raise ValueError("Timestamp must be timezone-aware")
    if trusted_key and fingerprint(included) != fingerprint(trusted_key):
        raise ValueError("Timestamp authority key is not trusted")
    included.verify(base64.b64decode(receipt["signature"], validate=True), canonical_json(receipt["payload"]))
