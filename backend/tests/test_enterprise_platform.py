import asyncio
from hashlib import sha256

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.app.config import Settings
from backend.app.database import (
    ApiAccessToken,
    Base,
    Entity,
    IntegrationConnection,
    OperationalEvent,
    PolicyRule,
    User,
    WebhookDelivery,
    WebhookSubscription,
)
from backend.app.job_service import stage_webhook_event
from backend.app.platform_admin import (
    DataPolicyWrite,
    DlpSimulation,
    EntitlementWrite,
    IntegrationWrite,
    LegalHoldWrite,
    ObjectiveWrite,
    OperationalEventWrite,
    PolicyRuleWrite,
    SupportAccessWrite,
    TokenWrite,
    WebhookWrite,
    create_api_token,
    create_data_policy,
    create_integration,
    create_legal_hold,
    create_policy,
    record_operational_event,
    request_support_access,
    save_entitlement,
    save_service_objective,
    simulate_dlp,
)


def test_enterprise_platform_controls_persist_without_exposing_secrets() -> None:
    asyncio.run(exercise_platform_controls())


def test_platform_configuration_rejects_unknown_dlp_and_webhook_values() -> None:
    with pytest.raises(ValueError):
        DataPolicyWrite(
            name="Unknown detector", kind="dlp",
            configuration={"detectors": ["magic_detector"]},
        )
    with pytest.raises(ValueError):
        WebhookWrite(
            name="Unsafe event", target_url="https://hooks.example.com/workspace",
            event_types=["project.updated/../../admin"],
        )


async def exercise_platform_controls() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    settings = Settings(auth_secret="enterprise-platform-test-secret-longer-than-thirty-two-bytes")
    async with sessions() as session:
        entity = Entity(id="entity", name="Contoso")
        admin = User(id="admin", entity_id="entity", email="admin@example.com", display_name="Admin", password_hash="x", role="admin")
        session.add_all([entity, admin]); await session.commit()

        policy = await create_policy(PolicyRuleWrite(
            name="Guests cannot export", effect="deny", actions=["export"],
            subject_type="role", subject_id="guest", resource_type="*",
        ), admin, session)
        assert policy["effect"] == "deny"
        assert await session.scalar(select(PolicyRule.id).where(PolicyRule.id == policy["id"]))

        await create_data_policy(DataPolicyWrite(
            name="Sensitive credentials", kind="dlp", applies_to=["assistant"],
            classification="restricted", enforcement="block",
            configuration={"detectors": ["credential"], "blocked_actions": ["ai.send"]},
        ), admin, session)
        dlp = await simulate_dlp(DlpSimulation(
            content="password=do-not-store-this", source_type="assistant", action="ai.send",
        ), admin, session)
        assert dlp["allowed"] is False
        assert "do-not-store-this" not in str(dlp)

        with pytest.raises(HTTPException) as residency_error:
            await create_data_policy(DataPolicyWrite(
                name="EU only", kind="residency", enforcement="block",
                configuration={"allowed_regions": ["eu-west"]},
            ), admin, session)
        assert residency_error.value.status_code == 409
        assert residency_error.value.detail["workspace_region"] == "us-central"

        hold = await create_legal_hold(LegalHoldWrite(
            name="Matter 2026", scope_type="project", scope_id="project-1", reason="Preserve for counsel",
        ), admin, session)
        assert hold["status"] == "active"

        integration = await create_integration(IntegrationWrite(
            name="Calendar", provider="google_calendar", scopes=["calendar.read"],
            credentials={"refresh_token": "never-return-me"}, configuration={"calendar_id": "primary"},
        ), admin, session, settings)
        assert integration["credential_configured"] is True
        assert "never-return-me" not in str(integration)
        saved_integration = await session.get(IntegrationConnection, integration["id"])
        assert saved_integration.credentials_encrypted and "never-return-me" not in saved_integration.credentials_encrypted

        session.add(WebhookSubscription(
            id="webhook", entity_id="entity", name="Lifecycle",
            target_url="https://hooks.example.com/workspace",
            event_types=["project.*"], signing_secret_encrypted="encrypted",
            created_by_id="admin",
        ))
        await session.flush()
        webhook_jobs = await stage_webhook_event(
            session, entity_id="entity", actor_id="admin",
            event_type="project.updated", data={"project_id": "project-1"},
            settings=settings,
        )
        await session.commit()
        assert len(webhook_jobs) == 1
        delivery = await session.scalar(select(WebhookDelivery).where(WebhookDelivery.subscription_id == "webhook"))
        assert delivery.payload["type"] == "project.updated"
        assert delivery.payload["data"] == {"project_id": "project-1"}

        token = await create_api_token(TokenWrite(
            name="Reporting", scopes=["projects:read", "work:read"], expires_in_days=30,
        ), admin, session)
        saved_token = await session.get(ApiAccessToken, token["id"])
        assert saved_token.token_hash == sha256(token["token"].encode()).hexdigest()
        assert token["token"] not in saved_token.token_hash

        support = await request_support_access(SupportAccessWrite(
            requested_for="CASE-2048", reason="Investigate a repeated connector failure",
            scopes=["diagnostics:read"], duration_hours=2,
        ), admin, session)
        assert support["status"] == "pending"

        entitlement = await save_entitlement("semantic_search", EntitlementWrite(
            enabled=True, limit_value=500_000,
        ), admin, session)
        assert entitlement["limit_value"] == 500_000

        objective = await save_service_objective("api", "availability", ObjectiveWrite(
            service="api", metric="availability", target=99.9, window_days=30,
        ), admin, session)
        assert objective["target"] == 99.9

        first = await record_operational_event(OperationalEventWrite(
            service="search", fingerprint="search-timeout", message="Search timed out",
            context={"route": "/search", "token": "must-be-scrubbed"},
        ), admin, session)
        second = await record_operational_event(OperationalEventWrite(
            service="search", fingerprint="search-timeout", message="Search timed out again",
            context={"route": "/search"},
        ), admin, session)
        assert first["id"] == second["id"]
        event = await session.get(OperationalEvent, first["id"])
        assert event.occurrence_count == 2
        assert "token" not in event.context

    await engine.dispose()
