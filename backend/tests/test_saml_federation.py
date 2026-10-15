import asyncio
import base64
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from urllib.parse import parse_qs, quote_plus, unquote_plus, urlencode, urlparse
import zlib

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID
from lxml import etree
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.requests import Request

from backend.app.auth import hash_password
from backend.app.config import Settings
from backend.app.database import AuthSession, Base, Entity, IdentityProvider, IdentityProviderDomain, SamlAssertionReplay, SamlLogoutState, SsoAuthorizationState, User
from backend.app.identity_federation import (
    SAML_ASSERTION,
    SAML_PROTOCOL,
    SAML_STATUS_SUCCESS,
    SamlCertificateWrite,
    SamlProviderWrite,
    add_saml_certificate,
    change_saml_certificate,
    create_saml_provider,
    discover_saml_logout,
    public_https_url,
    saml_acs,
    saml_logout_callback,
    saml_metadata,
    start_oidc,
    start_saml_logout,
)
from backend.app.main import app
from signxml import XMLSigner, methods


def app_request(method: str = "GET", path: str = "/", query: str = "") -> Request:
    return Request({
        "type": "http", "method": method, "path": path, "root_path": "", "scheme": "https",
        "headers": [(b"user-agent", b"SAML federation test")], "query_string": query.encode(),
        "client": ("203.0.113.10", 44300), "server": ("workspace.example", 443), "router": app.router,
    })


def signing_material() -> tuple[bytes, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test Identity Provider")])
    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=365)).sign(key, hashes.SHA256())
    )
    private_pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    certificate_pem = certificate.public_bytes(serialization.Encoding.PEM).decode()
    return private_pem, certificate_pem


def signed_response(private_key: bytes, certificate: str, *, provider, state: SsoAuthorizationState, acs_url: str) -> str:
    now = datetime.now(timezone.utc)
    timestamp = lambda value: value.isoformat().replace("+00:00", "Z")
    response = etree.Element(f"{{{SAML_PROTOCOL}}}Response", nsmap={"samlp": SAML_PROTOCOL, "saml": SAML_ASSERTION}, ID="_response-1", Version="2.0", IssueInstant=timestamp(now), Destination=acs_url, InResponseTo=state.nonce)
    etree.SubElement(response, f"{{{SAML_ASSERTION}}}Issuer").text = provider.issuer_url
    status = etree.SubElement(response, f"{{{SAML_PROTOCOL}}}Status")
    etree.SubElement(status, f"{{{SAML_PROTOCOL}}}StatusCode", Value=SAML_STATUS_SUCCESS)
    assertion = etree.SubElement(response, f"{{{SAML_ASSERTION}}}Assertion", ID="_assertion-1", Version="2.0", IssueInstant=timestamp(now))
    etree.SubElement(assertion, f"{{{SAML_ASSERTION}}}Issuer").text = provider.issuer_url
    subject = etree.SubElement(assertion, f"{{{SAML_ASSERTION}}}Subject")
    etree.SubElement(subject, f"{{{SAML_ASSERTION}}}NameID").text = "saml-user-id"
    confirmation = etree.SubElement(subject, f"{{{SAML_ASSERTION}}}SubjectConfirmation", Method="urn:oasis:names:tc:SAML:2.0:cm:bearer")
    etree.SubElement(confirmation, f"{{{SAML_ASSERTION}}}SubjectConfirmationData", InResponseTo=state.nonce, Recipient=acs_url, NotOnOrAfter=timestamp(now + timedelta(minutes=5)))
    conditions = etree.SubElement(assertion, f"{{{SAML_ASSERTION}}}Conditions", NotBefore=timestamp(now - timedelta(minutes=1)), NotOnOrAfter=timestamp(now + timedelta(minutes=5)))
    audience_restriction = etree.SubElement(conditions, f"{{{SAML_ASSERTION}}}AudienceRestriction")
    etree.SubElement(audience_restriction, f"{{{SAML_ASSERTION}}}Audience").text = provider.client_id
    authn = etree.SubElement(assertion, f"{{{SAML_ASSERTION}}}AuthnStatement", AuthnInstant=timestamp(now), SessionIndex="saml-session-1")
    context = etree.SubElement(authn, f"{{{SAML_ASSERTION}}}AuthnContext")
    etree.SubElement(context, f"{{{SAML_ASSERTION}}}AuthnContextClassRef").text = "urn:oasis:names:tc:SAML:2.0:ac:classes:PasswordProtectedTransport"
    statement = etree.SubElement(assertion, f"{{{SAML_ASSERTION}}}AttributeStatement")
    email = etree.SubElement(statement, f"{{{SAML_ASSERTION}}}Attribute", Name="email")
    etree.SubElement(email, f"{{{SAML_ASSERTION}}}AttributeValue").text = "new.saml@acme.test"
    display_name = etree.SubElement(statement, f"{{{SAML_ASSERTION}}}Attribute", Name="displayName")
    etree.SubElement(display_name, f"{{{SAML_ASSERTION}}}AttributeValue").text = "New SAML User"
    signed = XMLSigner(method=methods.enveloped, signature_algorithm="rsa-sha256", digest_algorithm="sha256").sign(
        response, key=private_key, cert=certificate, reference_uri="#_response-1",
    )
    return base64.b64encode(etree.tostring(signed)).decode()


def signed_redirect_query(private_key: bytes, message_key: str, xml: bytes, relay_state: str | None = None) -> str:
    compressor = zlib.compressobj(level=9, wbits=-15)
    encoded = base64.b64encode(compressor.compress(xml) + compressor.flush()).decode()
    parameters = [(message_key, encoded)]
    if relay_state is not None:
        parameters.append(("RelayState", relay_state))
    parameters.append(("SigAlg", "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"))
    signed_query = urlencode(parameters)
    key = serialization.load_pem_private_key(private_key, password=None)
    signature = key.sign(signed_query.encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{signed_query}&Signature={quote_plus(base64.b64encode(signature).decode())}"


def test_saml_signed_round_trip_and_jit_provisioning() -> None:
    asyncio.run(exercise_saml_round_trip())


async def exercise_saml_round_trip() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    settings = Settings(auth_secret="saml-test-secret-that-is-longer-than-thirty-two-bytes", frontend_url="https://workspace.example")
    private_key, certificate = signing_material()
    _, replacement_certificate = signing_material()

    try:
        await public_https_url("https://127.0.0.1/metadata.xml")
        raise AssertionError("Private metadata URL was accepted")
    except HTTPException as error:
        assert error.status_code == 422

    async with sessions() as session:
        entity = Entity(id="41111111-1111-1111-1111-111111111111", name="Acme")
        admin = User(id="42222222-2222-2222-2222-222222222222", entity_id=entity.id, email="admin@acme.test", display_name="Admin", password_hash=hash_password("SecurePass123!"), role="admin")
        session.add_all([entity, admin])
        await session.commit()
        created = await create_saml_provider(SamlProviderWrite(
            name="Acme SAML", idp_entity_id="https://idp.acme.test/metadata", sso_url="https://idp.acme.test/saml/sso",
            slo_url="https://idp.acme.test/saml/logout", x509_certificate=certificate,
            sp_entity_id="https://workspace.example/saml/metadata", enabled=True,
        ), app_request("POST", "/api/v1/identity/saml/providers"), admin, session, settings)
        provider_id = created["id"]
        assert created["has_sp_signing_key"] is True
        assert len(created["signing_certificates"]) == 1
        replacement = await add_saml_certificate(provider_id, SamlCertificateWrite(x509_certificate=replacement_certificate), admin, session, settings)
        assert replacement["status"] == "active"
        original_certificate_id = created["signing_certificates"][0]["id"]
        retired = await change_saml_certificate(provider_id, original_certificate_id, "retire", admin, session)
        assert retired["status"] == "retiring"
        domain = IdentityProviderDomain(provider_id=provider_id, entity_id=entity.id, domain="acme.test", status="verified", token_hash="verified")
        session.add(domain)
        await session.commit()

        metadata = await saml_metadata(provider_id, app_request("GET", f"/api/v1/auth/sso/{provider_id}/metadata"), session)
        assert b"WantAssertionsSigned=\"true\"" in metadata.body
        rejected_redirect = await start_oidc(provider_id, app_request("GET", f"/api/v1/auth/sso/{provider_id}/start"), "/", session, settings)
        rejected_state = parse_qs(urlparse(rejected_redirect.headers["location"]).query)["RelayState"][0]
        unsigned = base64.b64encode(f'<samlp:Response xmlns:samlp="{SAML_PROTOCOL}" ID="_unsigned"/>'.encode()).decode()
        try:
            await saml_acs(provider_id, app_request("POST", f"/api/v1/auth/sso/{provider_id}/acs"), unsigned, rejected_state, session, settings)
            raise AssertionError("An unsigned SAML response was accepted")
        except HTTPException as error:
            assert error.status_code == 401

        redirect = await start_oidc(provider_id, app_request("GET", f"/api/v1/auth/sso/{provider_id}/start"), "/workflows", session, settings)
        query = parse_qs(urlparse(redirect.headers["location"]).query)
        assert query["SAMLRequest"]
        assert query["SigAlg"]
        raw_query = urlparse(redirect.headers["location"]).query
        signed_query, encoded_signature = raw_query.rsplit("&Signature=", 1)
        relay_state = query["RelayState"][0]
        state = await session.scalar(select(SsoAuthorizationState).where(SsoAuthorizationState.state_hash == sha256(relay_state.encode()).hexdigest()))
        provider = await session.get(IdentityProvider, provider_id)
        sp_certificate = x509.load_pem_x509_certificate(provider.saml_sp_certificate.encode())
        sp_certificate.public_key().verify(base64.b64decode(unquote_plus(encoded_signature)), signed_query.encode(), padding.PKCS1v15(), hashes.SHA256())
        acs_request = app_request("POST", f"/api/v1/auth/sso/{provider_id}/acs")
        acs_url = str(acs_request.url_for("saml_acs", provider_id=provider_id))
        response = await saml_acs(provider_id, acs_request, signed_response(private_key, certificate, provider=provider, state=state, acs_url=acs_url), relay_state, session, settings)
        assert response.status_code == 302
        assert response.headers["location"] == "https://workspace.example/workflows"
        user = await session.scalar(select(User).where(User.email == "new.saml@acme.test"))
        assert user and user.provisioning_source == "saml"
        assert await session.scalar(select(SamlAssertionReplay.id).where(SamlAssertionReplay.assertion_id == "_assertion-1"))
        auth_session = await session.scalar(select(AuthSession).where(AuthSession.user_id == user.id))
        assert auth_session.identity_provider_id == provider_id
        assert auth_session.external_session_index == "saml-session-1"

        logout_request = app_request("GET", f"/api/v1/auth/sso/{provider_id}/logout/start")
        logout_request.state.auth_session = auth_session
        discovery = await discover_saml_logout(logout_request, user, session)
        assert discovery["available"] is True
        logout_redirect = await start_saml_logout(provider_id, logout_request, "/", user, session, settings)
        logout_query = parse_qs(urlparse(logout_redirect.headers["location"]).query)
        assert logout_query["SAMLRequest"] and logout_query["Signature"]
        logout_relay = logout_query["RelayState"][0]
        logout_state = await session.scalar(select(SamlLogoutState).where(SamlLogoutState.state_hash == sha256(logout_relay.encode()).hexdigest()))
        callback_url = f"https://workspace.example/api/v1/auth/sso/{provider_id}/logout/callback"
        now = datetime.now(timezone.utc)
        logout_response = etree.Element(f"{{{SAML_PROTOCOL}}}LogoutResponse", ID="_logout-response-1", Version="2.0", IssueInstant=now.isoformat().replace("+00:00", "Z"), Destination=callback_url, InResponseTo=logout_state.request_id)
        etree.SubElement(logout_response, f"{{{SAML_ASSERTION}}}Issuer").text = provider.issuer_url
        logout_status = etree.SubElement(logout_response, f"{{{SAML_PROTOCOL}}}Status")
        etree.SubElement(logout_status, f"{{{SAML_PROTOCOL}}}StatusCode", Value=SAML_STATUS_SUCCESS)
        callback_query = signed_redirect_query(private_key, "SAMLResponse", etree.tostring(logout_response), logout_relay)
        completed = await saml_logout_callback(provider_id, app_request("GET", f"/api/v1/auth/sso/{provider_id}/logout/callback", callback_query), session, settings)
        assert completed.status_code == 302
        await session.refresh(auth_session)
        assert auth_session.revoked_at is not None

        idp_session = AuthSession(
            user_id=user.id, entity_id=entity.id, auth_level="sso", expires_at=now + timedelta(hours=1),
            identity_provider_id=provider_id, external_session_index="idp-session-2", external_subject="saml-user-id",
        )
        session.add(idp_session)
        await session.commit()
        idp_logout = etree.Element(f"{{{SAML_PROTOCOL}}}LogoutRequest", ID="_idp-logout-1", Version="2.0", IssueInstant=now.isoformat().replace("+00:00", "Z"), Destination=callback_url)
        etree.SubElement(idp_logout, f"{{{SAML_ASSERTION}}}Issuer").text = provider.issuer_url
        etree.SubElement(idp_logout, f"{{{SAML_ASSERTION}}}NameID").text = "saml-user-id"
        etree.SubElement(idp_logout, f"{{{SAML_PROTOCOL}}}SessionIndex").text = "idp-session-2"
        idp_query = signed_redirect_query(private_key, "SAMLRequest", etree.tostring(idp_logout), "idp-relay")
        idp_completed = await saml_logout_callback(provider_id, app_request("GET", f"/api/v1/auth/sso/{provider_id}/logout/callback", idp_query), session, settings)
        await session.refresh(idp_session)
        assert idp_session.revoked_at is not None
        idp_response_query = urlparse(idp_completed.headers["location"]).query
        idp_signed_query, idp_encoded_signature = idp_response_query.rsplit("&Signature=", 1)
        sp_certificate.public_key().verify(base64.b64decode(unquote_plus(idp_encoded_signature)), idp_signed_query.encode(), padding.PKCS1v15(), hashes.SHA256())

        revoked = await change_saml_certificate(provider_id, original_certificate_id, "revoke", admin, session)
        assert revoked["status"] == "revoked"
        try:
            await change_saml_certificate(provider_id, replacement["id"], "revoke", admin, session)
            raise AssertionError("The final usable SAML certificate was revoked")
        except HTTPException as error:
            assert error.status_code == 409

    await engine.dispose()
