from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import (
    DUMMY_HASH,
    authentication_status,
    clear_session_cookie,
    create_auth_session,
    entity_auth_policy,
    generate_recovery_codes,
    generate_totp_secret,
    get_current_user,
    get_current_admin,
    hash_invitation_token,
    hash_password,
    recovery_code_hash,
    session_claims,
    set_session_cookie,
    user_requires_mfa,
    verify_totp,
    verify_password,
)
from .config import Settings, get_settings
from .database import AuthSession, Entity, IdentityProvider, IdentityProviderDomain, Invitation, User, get_session
from .governance import record_audit_event
from .identity import as_utc
from .quota_service import ensure_user_capacity
from .schemas import (
    AcceptInvitationRequest,
    AuthenticationPolicyWrite,
    InvitationPreview,
    LoginRequest,
    MfaCodeRequest,
    MfaDisableRequest,
    MfaEnrollRequest,
    ProfileUpdate,
    UserResponse,
)
from .secret_box import SecretBox, SecretBoxError


router = APIRouter(prefix="/auth", tags=["auth"])


async def serialize_user(
    user: User, session: AsyncSession, settings: Settings,
    auth_session: AuthSession | None = None,
) -> UserResponse:
    entity = await session.get(Entity, user.entity_id)
    if not entity:
        raise HTTPException(status_code=500, detail="The account entity could not be loaded")
    policy = entity_auth_policy(entity, settings)
    return UserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        entity_id=user.entity_id,
        entity_name=entity.name,
        role=user.role,
        created_at=as_utc(user.created_at),
        mfa_enabled=user.mfa_enabled,
        mfa_required=user_requires_mfa(user, policy),
        security_status=authentication_status(user, policy, auth_session.auth_level if auth_session else None),
    )


def verify_user_mfa_code(user: User, code: str, settings: Settings) -> bool:
    try:
        secret = SecretBox(settings.auth_secret).decrypt(user.mfa_secret_encrypted or "", f"mfa:{user.id}")
    except SecretBoxError as error:
        raise HTTPException(status_code=500, detail="Multi-factor authentication is unavailable") from error
    if verify_totp(secret, code):
        return True
    candidate = recovery_code_hash(user.id, code)
    recovery_hashes = list(user.mfa_recovery_hashes or [])
    if candidate not in recovery_hashes:
        return False
    recovery_hashes.remove(candidate)
    user.mfa_recovery_hashes = recovery_hashes
    return True


def invitation_is_active(invitation: Invitation) -> bool:
    expires_at = invitation.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return invitation.status == "pending" and expires_at > datetime.now(timezone.utc)


async def active_invitation(token: str, session: AsyncSession) -> Invitation:
    invitation = await session.scalar(
        select(Invitation).where(Invitation.token_hash == hash_invitation_token(token))
    )
    if not invitation or not invitation_is_active(invitation):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This invitation is invalid or has expired",
        )
    return invitation


@router.post("/login", response_model=UserResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> UserResponse:
    user = await session.scalar(select(User).where(User.email == payload.email).with_for_update())
    encoded_hash = user.password_hash if user else DUMMY_HASH
    password_valid = verify_password(payload.password, encoded_hash)
    if not user or not password_valid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")
    if user.account_status != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account is suspended")
    email_domain = user.email.rsplit("@", 1)[-1]
    enforced_provider = await session.scalar(select(IdentityProvider).join(IdentityProviderDomain).where(
        IdentityProvider.entity_id == user.entity_id,
        IdentityProvider.enabled.is_(True),
        IdentityProvider.enforce_sso.is_(True),
        IdentityProviderDomain.domain == email_domain,
        IdentityProviderDomain.status == "verified",
    ))
    if enforced_provider and not (user.role == "admin" and enforced_provider.allow_admin_password_fallback):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={
            "code": "sso_required", "message": f"Continue with {enforced_provider.name} to access this workspace.",
            "provider_id": enforced_provider.id, "provider_name": enforced_provider.name,
            "login_url": f"/api/v1/auth/sso/{enforced_provider.id}/start",
        })
    if user.mfa_enabled:
        if not payload.mfa_code:
            raise HTTPException(status_code=status.HTTP_428_PRECONDITION_REQUIRED, detail="Verification code required")
        if not verify_user_mfa_code(user, payload.mfa_code, settings):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid verification code")
    auth_session = await create_auth_session(
        session, user, request, settings, auth_level="mfa" if user.mfa_enabled else "password",
    )
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="auth.session.created",
                       target_type="user", target_id=user.id, details={"session_id": auth_session.id})
    await session.commit()
    set_session_cookie(response, user.id, settings, auth_session.id, as_utc(auth_session.expires_at))
    return await serialize_user(user, session, settings, auth_session)


@router.get("/me", response_model=UserResponse)
async def get_me(
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> UserResponse:
    return await serialize_user(user, session, settings, getattr(request.state, "auth_session", None))


@router.put("/me", response_model=UserResponse)
async def update_me(
    payload: ProfileUpdate,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> UserResponse:
    if payload.email != user.email:
        existing = await session.scalar(select(User).where(User.email == payload.email))
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account already uses this email")
    user.email = payload.email
    user.display_name = payload.display_name
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account already uses this email") from error
    await session.refresh(user)
    return await serialize_user(user, session, settings, getattr(request.state, "auth_session", None))


@router.get("/invitations/{token}", response_model=InvitationPreview)
async def get_invitation(
    token: str,
    session: AsyncSession = Depends(get_session),
) -> InvitationPreview:
    invitation = await active_invitation(token, session)
    entity = await session.get(Entity, invitation.entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="The invitation entity could not be loaded")
    return InvitationPreview(
        email=invitation.email,
        display_name=invitation.display_name,
        entity_name=entity.name,
        role=invitation.role,
        expires_at=as_utc(invitation.expires_at),
    )


@router.post("/invitations/accept", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def accept_invitation(
    payload: AcceptInvitationRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> UserResponse:
    invitation = await active_invitation(payload.token, session)
    existing = await session.scalar(select(User).where(User.email == invitation.email))
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account already uses this email",
        )
    await ensure_user_capacity(
        session,
        invitation.entity_id,
        additional_reserved_seats=0,
    )

    user = User(
        email=invitation.email,
        display_name=invitation.display_name,
        password_hash=hash_password(payload.password),
        entity_id=invitation.entity_id,
        role=invitation.role,
    )
    session.add(user)
    try:
        await session.flush()
        invitation.status = "accepted"
        invitation.accepted_user_id = user.id
        auth_session = await create_auth_session(session, user, request, settings, auth_level="password")
        record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="auth.session.created",
                           target_type="user", target_id=user.id, details={"session_id": auth_session.id})
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This invitation can no longer be accepted",
        ) from error
    await session.refresh(user)
    set_session_cookie(response, user.id, settings, auth_session.id, as_utc(auth_session.expires_at))
    return await serialize_user(user, session, settings, auth_session)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request, session: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings),
) -> Response:
    token = request.cookies.get("flowforge_session")
    claims = session_claims(token, settings) if token else None
    if claims and claims[1]:
        auth_session = await session.get(AuthSession, claims[1])
        if auth_session and auth_session.user_id == claims[0] and not auth_session.revoked_at:
            auth_session.revoked_at = datetime.now(timezone.utc)
            record_audit_event(session, entity_id=auth_session.entity_id, actor_id=auth_session.user_id,
                               action="auth.session.revoked", target_type="user", target_id=auth_session.user_id,
                               details={"session_id": auth_session.id, "reason": "logout"})
            await session.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookie(response, settings)
    return response


def current_session_id(request: Request, settings: Settings) -> str | None:
    token = request.cookies.get("flowforge_session")
    claims = session_claims(token, settings) if token else None
    return claims[1] if claims else None


def device_name(user_agent: str) -> str:
    browser = "Browser"
    for marker, label in (("Edg/", "Edge"), ("Chrome/", "Chrome"), ("Firefox/", "Firefox"), ("Safari/", "Safari")):
        if marker in user_agent:
            browser = label
            break
    system = next((label for marker, label in (("Windows", "Windows"), ("Macintosh", "macOS"), ("Android", "Android"), ("iPhone", "iPhone"), ("Linux", "Linux")) if marker in user_agent), "Unknown device")
    return f"{browser} on {system}"


def serialize_auth_session(item: AuthSession, current_id: str | None) -> dict:
    return {
        "id": item.id, "device": device_name(item.user_agent), "current": item.id == current_id,
        "auth_level": item.auth_level,
        "created_at": item.created_at.isoformat(), "last_seen_at": item.last_seen_at.isoformat(),
        "expires_at": item.expires_at.isoformat(), "revoked_at": item.revoked_at.isoformat() if item.revoked_at else None,
    }


@router.get("/security")
async def security_summary(
    request: Request, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    now = datetime.now(timezone.utc)
    sessions = (await session.scalars(select(AuthSession).where(
        AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None), AuthSession.expires_at > now,
    ).order_by(AuthSession.created_at.desc()).limit(100))).all()
    return {
        "mfa_enabled": user.mfa_enabled,
        "recovery_codes_remaining": len(user.mfa_recovery_hashes or []),
        "sessions": [serialize_auth_session(item, current_session_id(request, settings)) for item in sessions],
        "legacy_session": current_session_id(request, settings) is None,
        "authentication_policy": entity_auth_policy(await session.get(Entity, user.entity_id), settings),
        "security_status": getattr(request.state, "security_status", "compliant"),
    }


async def authentication_policy_response(user: User, session: AsyncSession, settings: Settings) -> dict:
    entity = await session.get(Entity, user.entity_id)
    policy = entity_auth_policy(entity, settings)
    response = {"policy": policy, "required_for_current_user": user_requires_mfa(user, policy)}
    if user.role == "admin":
        members = (await session.scalars(select(User).where(User.entity_id == user.entity_id))).all()
        required = [member for member in members if user_requires_mfa(member, policy)]
        response["compliance"] = {
            "total_users": len(members),
            "required_users": len(required),
            "enrolled_users": sum(member.mfa_enabled for member in members),
            "required_not_enrolled": [
                {"id": member.id, "display_name": member.display_name, "email": member.email, "role": member.role}
                for member in required if not member.mfa_enabled
            ][:100],
        }
    return response


@router.get("/policy")
async def get_authentication_policy(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    return await authentication_policy_response(user, session, settings)


@router.put("/policy")
async def update_authentication_policy(
    payload: AuthenticationPolicyWrite, user: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings),
) -> dict:
    entity = await session.get(Entity, user.entity_id)
    governance = dict(entity.governance_settings or {})
    previous = entity_auth_policy(entity, settings)
    governance["authentication"] = payload.model_dump()
    entity.governance_settings = governance
    deadline = datetime.now(timezone.utc) + timedelta(hours=payload.session_lifetime_hours)
    active_sessions = (await session.scalars(select(AuthSession).where(
        AuthSession.entity_id == entity.id, AuthSession.revoked_at.is_(None), AuthSession.expires_at > deadline,
    ))).all()
    for item in active_sessions:
        item.expires_at = deadline
    record_audit_event(
        session, entity_id=user.entity_id, actor_id=user.id, action="auth.policy.updated",
        target_type="entity", target_id=entity.id,
        details={"previous": previous, "current": payload.model_dump(), "sessions_shortened": len(active_sessions)},
    )
    await session.commit()
    return await authentication_policy_response(user, session, settings)


@router.post("/mfa/enroll")
async def enroll_mfa(
    payload: MfaEnrollRequest, user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings),
) -> dict:
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    if user.mfa_enabled:
        raise HTTPException(status_code=409, detail="Multi-factor authentication is already enabled")
    secret = generate_totp_secret()
    user.mfa_secret_encrypted = SecretBox(settings.auth_secret).encrypt(secret, f"mfa:{user.id}")
    user.mfa_enabled = False
    user.mfa_recovery_hashes = []
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="auth.mfa.enrollment_started",
                       target_type="user", target_id=user.id)
    await session.commit()
    issuer = quote("Workspace")
    account = quote(user.email)
    return {"secret": secret, "otpauth_uri": f"otpauth://totp/{issuer}:{account}?secret={secret}&issuer={issuer}&digits=6&period=30"}


@router.post("/mfa/confirm")
async def confirm_mfa(
    payload: MfaCodeRequest, request: Request, user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings),
) -> dict:
    if not user.mfa_secret_encrypted:
        raise HTTPException(status_code=409, detail="Start multi-factor enrollment first")
    try:
        secret = SecretBox(settings.auth_secret).decrypt(user.mfa_secret_encrypted, f"mfa:{user.id}")
    except SecretBoxError as error:
        raise HTTPException(status_code=500, detail="Multi-factor enrollment could not be verified") from error
    if not verify_totp(secret, payload.code):
        raise HTTPException(status_code=400, detail="Verification code is invalid or expired")
    recovery_codes = generate_recovery_codes()
    user.mfa_enabled = True
    user.mfa_recovery_hashes = [recovery_code_hash(user.id, code) for code in recovery_codes]
    auth_session = getattr(request.state, "auth_session", None)
    if auth_session:
        auth_session.auth_level = "mfa"
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="auth.mfa.enabled",
                       target_type="user", target_id=user.id)
    await session.commit()
    return {"mfa_enabled": True, "recovery_codes": recovery_codes}


@router.post("/mfa/step-up")
async def step_up_mfa(
    payload: MfaCodeRequest, request: Request, user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings),
) -> dict:
    if not user.mfa_enabled:
        raise HTTPException(status_code=409, detail="Multi-factor authentication is not enabled")
    auth_session = getattr(request.state, "auth_session", None)
    if not auth_session:
        raise HTTPException(status_code=409, detail="Sign out and back in to replace this legacy session")
    if not verify_user_mfa_code(user, payload.code, settings):
        raise HTTPException(status_code=400, detail="Verification code is invalid")
    auth_session.auth_level = "mfa"
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="auth.session.stepped_up",
                       target_type="user", target_id=user.id, details={"session_id": auth_session.id})
    await session.commit()
    return {"security_status": "compliant"}


@router.post("/mfa/disable")
async def disable_mfa(
    payload: MfaDisableRequest, request: Request, user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings),
) -> dict:
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    if not user.mfa_enabled or not user.mfa_secret_encrypted:
        raise HTTPException(status_code=409, detail="Multi-factor authentication is not enabled")
    if user_requires_mfa(user, getattr(request.state, "auth_policy", {})):
        raise HTTPException(status_code=409, detail="Your workspace policy requires multi-factor authentication")
    try:
        secret = SecretBox(settings.auth_secret).decrypt(user.mfa_secret_encrypted, f"mfa:{user.id}")
    except SecretBoxError as error:
        raise HTTPException(status_code=500, detail="Multi-factor authentication could not be disabled") from error
    candidate = recovery_code_hash(user.id, payload.code)
    if not verify_totp(secret, payload.code) and candidate not in (user.mfa_recovery_hashes or []):
        raise HTTPException(status_code=400, detail="Verification code is invalid")
    user.mfa_enabled = False
    user.mfa_secret_encrypted = None
    user.mfa_recovery_hashes = []
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="auth.mfa.disabled",
                       target_type="user", target_id=user.id)
    await session.commit()
    return {"mfa_enabled": False}


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_session(
    session_id: str, response: Response, request: Request,
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    auth_session = await session.get(AuthSession, session_id)
    if not auth_session or auth_session.user_id != user.id:
        raise HTTPException(status_code=404, detail="Session not found")
    auth_session.revoked_at = datetime.now(timezone.utc)
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="auth.session.revoked",
                       target_type="user", target_id=user.id, details={"session_id": auth_session.id})
    await session.commit()
    if current_session_id(request, settings) == auth_session.id:
        clear_session_cookie(response, settings)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post("/sessions/revoke-others")
async def revoke_other_sessions(
    request: Request, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    current_id = current_session_id(request, settings)
    now = datetime.now(timezone.utc)
    result = await session.execute(update(AuthSession).where(
        AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None),
        AuthSession.id != current_id if current_id else AuthSession.id.is_not(None),
    ).values(revoked_at=now))
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="auth.sessions.revoked_others",
                       target_type="user", target_id=user.id, details={"count": result.rowcount or 0})
    await session.commit()
    return {"revoked": result.rowcount or 0}
