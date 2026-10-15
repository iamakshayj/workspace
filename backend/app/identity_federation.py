import base64
import asyncio
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import ipaddress
import re
from secrets import token_urlsafe
import socket
from urllib.parse import quote_plus, unquote_plus, urlencode, urlparse
from uuid import uuid4
import zlib
import xml.etree.ElementTree as ElementTree

import httpx
import jwt
from cryptography import x509
from cryptography.exceptions import InvalidSignature as CryptoInvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID
from defusedxml import ElementTree as DefusedElementTree
from fastapi import APIRouter, Depends, Form, Header, HTTPException, Request, status
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from signxml import SignatureConfiguration, XMLVerifier
from signxml.exceptions import SignXMLException

from .auth import clear_session_cookie, create_auth_session, get_current_admin, get_current_user, hash_password, set_session_cookie
from .config import Settings, get_settings
from .database import (
    AuthSession, Entity, ExternalIdentity, IdentityProvider, IdentityProviderDomain, OrganizationUnit,
    OrganizationUnitMember, SamlAssertionReplay, SamlLogoutReplay, SamlLogoutState, SamlSigningCertificate, ScimAccessToken, SsoAuthorizationState, User, get_session,
)
from .governance import record_audit_event
from .identity import as_utc
from .quota_service import ensure_user_capacity
from .secret_box import SecretBox, SecretBoxError


identity_router = APIRouter(prefix="/identity", tags=["enterprise identity"])
sso_router = APIRouter(prefix="/auth/sso", tags=["enterprise SSO"])
scim_router = APIRouter(prefix="/scim/v2", tags=["SCIM 2.0"])
DOMAIN_PATTERN = re.compile(r"^(?=.{3,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
SCIM_SCHEMAS = ["urn:ietf:params:scim:schemas:core:2.0:User"]
SAML_PROTOCOL = "urn:oasis:names:tc:SAML:2.0:protocol"
SAML_ASSERTION = "urn:oasis:names:tc:SAML:2.0:assertion"
SAML_STATUS_SUCCESS = "urn:oasis:names:tc:SAML:2.0:status:Success"
SAML_EMAIL_NAME_ID = "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress"
SAML_MAX_RESPONSE_BYTES = 2_000_000
SAML_REDIRECT_BINDING = "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
SAML_RSA_SHA256 = "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"
SAML_METADATA = "urn:oasis:names:tc:SAML:2.0:metadata"


class ProviderWrite(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    issuer_url: str = Field(min_length=8, max_length=500)
    client_id: str = Field(min_length=1, max_length=300)
    client_secret: str | None = Field(default=None, max_length=2000)
    scopes: list[str] = Field(default_factory=lambda: ["openid", "profile", "email"], min_length=1, max_length=20)
    enabled: bool = False
    enforce_sso: bool = False
    jit_enabled: bool = True
    default_role: str = Field(default="basic", pattern=r"^(admin|basic|guest)$")
    allow_admin_password_fallback: bool = True

    @field_validator("issuer_url")
    @classmethod
    def secure_issuer(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        parsed = urlparse(normalized)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Issuer URL must be a public HTTPS origin")
        try:
            address = ipaddress.ip_address(parsed.hostname)
            if address.is_private or address.is_loopback or address.is_link_local:
                raise ValueError("Issuer URL cannot use a private network address")
        except ValueError as error:
            if "private network" in str(error):
                raise
        return normalized

    @field_validator("scopes")
    @classmethod
    def require_openid(cls, values: list[str]) -> list[str]:
        cleaned = list(dict.fromkeys(item.strip() for item in values if item.strip()))
        if "openid" not in cleaned:
            raise ValueError("OIDC scopes must include openid")
        return cleaned


class SamlProviderWrite(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    idp_entity_id: str = Field(min_length=3, max_length=500)
    sso_url: str = Field(min_length=8, max_length=1000)
    slo_url: str | None = Field(default=None, max_length=1000)
    x509_certificate: str | None = Field(default=None, max_length=20_000)
    sp_entity_id: str | None = Field(default=None, max_length=300)
    email_attribute: str | None = Field(default=None, max_length=500)
    sign_authn_requests: bool = True
    enabled: bool = False
    enforce_sso: bool = False
    jit_enabled: bool = True
    default_role: str = Field(default="basic", pattern=r"^(admin|basic|guest)$")
    allow_admin_password_fallback: bool = True

    @field_validator("sso_url")
    @classmethod
    def secure_sso_url(cls, value: str) -> str:
        normalized = value.strip()
        parsed = urlparse(normalized)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("The SAML sign-on URL must use a public HTTPS endpoint")
        try:
            address = ipaddress.ip_address(parsed.hostname)
            if address.is_private or address.is_loopback or address.is_link_local:
                raise ValueError("The SAML sign-on URL cannot use a private network address")
        except ValueError as error:
            if "private network" in str(error):
                raise
        return normalized

    @field_validator("slo_url")
    @classmethod
    def secure_slo_url(cls, value: str | None) -> str | None:
        if not value:
            return None
        normalized = value.strip()
        parsed = urlparse(normalized)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("The SAML logout URL must use a public HTTPS endpoint")
        try:
            address = ipaddress.ip_address(parsed.hostname)
            if not address.is_global:
                raise ValueError("The SAML logout URL cannot use a private network address")
        except ValueError as error:
            if "private network" in str(error):
                raise
        return normalized


class SamlMetadataInspectWrite(BaseModel):
    metadata_url: str = Field(min_length=8, max_length=1000)


class SamlCertificateWrite(BaseModel):
    x509_certificate: str = Field(min_length=100, max_length=20_000)

    @field_validator("x509_certificate")
    @classmethod
    def normalize_certificate(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if "-----BEGIN CERTIFICATE-----" not in normalized or "-----END CERTIFICATE-----" not in normalized:
            raise ValueError("Enter a PEM-encoded X.509 signing certificate")
        return normalized


class DomainWrite(BaseModel):
    domain: str = Field(min_length=3, max_length=253)

    @field_validator("domain")
    @classmethod
    def valid_domain(cls, value: str) -> str:
        normalized = value.strip().lower().rstrip(".")
        if not DOMAIN_PATTERN.fullmatch(normalized):
            raise ValueError("Enter a registrable domain name")
        return normalized


class EmailDiscovery(BaseModel):
    email: str = Field(min_length=5, max_length=320)


class ScimTokenWrite(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    expires_in_days: int | None = Field(default=365, ge=1, le=3650)
    scopes: list[str] = Field(default_factory=lambda: ["users:read", "users:write", "groups:read", "groups:write"])


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=value.tzinfo or timezone.utc)


async def provider_dict(item: IdentityProvider, session: AsyncSession) -> dict:
    domains = (await session.scalars(select(IdentityProviderDomain).where(
        IdentityProviderDomain.provider_id == item.id,
    ).order_by(IdentityProviderDomain.domain))).all()
    result = {
        "id": item.id, "name": item.name, "protocol": item.protocol, "domains": [
            {"domain": domain.domain, "status": domain.status, "verified_at": as_utc(domain.verified_at) if domain.verified_at else None}
            for domain in domains
        ],
        "enabled": item.enabled, "enforce_sso": item.enforce_sso, "jit_enabled": item.jit_enabled,
        "default_role": item.default_role, "allow_admin_password_fallback": item.allow_admin_password_fallback,
        "has_client_secret": bool(item.client_secret_encrypted), "created_at": as_utc(item.created_at),
        "updated_at": as_utc(item.updated_at),
    }
    if item.protocol == "saml":
        certificates = (await session.scalars(select(SamlSigningCertificate).where(
            SamlSigningCertificate.provider_id == item.id,
        ).order_by(SamlSigningCertificate.valid_until.desc()))).all()
        result.update({
            "idp_entity_id": item.issuer_url,
            "sp_entity_id": item.client_id,
            "sso_url": item.saml_sso_url,
            "slo_url": item.saml_slo_url,
            "email_attribute": item.saml_email_attribute,
            "sign_authn_requests": item.saml_sign_authn_requests,
            "has_sp_signing_key": bool(item.saml_sp_private_key_encrypted and item.saml_sp_certificate),
            "sp_certificate_fingerprint": certificate_fingerprint(item.saml_sp_certificate) if item.saml_sp_certificate else None,
            "signing_certificates": [{
                "id": certificate.id, "fingerprint_sha256": certificate.fingerprint_sha256,
                "status": certificate.status, "valid_from": as_utc(certificate.valid_from),
                "valid_until": as_utc(certificate.valid_until), "created_at": as_utc(certificate.created_at),
            } for certificate in certificates],
        })
    else:
        result.update({"issuer_url": item.issuer_url, "client_id": item.client_id, "scopes": item.scopes})
    return result


async def owned_provider(provider_id: str, user: User, session: AsyncSession) -> IdentityProvider:
    provider = await session.get(IdentityProvider, provider_id)
    if not provider or provider.entity_id != user.entity_id:
        raise HTTPException(status_code=404, detail="Identity provider not found")
    return provider


async def oidc_metadata(provider: IdentityProvider) -> dict:
    if provider.protocol != "oidc":
        raise HTTPException(status_code=409, detail="This connection does not use OpenID Connect")
    url = f"{provider.issuer_url}/.well-known/openid-configuration"
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=False) as client:
            response = await client.get(url, headers={"Accept": "application/json"})
            response.raise_for_status()
            metadata = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise HTTPException(status_code=502, detail="The provider discovery document could not be loaded") from error
    if str(metadata.get("issuer", "")).rstrip("/") != provider.issuer_url:
        raise HTTPException(status_code=502, detail="The discovery issuer does not match the configured issuer")
    for field in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not str(metadata.get(field, "")).startswith("https://"):
            raise HTTPException(status_code=502, detail=f"The discovery document is missing a secure {field}")
    return metadata


@identity_router.get("/providers")
async def list_providers(user: User = Depends(get_current_admin), session: AsyncSession = Depends(get_session)) -> list[dict]:
    rows = (await session.scalars(select(IdentityProvider).where(IdentityProvider.entity_id == user.entity_id).order_by(IdentityProvider.name))).all()
    return [await provider_dict(item, session) for item in rows]


@identity_router.post("/providers", status_code=201)
async def create_provider(payload: ProviderWrite, user: User = Depends(get_current_admin), session: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings)) -> dict:
    if not payload.client_secret:
        raise HTTPException(status_code=422, detail="A client secret is required when creating a provider")
    if payload.enforce_sso:
        raise HTTPException(status_code=409, detail="Verify at least one domain before enforcing SSO")
    provider = IdentityProvider(entity_id=user.entity_id, created_by_id=user.id, name=payload.name, issuer_url=payload.issuer_url,
        client_id=payload.client_id, client_secret_encrypted="pending", scopes=payload.scopes, enabled=payload.enabled,
        enforce_sso=payload.enforce_sso, jit_enabled=payload.jit_enabled, default_role=payload.default_role,
        allow_admin_password_fallback=payload.allow_admin_password_fallback)
    session.add(provider); await session.flush()
    provider.client_secret_encrypted = SecretBox(settings.auth_secret).encrypt(payload.client_secret, f"oidc:{provider.id}")
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="identity.provider.created", target_type="identity_provider", target_id=provider.id)
    try: await session.commit()
    except IntegrityError as error:
        await session.rollback(); raise HTTPException(status_code=409, detail="An identity provider already uses this name") from error
    await session.refresh(provider); return await provider_dict(provider, session)


@identity_router.put("/providers/{provider_id}")
async def update_provider(provider_id: str, payload: ProviderWrite, user: User = Depends(get_current_admin), session: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings)) -> dict:
    provider = await owned_provider(provider_id, user, session)
    if provider.protocol != "oidc":
        raise HTTPException(status_code=409, detail="Use the SAML settings endpoint for this connection")
    verified_domain = await session.scalar(select(IdentityProviderDomain.id).where(
        IdentityProviderDomain.provider_id == provider.id,
        IdentityProviderDomain.status == "verified",
    ))
    if payload.enforce_sso and not verified_domain:
        raise HTTPException(status_code=409, detail="Verify at least one domain before enforcing SSO")
    for field in ("name", "issuer_url", "client_id", "scopes", "enabled", "enforce_sso", "jit_enabled", "default_role", "allow_admin_password_fallback"):
        setattr(provider, field, getattr(payload, field))
    if payload.client_secret:
        provider.client_secret_encrypted = SecretBox(settings.auth_secret).encrypt(payload.client_secret, f"oidc:{provider.id}")
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="identity.provider.updated", target_type="identity_provider", target_id=provider.id,
                       details={"enabled": provider.enabled, "enforce_sso": provider.enforce_sso})
    await session.commit(); await session.refresh(provider); return await provider_dict(provider, session)


@identity_router.post("/providers/{provider_id}/test")
async def test_provider(provider_id: str, user: User = Depends(get_current_admin), session: AsyncSession = Depends(get_session)) -> dict:
    provider = await owned_provider(provider_id, user, session); metadata = await oidc_metadata(provider)
    return {"ok": True, "issuer": metadata["issuer"], "authorization_endpoint": metadata["authorization_endpoint"], "token_endpoint": metadata["token_endpoint"]}


def validate_saml_certificate(certificate: str) -> x509.Certificate:
    try:
        parsed = x509.load_pem_x509_certificate(certificate.encode())
    except ValueError as error:
        raise HTTPException(status_code=422, detail="The SAML signing certificate is not valid PEM") from error
    now = datetime.now(timezone.utc)
    if parsed.not_valid_before_utc > now + timedelta(minutes=5):
        raise HTTPException(status_code=422, detail="The SAML signing certificate is not valid yet")
    if parsed.not_valid_after_utc <= now:
        raise HTTPException(status_code=422, detail="The SAML signing certificate has expired")
    return parsed


def certificate_fingerprint(certificate: str) -> str:
    return validate_saml_certificate(certificate).fingerprint(hashes.SHA256()).hex()


def generate_sp_signing_material(common_name: str) -> tuple[str, str]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name[:64])])
    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(private_key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=730)).sign(private_key, hashes.SHA256())
    )
    key_pem = private_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    certificate_pem = certificate.public_bytes(serialization.Encoding.PEM).decode()
    return key_pem, certificate_pem


async def store_saml_certificate(session: AsyncSession, provider: IdentityProvider, certificate: str, actor_id: str | None, settings: Settings) -> SamlSigningCertificate:
    parsed = validate_saml_certificate(certificate)
    fingerprint = parsed.fingerprint(hashes.SHA256()).hex()
    existing = await session.scalar(select(SamlSigningCertificate).where(
        SamlSigningCertificate.provider_id == provider.id,
        SamlSigningCertificate.fingerprint_sha256 == fingerprint,
    ))
    if existing:
        if existing.status == "revoked":
            raise HTTPException(status_code=409, detail="A revoked certificate cannot be reactivated; upload the replacement certificate")
        return existing
    item = SamlSigningCertificate(
        provider_id=provider.id, entity_id=provider.entity_id, certificate_encrypted="pending",
        fingerprint_sha256=fingerprint, status="active", valid_from=parsed.not_valid_before_utc,
        valid_until=parsed.not_valid_after_utc, created_by_id=actor_id,
    )
    session.add(item)
    await session.flush()
    item.certificate_encrypted = SecretBox(settings.auth_secret).encrypt(certificate, f"saml-cert:{item.id}")
    return item


async def public_https_url(value: str) -> str:
    normalized = value.strip()
    parsed = urlparse(normalized)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(status_code=422, detail="Metadata must use a public HTTPS URL")
    try:
        port = parsed.port or 443
    except ValueError as error:
        raise HTTPException(status_code=422, detail="Metadata URL port is invalid") from error
    try:
        addresses = await asyncio.get_running_loop().getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        raise HTTPException(status_code=422, detail="Metadata hostname could not be resolved") from error
    if not addresses or any(not ipaddress.ip_address(address[4][0]).is_global for address in addresses):
        raise HTTPException(status_code=422, detail="Metadata hostname resolves to a private or reserved address")
    return normalized


@identity_router.post("/saml/metadata/inspect")
async def inspect_saml_metadata(payload: SamlMetadataInspectWrite, user: User = Depends(get_current_admin)) -> dict:
    metadata_url = await public_https_url(payload.metadata_url)
    raw = bytearray()
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
            async with client.stream("GET", metadata_url, headers={"Accept": "application/samlmetadata+xml, application/xml, text/xml"}) as response:
                response.raise_for_status()
                if int(response.headers.get("content-length", "0") or 0) > SAML_MAX_RESPONSE_BYTES:
                    raise HTTPException(status_code=413, detail="The SAML metadata document is too large")
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > SAML_MAX_RESPONSE_BYTES:
                        raise HTTPException(status_code=413, detail="The SAML metadata document is too large")
    except HTTPException:
        raise
    except httpx.HTTPError as error:
        raise HTTPException(status_code=502, detail="The SAML metadata document could not be loaded") from error
    upper = bytes(raw).upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise HTTPException(status_code=400, detail="The SAML metadata contains disallowed XML")
    try:
        root = DefusedElementTree.fromstring(bytes(raw))
    except Exception as error:
        raise HTTPException(status_code=400, detail="The SAML metadata is not valid XML") from error
    entity = root if root.tag == f"{{{SAML_METADATA}}}EntityDescriptor" else root.find(f".//{{{SAML_METADATA}}}EntityDescriptor")
    descriptor = entity.find(f"./{{{SAML_METADATA}}}IDPSSODescriptor") if entity is not None else None
    if entity is None or descriptor is None or not entity.get("entityID"):
        raise HTTPException(status_code=422, detail="No SAML identity-provider descriptor was found")
    services = descriptor.findall(f"./{{{SAML_METADATA}}}SingleSignOnService")
    selected = next((item for item in services if item.get("Binding") == SAML_REDIRECT_BINDING), None)
    selected = selected or next((item for item in services if str(item.get("Location", "")).startswith("https://")), None)
    if selected is None or not str(selected.get("Location", "")).startswith("https://"):
        raise HTTPException(status_code=422, detail="No secure SAML sign-on service was found")
    logout_services = descriptor.findall(f"./{{{SAML_METADATA}}}SingleLogoutService")
    logout = next((item for item in logout_services if item.get("Binding") == SAML_REDIRECT_BINDING), None)
    certificates: list[dict] = []
    seen: set[str] = set()
    for node in descriptor.findall(f"./{{{SAML_METADATA}}}KeyDescriptor"):
        if node.get("use") not in {None, "signing"}:
            continue
        value = node.find(".//{http://www.w3.org/2000/09/xmldsig#}X509Certificate")
        compact = re.sub(r"\s+", "", value.text or "") if value is not None else ""
        try:
            der = base64.b64decode(compact, validate=True)
            certificate = x509.load_der_x509_certificate(der).public_bytes(serialization.Encoding.PEM).decode()
            parsed = validate_saml_certificate(certificate)
        except (ValueError, HTTPException):
            continue
        fingerprint = parsed.fingerprint(hashes.SHA256()).hex()
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        certificates.append({"x509_certificate": certificate, "fingerprint_sha256": fingerprint, "valid_until": parsed.not_valid_after_utc.isoformat()})
    if not certificates:
        raise HTTPException(status_code=422, detail="No currently valid SAML signing certificate was found")
    return {"metadata_url": metadata_url, "idp_entity_id": entity.get("entityID"), "sso_url": selected.get("Location"), "slo_url": logout.get("Location") if logout is not None else None, "certificates": certificates}


@identity_router.post("/saml/providers", status_code=201)
async def create_saml_provider(payload: SamlProviderWrite, request: Request, user: User = Depends(get_current_admin), session: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings)) -> dict:
    if not payload.x509_certificate:
        raise HTTPException(status_code=422, detail="A SAML signing certificate is required when creating a provider")
    validate_saml_certificate(payload.x509_certificate)
    if payload.enforce_sso:
        raise HTTPException(status_code=409, detail="Verify at least one domain before enforcing SSO")
    provider = IdentityProvider(
        entity_id=user.entity_id, created_by_id=user.id, name=payload.name, protocol="saml",
        issuer_url=payload.idp_entity_id.strip(), client_id=payload.sp_entity_id or "pending",
        client_secret_encrypted="pending", scopes=[], saml_sso_url=payload.sso_url,
        saml_slo_url=payload.slo_url,
        saml_email_attribute=(payload.email_attribute or "").strip() or None,
        saml_sign_authn_requests=payload.sign_authn_requests,
        enabled=payload.enabled, enforce_sso=False, jit_enabled=payload.jit_enabled,
        default_role=payload.default_role, allow_admin_password_fallback=payload.allow_admin_password_fallback,
    )
    session.add(provider)
    await session.flush()
    if provider.client_id == "pending":
        provider.client_id = str(request.url_for("saml_metadata", provider_id=provider.id))
    provider.client_secret_encrypted = SecretBox(settings.auth_secret).encrypt(payload.x509_certificate, f"saml:{provider.id}")
    sp_private_key, sp_certificate = generate_sp_signing_material(f"Workspace SAML {provider.id}")
    provider.saml_sp_private_key_encrypted = SecretBox(settings.auth_secret).encrypt(sp_private_key, f"saml-sp-key:{provider.id}")
    provider.saml_sp_certificate = sp_certificate
    await store_saml_certificate(session, provider, payload.x509_certificate, user.id, settings)
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="identity.saml_provider.created", target_type="identity_provider", target_id=provider.id)
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise HTTPException(status_code=409, detail="An identity provider already uses this name") from error
    await session.refresh(provider)
    return await provider_dict(provider, session)


@identity_router.put("/saml/providers/{provider_id}")
async def update_saml_provider(provider_id: str, payload: SamlProviderWrite, user: User = Depends(get_current_admin), session: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings)) -> dict:
    provider = await owned_provider(provider_id, user, session)
    if provider.protocol != "saml":
        raise HTTPException(status_code=409, detail="Use the OpenID Connect settings endpoint for this connection")
    verified_domain = await session.scalar(select(IdentityProviderDomain.id).where(
        IdentityProviderDomain.provider_id == provider.id,
        IdentityProviderDomain.status == "verified",
    ))
    if payload.enforce_sso and not verified_domain:
        raise HTTPException(status_code=409, detail="Verify at least one domain before enforcing SSO")
    provider.name = payload.name
    provider.issuer_url = payload.idp_entity_id.strip()
    provider.saml_sso_url = payload.sso_url
    provider.saml_slo_url = payload.slo_url
    provider.client_id = (payload.sp_entity_id or provider.client_id).strip()
    provider.saml_email_attribute = (payload.email_attribute or "").strip() or None
    provider.saml_sign_authn_requests = payload.sign_authn_requests
    provider.enabled = payload.enabled
    provider.enforce_sso = payload.enforce_sso
    provider.jit_enabled = payload.jit_enabled
    provider.default_role = payload.default_role
    provider.allow_admin_password_fallback = payload.allow_admin_password_fallback
    if payload.x509_certificate:
        validate_saml_certificate(payload.x509_certificate)
        provider.client_secret_encrypted = SecretBox(settings.auth_secret).encrypt(payload.x509_certificate, f"saml:{provider.id}")
        await store_saml_certificate(session, provider, payload.x509_certificate, user.id, settings)
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="identity.saml_provider.updated", target_type="identity_provider", target_id=provider.id, details={"enabled": provider.enabled, "enforce_sso": provider.enforce_sso})
    await session.commit()
    await session.refresh(provider)
    return await provider_dict(provider, session)


@identity_router.post("/saml/providers/{provider_id}/test")
async def test_saml_provider(provider_id: str, user: User = Depends(get_current_admin), session: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings)) -> dict:
    provider = await owned_provider(provider_id, user, session)
    if provider.protocol != "saml" or not provider.saml_sso_url:
        raise HTTPException(status_code=409, detail="This connection is not a complete SAML provider")
    certificates = (await session.scalars(select(SamlSigningCertificate).where(
        SamlSigningCertificate.provider_id == provider.id,
        SamlSigningCertificate.status.in_(["active", "retiring"]),
    ))).all()
    if not certificates:
        raise HTTPException(status_code=409, detail="The SAML provider has no active signing certificate")
    if provider.saml_sign_authn_requests and (not provider.saml_sp_private_key_encrypted or not provider.saml_sp_certificate):
        raise HTTPException(status_code=409, detail="The SAML provider has no service-provider signing key")
    return {"ok": True, "idp_entity_id": provider.issuer_url, "sso_url": provider.saml_sso_url, "certificate_count": len(certificates), "certificate_expires_at": max(utc(item.valid_until) for item in certificates).isoformat(), "sp_entity_id": provider.client_id, "authn_requests_signed": provider.saml_sign_authn_requests}


@identity_router.post("/saml/providers/{provider_id}/certificates", status_code=201)
async def add_saml_certificate(provider_id: str, payload: SamlCertificateWrite, user: User = Depends(get_current_admin), session: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings)) -> dict:
    provider = await owned_provider(provider_id, user, session)
    if provider.protocol != "saml":
        raise HTTPException(status_code=409, detail="This connection does not use SAML")
    certificate = await store_saml_certificate(session, provider, payload.x509_certificate, user.id, settings)
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="identity.saml_certificate.added", target_type="saml_certificate", target_id=certificate.id, details={"fingerprint_sha256": certificate.fingerprint_sha256})
    await session.commit()
    return {"id": certificate.id, "fingerprint_sha256": certificate.fingerprint_sha256, "status": certificate.status, "valid_from": as_utc(certificate.valid_from), "valid_until": as_utc(certificate.valid_until)}


@identity_router.post("/saml/providers/{provider_id}/certificates/{certificate_id}/{action}")
async def change_saml_certificate(provider_id: str, certificate_id: str, action: str, user: User = Depends(get_current_admin), session: AsyncSession = Depends(get_session)) -> dict:
    provider = await owned_provider(provider_id, user, session)
    certificate = await session.get(SamlSigningCertificate, certificate_id)
    if not certificate or certificate.provider_id != provider.id or certificate.entity_id != user.entity_id:
        raise HTTPException(status_code=404, detail="SAML signing certificate not found")
    if action not in {"activate", "retire", "revoke"}:
        raise HTTPException(status_code=404, detail="Unknown certificate action")
    next_status = {"activate": "active", "retire": "retiring", "revoke": "revoked"}[action]
    if next_status == "revoked":
        usable = await session.scalar(select(SamlSigningCertificate.id).where(
            SamlSigningCertificate.provider_id == provider.id,
            SamlSigningCertificate.id != certificate.id,
            SamlSigningCertificate.status.in_(["active", "retiring"]),
            SamlSigningCertificate.valid_until > datetime.now(timezone.utc),
        ))
        if provider.enabled and not usable:
            raise HTTPException(status_code=409, detail="Add and validate a replacement before revoking the last usable certificate")
    certificate.status = next_status
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action=f"identity.saml_certificate.{action}d", target_type="saml_certificate", target_id=certificate.id, details={"fingerprint_sha256": certificate.fingerprint_sha256})
    await session.commit()
    return {"id": certificate.id, "fingerprint_sha256": certificate.fingerprint_sha256, "status": certificate.status, "valid_until": as_utc(certificate.valid_until)}


@identity_router.post("/providers/{provider_id}/domains", status_code=201)
async def create_domain_challenge(provider_id: str, payload: DomainWrite, user: User = Depends(get_current_admin), session: AsyncSession = Depends(get_session)) -> dict:
    provider = await owned_provider(provider_id, user, session)
    existing = await session.scalar(select(IdentityProviderDomain).where(IdentityProviderDomain.domain == payload.domain))
    if existing and existing.provider_id != provider.id:
        raise HTTPException(status_code=409, detail="This domain is already claimed by another workspace")
    token = f"workspace-domain={token_urlsafe(32)}"
    domain_record = existing or IdentityProviderDomain(provider_id=provider.id, entity_id=user.entity_id, domain=payload.domain, token_hash="")
    domain_record.status = "pending"; domain_record.token_hash = sha256(token.encode()).hexdigest(); domain_record.verified_at = None
    if not existing: session.add(domain_record)
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="identity.domain.challenge_created", target_type="identity_provider", target_id=provider.id, details={"domain": payload.domain})
    await session.commit()
    return {"domain": payload.domain, "status": "pending", "challenge_token": token, "verification_url": f"https://{payload.domain}/.well-known/workspace-domain-verification.txt"}


@identity_router.post("/providers/{provider_id}/domains/{domain}/verify")
async def verify_domain(provider_id: str, domain: str, user: User = Depends(get_current_admin), session: AsyncSession = Depends(get_session)) -> dict:
    provider = await owned_provider(provider_id, user, session); domain = DomainWrite(domain=domain).domain
    entry = await session.scalar(select(IdentityProviderDomain).where(
        IdentityProviderDomain.provider_id == provider.id, IdentityProviderDomain.domain == domain,
    ))
    if not entry: raise HTTPException(status_code=404, detail="Domain challenge not found")
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=False) as client:
            response = await client.get(f"https://{domain}/.well-known/workspace-domain-verification.txt"); response.raise_for_status()
    except httpx.HTTPError as error:
        raise HTTPException(status_code=409, detail="The domain verification file could not be read") from error
    if sha256(response.text.strip().encode()).hexdigest() != entry.token_hash:
        raise HTTPException(status_code=409, detail="The domain verification token does not match")
    entry.status = "verified"; entry.verified_at = datetime.now(timezone.utc)
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="identity.domain.verified", target_type="identity_provider", target_id=provider.id, details={"domain": domain})
    await session.commit(); return {"domain": domain, "status": "verified", "verified_at": as_utc(entry.verified_at)}


@sso_router.post("/discover")
async def discover_sso(payload: EmailDiscovery, session: AsyncSession = Depends(get_session)) -> dict:
    email = payload.email.strip().lower(); domain = email.rsplit("@", 1)[-1] if "@" in email else ""
    provider = await session.scalar(select(IdentityProvider).join(IdentityProviderDomain).where(
        IdentityProvider.enabled.is_(True), IdentityProviderDomain.domain == domain,
        IdentityProviderDomain.status == "verified",
    ))
    return {"available": bool(provider), "provider_id": provider.id if provider else None, "provider_name": provider.name if provider else None,
            "login_url": f"/api/v1/auth/sso/{provider.id}/start" if provider else None}


def safe_return_path(value: str) -> str:
    return value if value.startswith("/") and not value.startswith("//") and len(value) <= 500 else "/"


@sso_router.get("/{provider_id}/start")
async def start_oidc(provider_id: str, request: Request, return_to: str = "/", session: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings)) -> RedirectResponse:
    provider = await session.get(IdentityProvider, provider_id)
    if not provider or not provider.enabled: raise HTTPException(status_code=404, detail="SSO provider not found")
    if provider.protocol == "saml":
        return await start_saml(provider, request, return_to, session, settings)
    metadata = await oidc_metadata(provider); state = token_urlsafe(32); nonce = token_urlsafe(24); verifier = token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(sha256(verifier.encode()).digest()).decode().rstrip("=")
    record = SsoAuthorizationState(provider_id=provider.id, state_hash=sha256(state.encode()).hexdigest(), nonce=nonce,
        verifier_encrypted="pending", return_path=safe_return_path(return_to), expires_at=datetime.now(timezone.utc) + timedelta(minutes=10))
    session.add(record); await session.flush(); record.verifier_encrypted = SecretBox(settings.auth_secret).encrypt(verifier, f"oidc-state:{record.id}"); await session.commit()
    redirect_uri = str(request.url_for("oidc_callback", provider_id=provider.id))
    query = urlencode({"client_id": provider.client_id, "response_type": "code", "scope": " ".join(provider.scopes), "redirect_uri": redirect_uri,
                       "state": state, "nonce": nonce, "code_challenge": challenge, "code_challenge_method": "S256"})
    return RedirectResponse(f"{metadata['authorization_endpoint']}?{query}", status_code=302)


@sso_router.get("/{provider_id}/metadata", name="saml_metadata")
async def saml_metadata(provider_id: str, request: Request, session: AsyncSession = Depends(get_session)) -> Response:
    provider = await session.get(IdentityProvider, provider_id)
    if not provider or provider.protocol != "saml":
        raise HTTPException(status_code=404, detail="SAML provider not found")
    entity = ElementTree.Element("{urn:oasis:names:tc:SAML:2.0:metadata}EntityDescriptor", {"entityID": provider.client_id})
    service = ElementTree.SubElement(entity, "{urn:oasis:names:tc:SAML:2.0:metadata}SPSSODescriptor", {
        "AuthnRequestsSigned": "true" if provider.saml_sign_authn_requests else "false", "WantAssertionsSigned": "true",
        "protocolSupportEnumeration": SAML_PROTOCOL,
    })
    if provider.saml_sp_certificate:
        certificate = x509.load_pem_x509_certificate(provider.saml_sp_certificate.encode())
        key_descriptor = ElementTree.SubElement(service, "{urn:oasis:names:tc:SAML:2.0:metadata}KeyDescriptor", {"use": "signing"})
        key_info = ElementTree.SubElement(key_descriptor, "{http://www.w3.org/2000/09/xmldsig#}KeyInfo")
        x509_data = ElementTree.SubElement(key_info, "{http://www.w3.org/2000/09/xmldsig#}X509Data")
        ElementTree.SubElement(x509_data, "{http://www.w3.org/2000/09/xmldsig#}X509Certificate").text = base64.b64encode(certificate.public_bytes(serialization.Encoding.DER)).decode()
    if provider.saml_slo_url:
        ElementTree.SubElement(service, "{urn:oasis:names:tc:SAML:2.0:metadata}SingleLogoutService", {
            "Binding": SAML_REDIRECT_BINDING,
            "Location": str(request.url_for("saml_logout_callback", provider_id=provider.id)),
        })
    ElementTree.SubElement(service, "{urn:oasis:names:tc:SAML:2.0:metadata}NameIDFormat").text = SAML_EMAIL_NAME_ID
    ElementTree.SubElement(service, "{urn:oasis:names:tc:SAML:2.0:metadata}AssertionConsumerService", {
        "Binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
        "Location": str(request.url_for("saml_acs", provider_id=provider.id)), "index": "0", "isDefault": "true",
    })
    return Response(ElementTree.tostring(entity, encoding="utf-8", xml_declaration=True), media_type="application/samlmetadata+xml")


def signed_saml_redirect_query(parameters: list[tuple[str, str]], provider: IdentityProvider, settings: Settings, *, force_sign: bool = False) -> str:
    if not force_sign and not provider.saml_sign_authn_requests:
        return urlencode(parameters)
    if not provider.saml_sp_private_key_encrypted:
        raise HTTPException(status_code=500, detail="The service-provider signing key is unavailable")
    signed_parameters = [*parameters, ("SigAlg", SAML_RSA_SHA256)]
    signed_query = urlencode(signed_parameters)
    try:
        private_key_pem = SecretBox(settings.auth_secret).decrypt(provider.saml_sp_private_key_encrypted, f"saml-sp-key:{provider.id}")
        private_key = serialization.load_pem_private_key(private_key_pem.encode(), password=None)
        signature = private_key.sign(signed_query.encode(), padding.PKCS1v15(), hashes.SHA256())
    except (SecretBoxError, TypeError, ValueError) as error:
        raise HTTPException(status_code=500, detail="The service-provider signing key could not be opened") from error
    return f"{signed_query}&Signature={quote_plus(base64.b64encode(signature).decode())}"


async def start_saml(provider: IdentityProvider, request: Request, return_to: str, session: AsyncSession, settings: Settings) -> RedirectResponse:
    if not provider.saml_sso_url:
        raise HTTPException(status_code=409, detail="The SAML provider is missing a sign-on URL")
    relay_state = token_urlsafe(32)
    request_id = f"_{uuid4()}"
    now = datetime.now(timezone.utc)
    record = SsoAuthorizationState(
        provider_id=provider.id, state_hash=sha256(relay_state.encode()).hexdigest(), nonce=request_id,
        verifier_encrypted="pending", return_path=safe_return_path(return_to), expires_at=now + timedelta(minutes=10),
    )
    session.add(record)
    await session.flush()
    record.verifier_encrypted = SecretBox(settings.auth_secret).encrypt("saml", f"saml-state:{record.id}")
    await session.commit()

    acs_url = str(request.url_for("saml_acs", provider_id=provider.id))
    authn_request = ElementTree.Element(f"{{{SAML_PROTOCOL}}}AuthnRequest", {
        "ID": request_id, "Version": "2.0", "IssueInstant": now.isoformat().replace("+00:00", "Z"),
        "Destination": provider.saml_sso_url, "AssertionConsumerServiceURL": acs_url,
        "ProtocolBinding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
    })
    ElementTree.SubElement(authn_request, f"{{{SAML_ASSERTION}}}Issuer").text = provider.client_id
    ElementTree.SubElement(authn_request, f"{{{SAML_PROTOCOL}}}NameIDPolicy", {"Format": SAML_EMAIL_NAME_ID, "AllowCreate": "true"})
    raw = ElementTree.tostring(authn_request, encoding="utf-8")
    compressor = zlib.compressobj(level=9, wbits=-15)
    encoded = base64.b64encode(compressor.compress(raw) + compressor.flush()).decode()
    query = signed_saml_redirect_query([("SAMLRequest", encoded), ("RelayState", relay_state)], provider, settings)
    return RedirectResponse(f"{provider.saml_sso_url}?{query}", status_code=302)


async def usable_saml_certificates(provider: IdentityProvider, session: AsyncSession, settings: Settings, now: datetime) -> list[str]:
    rows = (await session.scalars(select(SamlSigningCertificate).where(
        SamlSigningCertificate.provider_id == provider.id,
        SamlSigningCertificate.status.in_(["active", "retiring"]),
        SamlSigningCertificate.valid_from <= now + timedelta(minutes=5),
        SamlSigningCertificate.valid_until > now,
    ))).all()
    certificates: list[str] = []
    for row in rows:
        try:
            certificates.append(SecretBox(settings.auth_secret).decrypt(row.certificate_encrypted, f"saml-cert:{row.id}"))
        except SecretBoxError:
            continue
    if not rows:
        try:
            certificates.append(SecretBox(settings.auth_secret).decrypt(provider.client_secret_encrypted, f"saml:{provider.id}"))
        except SecretBoxError:
            pass
    return certificates


async def verified_redirect_message(request: Request, message_key: str, provider: IdentityProvider, session: AsyncSession, settings: Settings) -> tuple[object, str | None]:
    raw_query = request.scope.get("query_string", b"")
    if len(raw_query) > SAML_MAX_RESPONSE_BYTES * 2:
        raise HTTPException(status_code=413, detail="The SAML logout message is too large")
    try:
        parts = raw_query.decode("ascii").split("&")
        keys = [unquote_plus(part.split("=", 1)[0]) for part in parts]
    except UnicodeDecodeError as error:
        raise HTTPException(status_code=400, detail="The SAML logout query is invalid") from error
    expected = [message_key]
    if "RelayState" in keys:
        expected.append("RelayState")
    expected.extend(["SigAlg", "Signature"])
    if keys != expected or any("=" not in part for part in parts):
        raise HTTPException(status_code=400, detail="The signed SAML logout query has unexpected or duplicate parameters")
    values = {key: unquote_plus(part.split("=", 1)[1]) for key, part in zip(keys, parts)}
    if values.get("SigAlg") != SAML_RSA_SHA256:
        raise HTTPException(status_code=401, detail="The SAML logout signature algorithm is not allowed")
    try:
        signature = base64.b64decode(values["Signature"], validate=True)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="The SAML logout signature is invalid") from error
    signed_query = "&".join(parts[:-1]).encode()
    verified = False
    now = datetime.now(timezone.utc)
    for certificate in await usable_saml_certificates(provider, session, settings, now):
        try:
            public_key = validate_saml_certificate(certificate).public_key()
            public_key.verify(signature, signed_query, padding.PKCS1v15(), hashes.SHA256())
            verified = True
            break
        except (CryptoInvalidSignature, HTTPException, ValueError, TypeError):
            continue
    if not verified:
        raise HTTPException(status_code=401, detail="The SAML logout signature could not be verified")
    try:
        compressed = base64.b64decode(values[message_key], validate=True)
        decompressor = zlib.decompressobj(wbits=-15)
        raw = decompressor.decompress(compressed, SAML_MAX_RESPONSE_BYTES + 1)
        if decompressor.unconsumed_tail or len(raw) > SAML_MAX_RESPONSE_BYTES:
            raise ValueError("expanded message is too large")
    except (ValueError, zlib.error) as error:
        raise HTTPException(status_code=400, detail="The SAML logout message could not be decoded") from error
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise HTTPException(status_code=400, detail="The SAML logout message contains disallowed XML")
    try:
        root = DefusedElementTree.fromstring(raw)
    except Exception as error:
        raise HTTPException(status_code=400, detail="The SAML logout message is not valid XML") from error
    return root, values.get("RelayState")


@sso_router.get("/logout/discover")
async def discover_saml_logout(request: Request, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> dict:
    auth_session = getattr(request.state, "auth_session", None)
    provider = await session.get(IdentityProvider, auth_session.identity_provider_id) if auth_session and auth_session.identity_provider_id else None
    available = bool(provider and provider.protocol == "saml" and provider.saml_slo_url and auth_session.external_subject)
    return {"available": available, "provider_name": provider.name if available else None, "logout_url": f"/api/v1/auth/sso/{provider.id}/logout/start" if available else None}


@sso_router.get("/{provider_id}/logout/start")
async def start_saml_logout(provider_id: str, request: Request, return_to: str = "/", user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings)) -> RedirectResponse:
    auth_session = getattr(request.state, "auth_session", None)
    provider = await session.get(IdentityProvider, provider_id)
    if not auth_session or auth_session.user_id != user.id or auth_session.identity_provider_id != provider_id:
        raise HTTPException(status_code=403, detail="This browser session is not bound to the requested identity provider")
    if not provider or provider.protocol != "saml" or not provider.saml_slo_url or not auth_session.external_subject:
        raise HTTPException(status_code=409, detail="SAML Single Logout is not configured for this session")
    now = datetime.now(timezone.utc)
    request_id = f"_{uuid4()}"
    relay_state = token_urlsafe(32)
    state = SamlLogoutState(
        provider_id=provider.id, auth_session_id=auth_session.id, request_id=request_id,
        state_hash=sha256(relay_state.encode()).hexdigest(), return_path=safe_return_path(return_to),
        expires_at=now + timedelta(minutes=10),
    )
    session.add(state)
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="auth.saml.logout_started", target_type="identity_provider", target_id=provider.id, details={"session_id": auth_session.id})
    await session.commit()
    logout_request = ElementTree.Element(f"{{{SAML_PROTOCOL}}}LogoutRequest", {
        "ID": request_id, "Version": "2.0", "IssueInstant": now.isoformat().replace("+00:00", "Z"),
        "Destination": provider.saml_slo_url,
    })
    ElementTree.SubElement(logout_request, f"{{{SAML_ASSERTION}}}Issuer").text = provider.client_id
    ElementTree.SubElement(logout_request, f"{{{SAML_ASSERTION}}}NameID").text = auth_session.external_subject
    if auth_session.external_session_index:
        ElementTree.SubElement(logout_request, f"{{{SAML_PROTOCOL}}}SessionIndex").text = auth_session.external_session_index
    raw = ElementTree.tostring(logout_request, encoding="utf-8")
    compressor = zlib.compressobj(level=9, wbits=-15)
    encoded = base64.b64encode(compressor.compress(raw) + compressor.flush()).decode()
    query = signed_saml_redirect_query([("SAMLRequest", encoded), ("RelayState", relay_state)], provider, settings, force_sign=True)
    return RedirectResponse(f"{provider.saml_slo_url}?{query}", status_code=302)


@sso_router.get("/{provider_id}/logout/callback", name="saml_logout_callback")
async def saml_logout_callback(provider_id: str, request: Request, session: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings)) -> RedirectResponse:
    provider = await session.get(IdentityProvider, provider_id)
    if not provider or provider.protocol != "saml" or not provider.saml_slo_url:
        raise HTTPException(status_code=404, detail="SAML Single Logout provider not found")
    try:
        keys = [unquote_plus(part.split("=", 1)[0]) for part in request.scope.get("query_string", b"").decode("ascii").split("&") if part]
    except UnicodeDecodeError as error:
        raise HTTPException(status_code=400, detail="The SAML logout query is invalid") from error
    now = datetime.now(timezone.utc)
    callback_url = str(request.url_for("saml_logout_callback", provider_id=provider.id))
    if "SAMLResponse" in keys:
        root, relay_state = await verified_redirect_message(request, "SAMLResponse", provider, session, settings)
        if not relay_state:
            raise HTTPException(status_code=400, detail="SAML logout RelayState is required")
        state = await session.scalar(select(SamlLogoutState).where(
            SamlLogoutState.provider_id == provider.id,
            SamlLogoutState.state_hash == sha256(relay_state.encode()).hexdigest(),
        ).with_for_update())
        if not state or state.consumed_at or utc(state.expires_at) <= now:
            raise HTTPException(status_code=400, detail="SAML logout state is invalid or expired")
        if root.tag != f"{{{SAML_PROTOCOL}}}LogoutResponse" or root.get("InResponseTo") != state.request_id or root.get("Destination") != callback_url:
            raise HTTPException(status_code=401, detail="The SAML LogoutResponse did not match the request")
        issue_instant = parse_saml_time(root.get("IssueInstant"), "LogoutResponse IssueInstant")
        if abs((now - issue_instant).total_seconds()) > 600:
            raise HTTPException(status_code=401, detail="The SAML LogoutResponse issue time is outside the allowed window")
        issuer = root.find(f"./{{{SAML_ASSERTION}}}Issuer")
        status_code = root.find(f"./{{{SAML_PROTOCOL}}}Status/{{{SAML_PROTOCOL}}}StatusCode")
        if issuer is None or (issuer.text or "").strip() != provider.issuer_url or status_code is None or status_code.get("Value") != SAML_STATUS_SUCCESS:
            raise HTTPException(status_code=401, detail="The SAML LogoutResponse issuer or status did not match")
        state.consumed_at = now
        auth_session = await session.get(AuthSession, state.auth_session_id)
        if auth_session and auth_session.identity_provider_id == provider.id:
            auth_session.revoked_at = now
            record_audit_event(session, entity_id=auth_session.entity_id, actor_id=auth_session.user_id, action="auth.saml.logout_completed", target_type="identity_provider", target_id=provider.id, details={"session_id": auth_session.id})
        await session.commit()
        response = RedirectResponse(f"{settings.frontend_url.rstrip('/')}{state.return_path}", status_code=302)
        clear_session_cookie(response, settings)
        return response

    if "SAMLRequest" not in keys:
        raise HTTPException(status_code=400, detail="A SAML logout request or response is required")
    root, relay_state = await verified_redirect_message(request, "SAMLRequest", provider, session, settings)
    if root.tag != f"{{{SAML_PROTOCOL}}}LogoutRequest" or root.get("Destination") != callback_url:
        raise HTTPException(status_code=401, detail="The SAML LogoutRequest destination did not match")
    request_id = str(root.get("ID") or "")
    issue_instant = parse_saml_time(root.get("IssueInstant"), "LogoutRequest IssueInstant")
    issuer = root.find(f"./{{{SAML_ASSERTION}}}Issuer")
    name_id = root.find(f"./{{{SAML_ASSERTION}}}NameID")
    session_index_node = root.find(f"./{{{SAML_PROTOCOL}}}SessionIndex")
    subject = (name_id.text or "").strip() if name_id is not None else ""
    session_index = (session_index_node.text or "").strip() if session_index_node is not None else ""
    if not request_id or abs((now - issue_instant).total_seconds()) > 600 or issuer is None or (issuer.text or "").strip() != provider.issuer_url or not subject:
        raise HTTPException(status_code=401, detail="The SAML LogoutRequest identity or issue time did not match")
    if await session.scalar(select(SamlLogoutReplay.id).where(SamlLogoutReplay.request_id == request_id)):
        raise HTTPException(status_code=401, detail="The SAML LogoutRequest has already been used")
    query = select(AuthSession).where(
        AuthSession.identity_provider_id == provider.id, AuthSession.external_subject == subject,
        AuthSession.revoked_at.is_(None),
    )
    if session_index:
        query = query.where(AuthSession.external_session_index == session_index)
    sessions_to_revoke = (await session.scalars(query)).all()
    for auth_session in sessions_to_revoke:
        auth_session.revoked_at = now
    session.add(SamlLogoutReplay(provider_id=provider.id, request_id=request_id, expires_at=now + timedelta(days=1), consumed_at=now))
    record_audit_event(session, entity_id=provider.entity_id, actor_id=None, action="auth.saml.idp_logout", target_type="identity_provider", target_id=provider.id, details={"revoked_sessions": len(sessions_to_revoke), "request_id_hash": sha256(request_id.encode()).hexdigest()})
    response_id = f"_{uuid4()}"
    logout_response = ElementTree.Element(f"{{{SAML_PROTOCOL}}}LogoutResponse", {
        "ID": response_id, "Version": "2.0", "IssueInstant": now.isoformat().replace("+00:00", "Z"),
        "Destination": provider.saml_slo_url, "InResponseTo": request_id,
    })
    ElementTree.SubElement(logout_response, f"{{{SAML_ASSERTION}}}Issuer").text = provider.client_id
    status_element = ElementTree.SubElement(logout_response, f"{{{SAML_PROTOCOL}}}Status")
    ElementTree.SubElement(status_element, f"{{{SAML_PROTOCOL}}}StatusCode", {"Value": SAML_STATUS_SUCCESS})
    raw = ElementTree.tostring(logout_response, encoding="utf-8")
    compressor = zlib.compressobj(level=9, wbits=-15)
    encoded = base64.b64encode(compressor.compress(raw) + compressor.flush()).decode()
    parameters = [("SAMLResponse", encoded)]
    if relay_state is not None:
        parameters.append(("RelayState", relay_state))
    redirect_query = signed_saml_redirect_query(parameters, provider, settings, force_sign=True)
    await session.commit()
    response = RedirectResponse(f"{provider.saml_slo_url}?{redirect_query}", status_code=302)
    clear_session_cookie(response, settings)
    return response


def parse_saml_time(value: str | None, field: str) -> datetime:
    if not value:
        raise HTTPException(status_code=401, detail=f"The SAML assertion is missing {field}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise HTTPException(status_code=401, detail=f"The SAML assertion has an invalid {field}") from error
    return parsed.astimezone(timezone.utc)


def saml_attribute(assertion, configured_name: str | None, common_names: set[str]) -> str:
    for attribute in assertion.findall(f".//{{{SAML_ASSERTION}}}Attribute"):
        name = str(attribute.get("Name") or "")
        if (configured_name and name == configured_name) or (not configured_name and name.lower() in common_names):
            value = attribute.find(f"{{{SAML_ASSERTION}}}AttributeValue")
            if value is not None and value.text:
                return value.text.strip()
    return ""


@sso_router.post("/{provider_id}/acs", name="saml_acs")
async def saml_acs(provider_id: str, request: Request, SAMLResponse: str = Form(...), RelayState: str = Form(...), session: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings)) -> RedirectResponse:
    now = datetime.now(timezone.utc)
    state_record = await session.scalar(select(SsoAuthorizationState).where(
        SsoAuthorizationState.provider_id == provider_id,
        SsoAuthorizationState.state_hash == sha256(RelayState.encode()).hexdigest(),
    ).with_for_update())
    if not state_record or state_record.consumed_at or utc(state_record.expires_at) <= now:
        raise HTTPException(status_code=400, detail="SAML relay state is invalid or expired")
    state_record.consumed_at = now
    provider = await session.get(IdentityProvider, provider_id)
    if not provider or provider.protocol != "saml" or not provider.enabled:
        raise HTTPException(status_code=404, detail="SAML provider not found")
    await session.commit()
    try:
        raw = base64.b64decode(SAMLResponse, validate=True)
    except (ValueError, TypeError) as error:
        raise HTTPException(status_code=400, detail="The SAML response is not valid base64") from error
    if len(raw) > SAML_MAX_RESPONSE_BYTES or b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise HTTPException(status_code=400, detail="The SAML response contains disallowed XML")
    try:
        preflight = DefusedElementTree.fromstring(raw)
    except Exception as error:
        raise HTTPException(status_code=400, detail="The SAML response is not valid XML") from error
    if preflight.tag != f"{{{SAML_PROTOCOL}}}Response" or preflight.find("{http://www.w3.org/2000/09/xmldsig#}Signature") is None:
        raise HTTPException(status_code=401, detail="A signed SAML response is required")
    certificate_rows = (await session.scalars(select(SamlSigningCertificate).where(
        SamlSigningCertificate.provider_id == provider.id,
        SamlSigningCertificate.status.in_(["active", "retiring"]),
        SamlSigningCertificate.valid_from <= now + timedelta(minutes=5),
        SamlSigningCertificate.valid_until > now,
    ))).all()
    certificates: list[str] = []
    for certificate_row in certificate_rows:
        try:
            certificates.append(SecretBox(settings.auth_secret).decrypt(certificate_row.certificate_encrypted, f"saml-cert:{certificate_row.id}"))
        except SecretBoxError:
            continue
    if not certificate_rows:  # Compatibility for SAML providers created before certificate rotation was introduced.
        try:
            certificates.append(SecretBox(settings.auth_secret).decrypt(provider.client_secret_encrypted, f"saml:{provider.id}"))
        except SecretBoxError:
            pass
    response_xml = None
    for certificate in certificates:
        try:
            validate_saml_certificate(certificate)
            verified = XMLVerifier().verify(raw, x509_cert=certificate, id_attribute="ID", expect_config=SignatureConfiguration(require_x509=True, expect_references=1))
            response_xml = verified.signed_xml
            break
        except (HTTPException, SignXMLException, ValueError):
            continue
    if response_xml is None:
        raise HTTPException(status_code=401, detail="The SAML response signature could not be verified by an active certificate")
    if response_xml.tag != f"{{{SAML_PROTOCOL}}}Response" or response_xml.get("ID") != preflight.get("ID"):
        raise HTTPException(status_code=401, detail="The SAML signature did not cover the response")
    acs_url = str(request.url_for("saml_acs", provider_id=provider.id))
    if response_xml.get("InResponseTo") != state_record.nonce or response_xml.get("Destination") != acs_url:
        raise HTTPException(status_code=401, detail="The SAML response destination or request binding did not match")
    status_code = response_xml.find(f"./{{{SAML_PROTOCOL}}}Status/{{{SAML_PROTOCOL}}}StatusCode")
    if status_code is None or status_code.get("Value") != SAML_STATUS_SUCCESS:
        raise HTTPException(status_code=401, detail="The identity provider did not return a successful SAML status")
    response_issuer = response_xml.find(f"./{{{SAML_ASSERTION}}}Issuer")
    assertion = response_xml.find(f"./{{{SAML_ASSERTION}}}Assertion")
    if assertion is None or response_issuer is None or (response_issuer.text or "").strip() != provider.issuer_url:
        raise HTTPException(status_code=401, detail="The SAML response issuer did not match")
    assertion_issuer = assertion.find(f"./{{{SAML_ASSERTION}}}Issuer")
    assertion_id = str(assertion.get("ID") or "")
    if not assertion_id or assertion_issuer is None or (assertion_issuer.text or "").strip() != provider.issuer_url:
        raise HTTPException(status_code=401, detail="The SAML assertion issuer did not match")
    if await session.scalar(select(SamlAssertionReplay.id).where(SamlAssertionReplay.assertion_id == assertion_id)):
        raise HTTPException(status_code=401, detail="The SAML assertion has already been used")
    conditions = assertion.find(f"./{{{SAML_ASSERTION}}}Conditions")
    if conditions is None:
        raise HTTPException(status_code=401, detail="The SAML assertion has no validity conditions")
    skew = timedelta(minutes=2)
    not_before = parse_saml_time(conditions.get("NotBefore"), "NotBefore")
    not_after = parse_saml_time(conditions.get("NotOnOrAfter"), "NotOnOrAfter")
    if now + skew < not_before or now - skew >= not_after:
        raise HTTPException(status_code=401, detail="The SAML assertion is outside its validity period")
    audiences = {(item.text or "").strip() for item in conditions.findall(f".//{{{SAML_ASSERTION}}}Audience")}
    if provider.client_id not in audiences:
        raise HTTPException(status_code=401, detail="The SAML assertion audience did not match")
    confirmation = assertion.find(f".//{{{SAML_ASSERTION}}}SubjectConfirmationData")
    if confirmation is None or confirmation.get("InResponseTo") != state_record.nonce or confirmation.get("Recipient") != acs_url:
        raise HTTPException(status_code=401, detail="The SAML subject confirmation did not match")
    confirmation_expiry = parse_saml_time(confirmation.get("NotOnOrAfter"), "SubjectConfirmationData NotOnOrAfter")
    if now - skew >= confirmation_expiry:
        raise HTTPException(status_code=401, detail="The SAML subject confirmation has expired")
    name_id = assertion.find(f".//{{{SAML_ASSERTION}}}NameID")
    subject = (name_id.text or "").strip() if name_id is not None else ""
    email_names = {"email", "mail", "emailaddress", "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress"}
    email = saml_attribute(assertion, provider.saml_email_attribute, email_names).lower()
    if not email and "@" in subject:
        email = subject.lower()
    domain = email.rsplit("@", 1)[-1] if "@" in email else ""
    verified_domain = await session.scalar(select(IdentityProviderDomain.id).where(
        IdentityProviderDomain.provider_id == provider.id, IdentityProviderDomain.domain == domain,
        IdentityProviderDomain.status == "verified",
    ))
    if not subject or not email or not verified_domain:
        raise HTTPException(status_code=403, detail="The SAML identity is not in a verified workspace domain")
    link = await session.scalar(select(ExternalIdentity).where(ExternalIdentity.provider_id == provider.id, ExternalIdentity.subject == subject))
    user = await session.get(User, link.user_id) if link else await session.scalar(select(User).where(User.email == email))
    if user and user.entity_id != provider.entity_id:
        raise HTTPException(status_code=409, detail="This email belongs to another workspace")
    if not user:
        if not provider.jit_enabled:
            raise HTTPException(status_code=403, detail="Your account has not been provisioned")
        await ensure_user_capacity(session, provider.entity_id, additional_reserved_seats=0)
        display_name = saml_attribute(assertion, None, {"displayname", "name", "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name"})
        user = User(entity_id=provider.entity_id, email=email, display_name=(display_name or email.split("@", 1)[0])[:100], password_hash=hash_password(token_urlsafe(48)), role=provider.default_role, provisioning_source="saml")
        session.add(user)
        await session.flush()
    if user.account_status != "active":
        raise HTTPException(status_code=403, detail="This account is suspended")
    if not link:
        link = ExternalIdentity(entity_id=provider.entity_id, provider_id=provider.id, user_id=user.id, subject=subject, email_at_link=email)
        session.add(link)
    link.last_login_at = now
    session.add(SamlAssertionReplay(provider_id=provider.id, assertion_id=assertion_id, expires_at=not_after, consumed_at=now))
    contexts = {(item.text or "").strip().lower() for item in assertion.findall(f".//{{{SAML_ASSERTION}}}AuthnContextClassRef")}
    mfa_markers = ("multifactor", "multipleauthn", "timesynctoken", "smartcardpki", "mobiletwofactor")
    auth_level = "mfa" if any(any(marker in context for marker in mfa_markers) for context in contexts) else "sso"
    auth_session = await create_auth_session(session, user, request, settings, auth_level=auth_level)
    authn_statement = assertion.find(f".//{{{SAML_ASSERTION}}}AuthnStatement")
    auth_session.identity_provider_id = provider.id
    auth_session.external_session_index = authn_statement.get("SessionIndex") if authn_statement is not None else None
    auth_session.external_subject = subject
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="auth.saml.login", target_type="identity_provider", target_id=provider.id, details={"session_id": auth_session.id, "auth_level": auth_level, "assertion_id_hash": sha256(assertion_id.encode()).hexdigest()})
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise HTTPException(status_code=401, detail="The SAML assertion has already been used") from error
    response = RedirectResponse(f"{settings.frontend_url.rstrip('/')}{state_record.return_path}", status_code=302)
    set_session_cookie(response, user.id, settings, auth_session.id, utc(auth_session.expires_at))
    return response


@sso_router.get("/{provider_id}/callback", name="oidc_callback")
async def oidc_callback(provider_id: str, request: Request, code: str, state: str, session: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings)) -> RedirectResponse:
    state_record = await session.scalar(select(SsoAuthorizationState).where(SsoAuthorizationState.provider_id == provider_id, SsoAuthorizationState.state_hash == sha256(state.encode()).hexdigest()).with_for_update())
    now = datetime.now(timezone.utc)
    if not state_record or state_record.consumed_at or utc(state_record.expires_at) <= now: raise HTTPException(status_code=400, detail="SSO authorization state is invalid or expired")
    state_record.consumed_at = now; provider = await session.get(IdentityProvider, provider_id)
    if not provider or not provider.enabled or provider.protocol != "oidc": raise HTTPException(status_code=404, detail="SSO provider not found")
    await session.commit()  # Consume before token exchange so a provider or callback failure cannot make the state replayable.
    try:
        verifier = SecretBox(settings.auth_secret).decrypt(state_record.verifier_encrypted, f"oidc-state:{state_record.id}")
        secret = SecretBox(settings.auth_secret).decrypt(provider.client_secret_encrypted, f"oidc:{provider.id}")
    except SecretBoxError as error: raise HTTPException(status_code=500, detail="SSO credentials could not be opened") from error
    metadata = await oidc_metadata(provider); redirect_uri = str(request.url_for("oidc_callback", provider_id=provider.id))
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            token_response = await client.post(metadata["token_endpoint"], data={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri, "client_id": provider.client_id, "client_secret": secret, "code_verifier": verifier}); token_response.raise_for_status(); token_payload = token_response.json()
            jwks_response = await client.get(metadata["jwks_uri"]); jwks_response.raise_for_status(); jwks = jwks_response.json()
        id_token = token_payload["id_token"]; header = jwt.get_unverified_header(id_token); algorithm = header.get("alg")
        if algorithm not in {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512"}: raise ValueError("unsupported algorithm")
        key_data = next(item for item in jwks.get("keys", []) if item.get("kid") == header.get("kid")); key = jwt.PyJWK.from_dict(key_data).key
        claims = jwt.decode(id_token, key, algorithms=[algorithm], audience=provider.client_id, issuer=provider.issuer_url)
    except (httpx.HTTPError, KeyError, StopIteration, ValueError, jwt.PyJWTError) as error:
        raise HTTPException(status_code=401, detail="The identity provider response could not be verified") from error
    if claims.get("nonce") != state_record.nonce: raise HTTPException(status_code=401, detail="The identity provider nonce did not match")
    email = str(claims.get("email", "")).strip().lower(); subject = str(claims.get("sub", ""))
    domain = email.rsplit("@", 1)[-1] if "@" in email else ""
    verified_domain = await session.scalar(select(IdentityProviderDomain.id).where(
        IdentityProviderDomain.provider_id == provider.id, IdentityProviderDomain.domain == domain,
        IdentityProviderDomain.status == "verified",
    ))
    if not subject or not email or claims.get("email_verified") is False or not verified_domain:
        raise HTTPException(status_code=403, detail="The SSO identity is not in a verified workspace domain")
    link = await session.scalar(select(ExternalIdentity).where(ExternalIdentity.provider_id == provider.id, ExternalIdentity.subject == subject))
    user = await session.get(User, link.user_id) if link else await session.scalar(select(User).where(User.email == email))
    if user and user.entity_id != provider.entity_id: raise HTTPException(status_code=409, detail="This email belongs to another workspace")
    if not user:
        if not provider.jit_enabled: raise HTTPException(status_code=403, detail="Your account has not been provisioned")
        await ensure_user_capacity(session, provider.entity_id, additional_reserved_seats=0)
        user = User(entity_id=provider.entity_id, email=email, display_name=str(claims.get("name") or email.split("@", 1)[0])[:100],
                    password_hash=hash_password(token_urlsafe(48)), role=provider.default_role, provisioning_source="oidc")
        session.add(user); await session.flush()
    if user.account_status != "active": raise HTTPException(status_code=403, detail="This account is suspended")
    if not link:
        link = ExternalIdentity(entity_id=provider.entity_id, provider_id=provider.id, user_id=user.id, subject=subject, email_at_link=email); session.add(link)
    link.last_login_at = now
    amr = claims.get("amr") or []; auth_level = "mfa" if any(item in {"mfa", "otp", "hwk"} for item in amr) else "sso"
    auth_session = await create_auth_session(session, user, request, settings, auth_level=auth_level)
    record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="auth.sso.login", target_type="identity_provider", target_id=provider.id, details={"session_id": auth_session.id, "auth_level": auth_level})
    await session.commit()
    response = RedirectResponse(f"{settings.frontend_url.rstrip('/')}{state_record.return_path}", status_code=302)
    set_session_cookie(response, user.id, settings, auth_session.id, utc(auth_session.expires_at)); return response


def token_hash(value: str) -> str: return sha256(value.encode()).hexdigest()


@identity_router.get("/scim/tokens")
async def list_scim_tokens(user: User = Depends(get_current_admin), session: AsyncSession = Depends(get_session)) -> list[dict]:
    rows = (await session.scalars(select(ScimAccessToken).where(ScimAccessToken.entity_id == user.entity_id).order_by(ScimAccessToken.created_at.desc()))).all()
    return [{"id": item.id, "name": item.name, "scopes": item.scopes, "created_at": as_utc(item.created_at), "expires_at": as_utc(item.expires_at) if item.expires_at else None, "last_used_at": as_utc(item.last_used_at) if item.last_used_at else None, "revoked_at": as_utc(item.revoked_at) if item.revoked_at else None} for item in rows]


@identity_router.post("/scim/tokens", status_code=201)
async def create_scim_token(payload: ScimTokenWrite, user: User = Depends(get_current_admin), session: AsyncSession = Depends(get_session)) -> dict:
    allowed = {"users:read", "users:write", "groups:read", "groups:write"}
    if not set(payload.scopes).issubset(allowed): raise HTTPException(status_code=422, detail="Unsupported SCIM scope")
    plaintext = f"wss_scim_{token_urlsafe(40)}"; now = datetime.now(timezone.utc)
    item = ScimAccessToken(entity_id=user.entity_id, name=payload.name, token_hash=token_hash(plaintext), scopes=payload.scopes, created_by_id=user.id,
                           expires_at=now + timedelta(days=payload.expires_in_days) if payload.expires_in_days else None)
    session.add(item); await session.flush(); record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="identity.scim_token.created", target_type="scim_token", target_id=item.id, details={"scopes": item.scopes}); await session.commit()
    return {"id": item.id, "name": item.name, "token": plaintext, "scopes": item.scopes, "expires_at": as_utc(item.expires_at) if item.expires_at else None}


@identity_router.delete("/scim/tokens/{token_id}", status_code=204)
async def revoke_scim_token(token_id: str, user: User = Depends(get_current_admin), session: AsyncSession = Depends(get_session)) -> None:
    item = await session.get(ScimAccessToken, token_id)
    if not item or item.entity_id != user.entity_id: raise HTTPException(status_code=404, detail="SCIM token not found")
    item.revoked_at = datetime.now(timezone.utc); record_audit_event(session, entity_id=user.entity_id, actor_id=user.id, action="identity.scim_token.revoked", target_type="scim_token", target_id=item.id); await session.commit()


async def scim_context(authorization: str | None = Header(default=None), session: AsyncSession = Depends(get_session)) -> tuple[ScimAccessToken, AsyncSession]:
    if not authorization or not authorization.startswith("Bearer "): raise HTTPException(status_code=401, detail="SCIM bearer token required")
    item = await session.scalar(select(ScimAccessToken).where(ScimAccessToken.token_hash == token_hash(authorization[7:].strip())))
    now = datetime.now(timezone.utc)
    if not item or item.revoked_at or (item.expires_at and utc(item.expires_at) <= now): raise HTTPException(status_code=401, detail="SCIM bearer token is invalid or expired")
    item.last_used_at = now; await session.commit(); return item, session


def require_scope(context: tuple[ScimAccessToken, AsyncSession], scope: str) -> tuple[ScimAccessToken, AsyncSession]:
    if scope not in context[0].scopes: raise HTTPException(status_code=403, detail="SCIM token lacks the required scope")
    return context


def scim_user(user: User) -> dict:
    return {"schemas": SCIM_SCHEMAS, "id": user.id, "userName": user.email, "displayName": user.display_name, "active": user.account_status == "active",
            "roles": [{"value": user.role, "primary": True}], "meta": {"resourceType": "User", "created": as_utc(user.created_at).isoformat(), "location": f"/scim/v2/Users/{user.id}"}}


@scim_router.get("/ServiceProviderConfig")
async def scim_config() -> dict:
    return {"schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"], "patch": {"supported": True}, "bulk": {"supported": False}, "filter": {"supported": True, "maxResults": 200}, "changePassword": {"supported": False}, "sort": {"supported": False}, "etag": {"supported": False}}


@scim_router.get("/Users")
async def list_scim_users(startIndex: int = 1, count: int = 100, filter: str | None = None, context: tuple[ScimAccessToken, AsyncSession] = Depends(scim_context)) -> dict:
    token, session = require_scope(context, "users:read"); query = select(User).where(User.entity_id == token.entity_id)
    match = re.fullmatch(r'userName eq "([^"]+)"', filter or "")
    if filter and not match: raise HTTPException(status_code=400, detail="Only userName eq filtering is supported")
    if match: query = query.where(User.email == match.group(1).strip().lower())
    rows = (await session.scalars(query.order_by(User.email).offset(max(0, startIndex - 1)).limit(min(200, max(1, count))))).all()
    total = len((await session.scalars(select(User.id).where(User.entity_id == token.entity_id))).all()) if not match else len(rows)
    return {"schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"], "totalResults": total, "startIndex": startIndex, "itemsPerPage": len(rows), "Resources": [scim_user(item) for item in rows]}


@scim_router.post("/Users", status_code=201)
async def create_scim_user(payload: dict, context: tuple[ScimAccessToken, AsyncSession] = Depends(scim_context)) -> dict:
    token, session = require_scope(context, "users:write"); email = str(payload.get("userName", "")).strip().lower()
    if "@" not in email: raise HTTPException(status_code=400, detail="userName must be an email address")
    if await session.scalar(select(User.id).where(User.email == email)): raise HTTPException(status_code=409, detail="A user with this userName already exists")
    await ensure_user_capacity(session, token.entity_id, additional_reserved_seats=0)
    roles = payload.get("roles") or []; role = str(roles[0].get("value", "basic")) if roles and isinstance(roles[0], dict) else "basic"
    if role not in {"admin", "basic", "guest"}: role = "basic"
    user = User(entity_id=token.entity_id, email=email, display_name=str(payload.get("displayName") or email.split("@", 1)[0])[:100],
                password_hash=hash_password(token_urlsafe(48)), role=role, account_status="active" if payload.get("active", True) else "suspended", provisioning_source="scim")
    session.add(user); await session.flush(); record_audit_event(session, entity_id=token.entity_id, actor_id=token.created_by_id, action="identity.scim.user_created", target_type="user", target_id=user.id); await session.commit(); await session.refresh(user); return scim_user(user)


async def scim_owned_user(user_id: str, token: ScimAccessToken, session: AsyncSession) -> User:
    user = await session.get(User, user_id)
    if not user or user.entity_id != token.entity_id: raise HTTPException(status_code=404, detail="SCIM user not found")
    return user


@scim_router.get("/Users/{user_id}")
async def get_scim_user(user_id: str, context: tuple[ScimAccessToken, AsyncSession] = Depends(scim_context)) -> dict:
    token, session = require_scope(context, "users:read"); return scim_user(await scim_owned_user(user_id, token, session))


@scim_router.patch("/Users/{user_id}")
async def patch_scim_user(user_id: str, payload: dict, context: tuple[ScimAccessToken, AsyncSession] = Depends(scim_context)) -> dict:
    token, session = require_scope(context, "users:write"); user = await scim_owned_user(user_id, token, session)
    original_role, original_status = user.role, user.account_status
    for operation in payload.get("Operations", []):
        if str(operation.get("op", "")).lower() not in {"add", "replace"}: continue
        path = operation.get("path"); value = operation.get("value")
        if path == "active": user.account_status = "active" if value else "suspended"
        elif path == "displayName": user.display_name = str(value)[:100]
        elif path == "userName": user.email = str(value).strip().lower()
        elif path == "roles" and value: user.role = str(value[0].get("value", "basic")) if str(value[0].get("value", "basic")) in {"admin", "basic", "guest"} else "basic"
        elif isinstance(value, dict):
            if "active" in value: user.account_status = "active" if value["active"] else "suspended"
            if "displayName" in value: user.display_name = str(value["displayName"])[:100]
    if user.provisioning_source == "local" and original_role == "admin" and (user.account_status != original_status or user.role != original_role):
        await session.rollback()
        raise HTTPException(status_code=409, detail="A locally managed administrator cannot be deprovisioned through SCIM")
    if user.account_status != "active":
        for item in (await session.scalars(select(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None)))).all(): item.revoked_at = datetime.now(timezone.utc)
    record_audit_event(session, entity_id=token.entity_id, actor_id=token.created_by_id, action="identity.scim.user_updated", target_type="user", target_id=user.id, details={"status": user.account_status}); await session.commit(); await session.refresh(user); return scim_user(user)


@scim_router.delete("/Users/{user_id}", status_code=204)
async def delete_scim_user(user_id: str, context: tuple[ScimAccessToken, AsyncSession] = Depends(scim_context)) -> None:
    token, session = require_scope(context, "users:write"); user = await scim_owned_user(user_id, token, session)
    if user.provisioning_source == "local" and user.role == "admin":
        raise HTTPException(status_code=409, detail="A locally managed administrator cannot be deprovisioned through SCIM")
    user.account_status = "suspended"
    for item in (await session.scalars(select(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None)))).all():
        item.revoked_at = datetime.now(timezone.utc)
    record_audit_event(session, entity_id=token.entity_id, actor_id=token.created_by_id, action="identity.scim.user_deprovisioned", target_type="user", target_id=user.id)
    await session.commit()


def scim_group(group: OrganizationUnit, members: list[OrganizationUnitMember]) -> dict:
    return {"schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"], "id": group.id, "displayName": group.name,
            "members": [{"value": item.user_id, "$ref": f"/scim/v2/Users/{item.user_id}"} for item in members], "meta": {"resourceType": "Group", "location": f"/scim/v2/Groups/{group.id}"}}


@scim_router.get("/Groups")
async def list_scim_groups(context: tuple[ScimAccessToken, AsyncSession] = Depends(scim_context)) -> dict:
    token, session = require_scope(context, "groups:read")
    groups = (await session.scalars(select(OrganizationUnit).where(
        OrganizationUnit.entity_id == token.entity_id,
        OrganizationUnit.unit_type == "group",
    ).order_by(OrganizationUnit.name))).all()
    resources = []
    for group in groups:
        members = (await session.scalars(select(OrganizationUnitMember).where(OrganizationUnitMember.unit_id == group.id))).all(); resources.append(scim_group(group, members))
    return {"schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"], "totalResults": len(resources), "startIndex": 1, "itemsPerPage": len(resources), "Resources": resources}


@scim_router.post("/Groups", status_code=201)
async def create_scim_group(payload: dict, context: tuple[ScimAccessToken, AsyncSession] = Depends(scim_context)) -> dict:
    token, session = require_scope(context, "groups:write"); name = str(payload.get("displayName", "")).strip()
    if not name: raise HTTPException(status_code=400, detail="displayName is required")
    group = OrganizationUnit(entity_id=token.entity_id, name=name[:140], unit_type="group", description="Provisioned by SCIM")
    session.add(group); await session.flush(); members = []
    seen = set()
    for entry in payload.get("members", []):
        user = await scim_owned_user(str(entry.get("value", "")), token, session)
        if user.id in seen: continue
        seen.add(user.id); member = OrganizationUnitMember(unit_id=group.id, user_id=user.id, membership_role="member", allocation_percent=0); session.add(member); members.append(member)
    record_audit_event(session, entity_id=token.entity_id, actor_id=token.created_by_id, action="identity.scim.group_created", target_type="unit", target_id=group.id)
    await session.commit(); return scim_group(group, members)


async def scim_owned_group(group_id: str, token: ScimAccessToken, session: AsyncSession) -> OrganizationUnit:
    group = await session.get(OrganizationUnit, group_id)
    if not group or group.entity_id != token.entity_id or group.unit_type != "group":
        raise HTTPException(status_code=404, detail="SCIM group not found")
    return group


@scim_router.get("/Groups/{group_id}")
async def get_scim_group(group_id: str, context: tuple[ScimAccessToken, AsyncSession] = Depends(scim_context)) -> dict:
    token, session = require_scope(context, "groups:read")
    group = await scim_owned_group(group_id, token, session)
    members = (await session.scalars(select(OrganizationUnitMember).where(OrganizationUnitMember.unit_id == group.id))).all()
    return scim_group(group, members)


@scim_router.patch("/Groups/{group_id}")
async def patch_scim_group(group_id: str, payload: dict, context: tuple[ScimAccessToken, AsyncSession] = Depends(scim_context)) -> dict:
    token, session = require_scope(context, "groups:write")
    group = await scim_owned_group(group_id, token, session)
    for operation in payload.get("Operations", []):
        if str(operation.get("op", "")).lower() not in {"add", "replace", "remove"}:
            continue
        path, value = operation.get("path"), operation.get("value")
        if path == "displayName" and value:
            group.name = str(value)[:140]
        elif path == "members":
            if str(operation.get("op", "")).lower() == "replace":
                await session.execute(delete(OrganizationUnitMember).where(OrganizationUnitMember.unit_id == group.id))
            for entry in value or []:
                member = await scim_owned_user(str(entry.get("value", "")), token, session)
                existing = await session.scalar(select(OrganizationUnitMember).where(
                    OrganizationUnitMember.unit_id == group.id,
                    OrganizationUnitMember.user_id == member.id,
                ))
                if str(operation.get("op", "")).lower() == "remove":
                    if existing: await session.delete(existing)
                elif not existing:
                    session.add(OrganizationUnitMember(unit_id=group.id, user_id=member.id, membership_role="member", allocation_percent=0))
    record_audit_event(session, entity_id=token.entity_id, actor_id=token.created_by_id, action="identity.scim.group_updated", target_type="unit", target_id=group.id)
    await session.commit()
    members = (await session.scalars(select(OrganizationUnitMember).where(OrganizationUnitMember.unit_id == group.id))).all()
    return scim_group(group, members)


@scim_router.delete("/Groups/{group_id}", status_code=204)
async def delete_scim_group(group_id: str, context: tuple[ScimAccessToken, AsyncSession] = Depends(scim_context)) -> None:
    token, session = require_scope(context, "groups:write")
    group = await scim_owned_group(group_id, token, session)
    record_audit_event(session, entity_id=token.entity_id, actor_id=token.created_by_id, action="identity.scim.group_deleted", target_type="unit", target_id=group.id)
    await session.delete(group); await session.commit()
