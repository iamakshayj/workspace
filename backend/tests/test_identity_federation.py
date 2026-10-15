import asyncio

from fastapi import HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.requests import Request

from backend.app.auth import hash_password
from backend.app.auth_routes import login
from backend.app.config import Settings
from backend.app.database import Base, Entity, IdentityProviderDomain, OrganizationUnit, ScimAccessToken, User
from backend.app.identity_federation import (
    DomainWrite, EmailDiscovery, ProviderWrite, ScimTokenWrite, create_domain_challenge,
    create_provider, create_scim_group, create_scim_token, create_scim_user, discover_sso,
    list_scim_groups, list_scim_users, patch_scim_user, revoke_scim_token, scim_context,
    update_provider,
)
from backend.app.schemas import LoginRequest


def request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/api/v1/auth/login", "headers": [(b"user-agent", b"Federation test")],
                    "client": ("127.0.0.1", 45000), "server": ("test", 80), "scheme": "http", "query_string": b""})


def test_oidc_configuration_sso_enforcement_and_scim_lifecycle() -> None:
    asyncio.run(exercise_identity_federation())


async def exercise_identity_federation() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    settings = Settings(auth_secret="federation-test-secret-that-is-longer-than-thirty-two-bytes")

    async with sessions() as session:
        entity = Entity(id="11111111-1111-1111-1111-111111111111", name="Acme")
        admin = User(id="22222222-2222-2222-2222-222222222222", entity_id=entity.id, email="admin@acme.test",
                     display_name="Admin", password_hash=hash_password("SecurePass123!"), role="admin")
        member = User(id="33333333-3333-3333-3333-333333333333", entity_id=entity.id, email="member@acme.test",
                      display_name="Member", password_hash=hash_password("SecurePass123!"), role="basic")
        session.add_all([entity, admin, member]); await session.commit()

        provider = await create_provider(ProviderWrite(name="Acme Identity", issuer_url="https://login.acme.test",
            client_id="workspace-client", client_secret="super-secret", enabled=True), admin, session, settings)
        assert provider["has_client_secret"] is True
        challenge = await create_domain_challenge(provider["id"], DomainWrite(domain="acme.test"), admin, session)
        assert challenge["challenge_token"].startswith("workspace-domain=")
        domain = await session.scalar(select(IdentityProviderDomain).where(IdentityProviderDomain.domain == "acme.test"))
        domain.status = "verified"; await session.commit()

        configured = await update_provider(provider["id"], ProviderWrite(name="Acme Identity", issuer_url="https://login.acme.test",
            client_id="workspace-client", enabled=True, enforce_sso=True, jit_enabled=True), admin, session, settings)
        assert configured["enforce_sso"] is True
        discovery = await discover_sso(EmailDiscovery(email="anyone@acme.test"), session)
        assert discovery["available"] is True
        assert discovery["provider_id"] == provider["id"]

        try:
            await login(LoginRequest(email=member.email, password="SecurePass123!"), request(), Response(), session, settings)
            raise AssertionError("Password login bypassed an enforced SSO provider")
        except HTTPException as error:
            assert error.status_code == 403
            assert error.detail["code"] == "sso_required"

        created_token = await create_scim_token(ScimTokenWrite(name="Test provisioning", expires_in_days=30), admin, session)
        assert created_token["token"].startswith("wss_scim_")
        stored = await session.get(ScimAccessToken, created_token["id"])
        assert stored.token_hash != created_token["token"]
        context = await scim_context(f"Bearer {created_token['token']}", session)

        provisioned = await create_scim_user({"userName": "new.user@acme.test", "displayName": "New User", "active": True}, context)
        assert provisioned["active"] is True
        listing = await list_scim_users(1, 100, 'userName eq "new.user@acme.test"', context)
        assert listing["totalResults"] == 1
        assert listing["Resources"][0]["id"] == provisioned["id"]
        suspended = await patch_scim_user(provisioned["id"], {"Operations": [{"op": "Replace", "path": "active", "value": False}]}, context)
        assert suspended["active"] is False

        group = await create_scim_group({"displayName": "Platform Team", "members": [{"value": provisioned["id"]}]}, context)
        assert group["members"][0]["value"] == provisioned["id"]
        groups = await list_scim_groups(context)
        assert groups["totalResults"] == 1
        assert (await session.get(OrganizationUnit, group["id"])).unit_type == "group"

        await revoke_scim_token(created_token["id"], admin, session)
        try:
            await scim_context(f"Bearer {created_token['token']}", session)
            raise AssertionError("A revoked SCIM token was accepted")
        except HTTPException as error:
            assert error.status_code == 401

    await engine.dispose()
