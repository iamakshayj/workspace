import base64
from datetime import datetime, timedelta, timezone
from hashlib import sha1, sha256
import hmac
import secrets
import struct
import time
from secrets import token_urlsafe

import jwt
from fastapi import Depends, HTTPException, Request, Response, status
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings, get_settings
from .database import AuthSession, Entity, User, get_session


SESSION_COOKIE = "flowforge_session"
ALGORITHM = "HS256"
password_hash = PasswordHash.recommended()
DUMMY_HASH = password_hash.hash("flowforge-dummy-password")


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, encoded_hash: str) -> bool:
    return password_hash.verify(password, encoded_hash)


def create_invitation_token() -> str:
    return token_urlsafe(32)


def hash_invitation_token(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def generate_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def totp_code(secret: str, timestamp: int | None = None) -> str:
    normalized = secret.strip().replace(" ", "").upper()
    padding = "=" * (-len(normalized) % 8)
    key = base64.b32decode(normalized + padding, casefold=True)
    counter = int(timestamp if timestamp is not None else time.time()) // 30
    digest = hmac.new(key, struct.pack(">Q", counter), sha1).digest()
    offset = digest[-1] & 0x0F
    value = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{value:06d}"


def verify_totp(secret: str, code: str, timestamp: int | None = None) -> bool:
    normalized = "".join(character for character in code if character.isdigit())
    if len(normalized) != 6:
        return False
    now = int(timestamp if timestamp is not None else time.time())
    return any(hmac.compare_digest(totp_code(secret, now + offset * 30), normalized) for offset in (-1, 0, 1))


def normalize_recovery_code(code: str) -> str:
    return "".join(character for character in code.upper() if character.isalnum())


def generate_recovery_codes(count: int = 8) -> list[str]:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    codes = []
    for _ in range(count):
        raw = "".join(secrets.choice(alphabet) for _ in range(10))
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes


def recovery_code_hash(user_id: str, code: str) -> str:
    return sha256(f"{user_id}:{normalize_recovery_code(code)}".encode("utf-8")).hexdigest()


def create_session_token(
    user_id: str, settings: Settings, session_id: str | None = None,
    expires_at: datetime | None = None,
) -> str:
    expires_at = expires_at or datetime.now(timezone.utc) + timedelta(days=settings.auth_session_days)
    payload = {"sub": user_id, "exp": expires_at}
    if session_id:
        payload["sid"] = session_id
    return jwt.encode(payload, settings.auth_secret, algorithm=ALGORITHM)


def session_claims(token: str, settings: Settings) -> tuple[str, str | None] | None:
    try:
        payload = jwt.decode(token, settings.auth_secret, algorithms=[ALGORITHM])
    except InvalidTokenError:
        return None
    user_id = payload.get("sub")
    session_id = payload.get("sid")
    if not isinstance(user_id, str) or not user_id:
        return None
    return user_id, session_id if isinstance(session_id, str) and session_id else None


def session_user_id(token: str, settings: Settings) -> str | None:
    claims = session_claims(token, settings)
    return claims[0] if claims else None


async def active_session_user_id(token: str, settings: Settings, session: AsyncSession) -> str | None:
    claims = session_claims(token, settings)
    if not claims:
        return None
    user_id, auth_session_id = claims
    user = await session.get(User, user_id)
    if not user or user.account_status != "active":
        return None
    entity = await session.get(Entity, user.entity_id)
    policy = entity_auth_policy(entity, settings)
    if not auth_session_id:  # Legacy cookies cannot satisfy an enforced MFA assurance level.
        return user_id if authentication_status(user, policy, None) == "compliant" else None
    auth_session = await session.get(AuthSession, auth_session_id)
    now = datetime.now(timezone.utc)
    if (
        not auth_session or auth_session.user_id != user_id or auth_session.revoked_at
        or auth_session.expires_at.replace(tzinfo=auth_session.expires_at.tzinfo or timezone.utc) <= now
        or session_is_idle(auth_session, policy, now)
        or authentication_status(user, policy, auth_session.auth_level) != "compliant"
    ):
        return None
    return user_id


def set_session_cookie(
    response: Response, user_id: str, settings: Settings, session_id: str | None = None,
    expires_at: datetime | None = None,
) -> None:
    effective_expiry = expires_at or datetime.now(timezone.utc) + timedelta(days=settings.auth_session_days)
    max_age = max(1, int((effective_expiry - datetime.now(timezone.utc)).total_seconds()))
    response.set_cookie(
        key=SESSION_COOKIE,
        value=create_session_token(user_id, settings, session_id, effective_expiry),
        max_age=max_age,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/",
    )


def request_ip_digest(request: Request, settings: Settings) -> str:
    address = request.client.host if request.client else "unknown"
    return sha256(f"{settings.auth_secret}:{address}".encode("utf-8")).hexdigest()


async def create_auth_session(
    session: AsyncSession, user: User, request: Request, settings: Settings, auth_level: str = "password",
) -> AuthSession:
    now = datetime.now(timezone.utc)
    entity = await session.get(Entity, user.entity_id)
    policy = entity_auth_policy(entity, settings)
    lifetime_hours = min(policy["session_lifetime_hours"], settings.auth_session_days * 24)
    auth_session = AuthSession(
        user_id=user.id, entity_id=user.entity_id,
        user_agent=(request.headers.get("user-agent") or "Unknown device")[:500],
        ip_digest=request_ip_digest(request, settings),
        auth_level=auth_level,
        created_at=now, last_seen_at=now,
        expires_at=now + timedelta(hours=lifetime_hours),
    )
    session.add(auth_session)
    await session.flush()
    return auth_session


def entity_auth_policy(entity: Entity | None, settings: Settings) -> dict[str, str | int]:
    saved = dict((entity.governance_settings or {}).get("authentication") or {}) if entity else {}
    requirement = saved.get("mfa_requirement", "optional")
    if requirement not in {"optional", "admins", "all"}:
        requirement = "optional"
    def bounded_int(value: object, fallback: int, minimum: int, maximum: int) -> int:
        try:
            return max(minimum, min(maximum, int(value)))
        except (TypeError, ValueError):
            return fallback

    return {
        "mfa_requirement": requirement,
        "session_lifetime_hours": bounded_int(saved.get("session_lifetime_hours"), settings.auth_session_days * 24, 1, 720),
        "idle_timeout_minutes": bounded_int(saved.get("idle_timeout_minutes"), 720, 5, 10_080),
    }


def user_requires_mfa(user: User, policy: dict[str, str | int]) -> bool:
    requirement = policy["mfa_requirement"]
    return requirement == "all" or (requirement == "admins" and user.role == "admin")


def authentication_status(user: User, policy: dict[str, str | int], auth_level: str | None) -> str:
    if not user_requires_mfa(user, policy):
        return "compliant"
    if not user.mfa_enabled:
        return "setup_required"
    return "compliant" if auth_level == "mfa" else "verification_required"


def session_is_idle(auth_session: AuthSession, policy: dict[str, str | int], now: datetime) -> bool:
    last_seen = auth_session.last_seen_at.replace(tzinfo=auth_session.last_seen_at.tzinfo or timezone.utc)
    return last_seen + timedelta(minutes=int(policy["idle_timeout_minutes"])) <= now


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/",
    )


async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
    )
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise credentials_error
    claims = session_claims(token, settings)
    if not claims:
        raise credentials_error
    user_id, auth_session_id = claims

    auth_session = None
    now = datetime.now(timezone.utc)
    if auth_session_id:
        auth_session = await session.get(AuthSession, auth_session_id)
        if (
            not auth_session or auth_session.user_id != user_id or auth_session.revoked_at
            or auth_session.expires_at.replace(tzinfo=auth_session.expires_at.tzinfo or timezone.utc) <= now
        ):
            raise credentials_error

    user = await session.get(User, user_id)
    if not user or user.account_status != "active":
        raise credentials_error
    entity = await session.get(Entity, user.entity_id)
    if not entity or entity.data_region != settings.deployment_region:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This workspace is assigned to a different data-residency deployment",
        )
    policy = entity_auth_policy(entity, settings)
    if auth_session and session_is_idle(auth_session, policy, now):
        auth_session.revoked_at = now
        await session.commit()
        raise credentials_error
    security_status = authentication_status(user, policy, auth_session.auth_level if auth_session else None)
    request.state.auth_session = auth_session
    request.state.auth_policy = policy
    request.state.security_status = security_status
    allowed_during_security_setup = {
        "/auth/me", "/auth/security", "/auth/policy", "/auth/mfa/enroll", "/auth/mfa/confirm",
        "/auth/mfa/step-up", "/auth/logout",
    }
    path = request.url.path
    saml_logout_path = path.endswith("/logout/discover") or path.endswith("/logout/start")
    if security_status != "compliant" and not saml_logout_path and not any(path.endswith(suffix) for suffix in allowed_during_security_setup):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": security_status,
                "message": "Your workspace authentication policy requires an additional security step.",
            },
        )
    if auth_session:
        last_seen = auth_session.last_seen_at.replace(tzinfo=auth_session.last_seen_at.tzinfo or timezone.utc)
        if last_seen < now - timedelta(minutes=5):
            auth_session.last_seen_at = now
            await session.commit()
    return user


async def get_current_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator privileges are required",
        )
    return user
