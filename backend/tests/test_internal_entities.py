import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from backend.app.config import Settings
from backend.app.internal_routes import require_internal_key
from backend.app.schemas import InternalAdminCreate, InternalEntityCreate, InternalEntityUpdate


def test_internal_entity_api_requires_the_platform_owner_key() -> None:
    settings = Settings(internal_api_key="test-owner-key-with-sufficient-entropy")

    with pytest.raises(HTTPException) as missing_error:
        require_internal_key(None, settings)
    with pytest.raises(HTTPException) as invalid_error:
        require_internal_key("wrong-key", settings)

    assert missing_error.value.status_code == 401
    assert invalid_error.value.status_code == 401
    assert require_internal_key("test-owner-key-with-sufficient-entropy", settings) is None


def test_internal_entity_requires_at_least_one_admin() -> None:
    with pytest.raises(ValidationError, match="at least 1 item"):
        InternalEntityCreate(name="Northwind Operations", admins=[])


def test_internal_entity_rejects_duplicate_admin_emails() -> None:
    admin = InternalAdminCreate(
        display_name="Avery Admin",
        email="avery@northwind.example",
        password="SecureInitialPass123!",
    )

    with pytest.raises(ValidationError, match="Admin email addresses must be unique"):
        InternalEntityCreate(name="Northwind Operations", admins=[admin, admin])


def test_internal_entity_accepts_only_supported_residency_regions() -> None:
    admin = InternalAdminCreate(
        display_name="Avery Admin", email="avery@northwind.example",
        password="SecureInitialPass123!",
    )
    entity = InternalEntityCreate(
        name="Northwind Operations", admins=[admin], data_region="eu-west",
        data_residency_locked=True,
    )
    assert entity.data_region == "eu-west"
    assert entity.data_residency_locked is True
    with pytest.raises(ValidationError):
        InternalEntityUpdate(data_region="moon-base")
