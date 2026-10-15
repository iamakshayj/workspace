import jwt
import pytest
from pydantic import ValidationError

from backend.app.auth import (
    ALGORITHM,
    create_invitation_token,
    create_session_token,
    generate_recovery_codes,
    generate_totp_secret,
    hash_invitation_token,
    hash_password,
    recovery_code_hash,
    session_claims,
    totp_code,
    verify_totp,
    verify_password,
)
from backend.app.config import Settings
from backend.app.schemas import InternalAdminCreate, LoginRequest


def test_passwords_are_argon2_hashed_and_verifiable() -> None:
    encoded = hash_password("SecurePass123!")

    assert encoded.startswith("$argon2")
    assert "SecurePass123!" not in encoded
    assert verify_password("SecurePass123!", encoded)
    assert not verify_password("incorrect", encoded)


def test_session_token_is_signed_for_the_user() -> None:
    settings = Settings(
        auth_secret="test-only-secret-that-is-longer-than-thirty-two-bytes",
        auth_session_days=1,
    )
    token = create_session_token("user-123", settings)
    payload = jwt.decode(token, settings.auth_secret, algorithms=[ALGORITHM])

    assert payload["sub"] == "user-123"
    assert "exp" in payload
    assert session_claims(token, settings) == ("user-123", None)

    managed_token = create_session_token("user-123", settings, "session-456")
    assert session_claims(managed_token, settings) == ("user-123", "session-456")


def test_totp_and_recovery_codes_are_validated_without_storing_plaintext() -> None:
    timestamp = 1_800_000_000
    secret = generate_totp_secret()
    code = totp_code(secret, timestamp)

    assert verify_totp(secret, code, timestamp)
    assert verify_totp(secret, totp_code(secret, timestamp - 30), timestamp)
    assert not verify_totp(secret, "not-a-code", timestamp)

    recovery_codes = generate_recovery_codes()
    assert len(recovery_codes) == 8
    assert len(set(recovery_codes)) == 8
    assert all(len(item) == 11 and item[5] == "-" for item in recovery_codes)
    assert recovery_code_hash("user-123", recovery_codes[0]) == recovery_code_hash(
        "user-123", recovery_codes[0].lower().replace("-", " ")
    )


def test_auth_payloads_normalize_email_addresses() -> None:
    registration = InternalAdminCreate(
        display_name="  FlowForge Owner  ",
        email="  OWNER@Example.COM ",
        password="SecurePass123!",
    )
    login = LoginRequest(email=" OWNER@Example.COM ", password="SecurePass123!")

    assert registration.display_name == "FlowForge Owner"
    assert registration.email == "owner@example.com"
    assert login.email == "owner@example.com"


def test_invitation_tokens_are_random_and_only_hashes_need_storage() -> None:
    first = create_invitation_token()
    second = create_invitation_token()

    assert first != second
    assert len(first) >= 40
    assert hash_invitation_token(first) != first
    assert len(hash_invitation_token(first)) == 64


def test_production_configuration_rejects_development_defaults() -> None:
    with pytest.raises(ValidationError, match="Invalid production configuration"):
        Settings(environment="production")


def test_production_configuration_accepts_secure_service_settings() -> None:
    settings = Settings(
        environment="production",
        auth_secret="a" * 64,
        internal_api_key="b" * 64,
        metrics_api_key="d" * 64,
        model_api_token="c" * 32,
        auth_cookie_secure=True,
        database_url="postgresql+asyncpg://flowforge:secret@postgres/flowforge",
        redis_url="redis://:secret@redis:6379/0",
        embedded_worker_enabled=False,
        storage_backend="s3",
        storage_public_endpoint_url="https://storage.flowforge.example.com",
        attachment_scan_mode="clamav",
        clamav_host="clamav",
        frontend_url="https://flowforge.example.com",
        cors_origins=["https://flowforge.example.com"],
        email_delivery_mode="smtp",
        smtp_host="smtp.example.com",
    )

    assert settings.environment == "production"
