import asyncio
from http.cookies import SimpleCookie

from fastapi import HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.requests import Request

from backend.app.auth import SESSION_COOKIE, get_current_user, hash_password, session_claims, totp_code
from backend.app.auth_routes import (
    confirm_mfa, enroll_mfa, login, revoke_other_sessions, security_summary,
    update_authentication_policy,
)
from backend.app.config import Settings
from backend.app.database import AuthSession, Base, Entity, User
from backend.app.schemas import AuthenticationPolicyWrite, LoginRequest, MfaCodeRequest, MfaEnrollRequest


def make_request(cookie: str = "", user_agent: str = "Workspace test browser", path: str = "/api/v1/auth/login") -> Request:
    headers = [(b"user-agent", user_agent.encode())]
    if cookie:
        headers.append((b"cookie", f"{SESSION_COOKIE}={cookie}".encode()))
    return Request({
        "type": "http",
        "method": "POST",
        "path": path,
        "headers": headers,
        "client": ("127.0.0.1", 44000),
        "server": ("test", 80),
        "scheme": "http",
        "query_string": b"",
    })


def response_cookie(response: Response) -> str:
    cookies = SimpleCookie()
    cookies.load(response.headers["set-cookie"])
    return cookies[SESSION_COOKIE].value


def test_managed_sessions_and_mfa_lifecycle() -> None:
    asyncio.run(exercise_managed_sessions_and_mfa())


async def exercise_managed_sessions_and_mfa() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    settings = Settings(
        auth_secret="identity-test-secret-that-is-longer-than-thirty-two-bytes",
        auth_session_days=2,
    )
    async with sessions() as session:
        entity = Entity(id="11111111-1111-1111-1111-111111111111", name="Northwind")
        user = User(
            id="22222222-2222-2222-2222-222222222222",
            entity_id=entity.id,
            email="owner@example.com",
            display_name="Workspace Owner",
            password_hash=hash_password("SecurePass123!"),
            role="admin",
        )
        session.add_all([entity, user])
        await session.commit()

        response = Response()
        await login(
            LoginRequest(email=user.email, password="SecurePass123!"),
            make_request(user_agent="Chrome on Macintosh"), response, session, settings,
        )
        cookie = response_cookie(response)
        claims = session_claims(cookie, settings)
        assert claims and claims[0] == user.id and claims[1]
        managed_session = await session.get(AuthSession, claims[1])
        assert managed_session and managed_session.user_agent == "Chrome on Macintosh"
        assert managed_session.ip_digest != "127.0.0.1"

        enrollment = await enroll_mfa(MfaEnrollRequest(password="SecurePass123!"), user, session, settings)
        enrollment_request = make_request(cookie, path="/api/v1/auth/mfa/confirm")
        enrollment_request.state.auth_session = managed_session
        result = await confirm_mfa(
            MfaCodeRequest(code=totp_code(enrollment["secret"])), enrollment_request, user, session, settings,
        )
        assert result["mfa_enabled"] is True
        assert len(result["recovery_codes"]) == 8
        assert user.mfa_enabled is True
        assert len(user.mfa_recovery_hashes) == 8
        assert all(item not in user.mfa_recovery_hashes for item in result["recovery_codes"])

        try:
            await login(
                LoginRequest(email=user.email, password="SecurePass123!"),
                make_request(), Response(), session, settings,
            )
            raise AssertionError("MFA-protected login unexpectedly succeeded without a code")
        except HTTPException as error:
            assert error.status_code == 428

        second_response = Response()
        await login(
            LoginRequest(
                email=user.email, password="SecurePass123!", mfa_code=totp_code(enrollment["secret"]),
            ),
            make_request(user_agent="Firefox on Linux"), second_response, session, settings,
        )
        second_cookie = response_cookie(second_response)
        second_claims = session_claims(second_cookie, settings)
        assert second_claims and second_claims[1] != claims[1]

        policy = await update_authentication_policy(
            AuthenticationPolicyWrite(mfa_requirement="all", session_lifetime_hours=24, idle_timeout_minutes=30),
            user, session, settings,
        )
        assert policy["policy"]["mfa_requirement"] == "all"
        assert policy["compliance"]["required_users"] == 1
        assert policy["compliance"]["required_not_enrolled"] == []
        managed_session.auth_level = "password"
        await session.commit()
        setup_request = make_request(cookie, path="/api/v1/auth/me")
        assert (await get_current_user(setup_request, session, settings)).id == user.id
        assert setup_request.state.security_status == "verification_required"
        try:
            await get_current_user(make_request(cookie, path="/api/v1/projects"), session, settings)
            raise AssertionError("A password-only session bypassed the enforced MFA policy")
        except HTTPException as error:
            assert error.status_code == 403
            assert error.detail["code"] == "verification_required"
        assert (await get_current_user(make_request(second_cookie, path="/api/v1/projects"), session, settings)).id == user.id

        summary = await security_summary(make_request(second_cookie), user, session, settings)
        assert summary["mfa_enabled"] is True
        assert len(summary["sessions"]) == 2
        assert sum(item["current"] for item in summary["sessions"]) == 1

        revoked = await revoke_other_sessions(make_request(second_cookie), user, session, settings)
        assert revoked == {"revoked": 1}
        active = (await session.scalars(select(AuthSession).where(AuthSession.revoked_at.is_(None)))).all()
        assert [item.id for item in active] == [second_claims[1]]

    await engine.dispose()
