from collections.abc import AsyncIterator
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from uuid import uuid4

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, LargeBinary, String, Text, UniqueConstraint, event, inspect, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.types import JSON

from .config import get_settings


settings = get_settings()
EXPECTED_DATABASE_REVISION = "20260915_29"
engine = create_async_engine(settings.database_url, pool_pre_ping=True)
session_factory = async_sessionmaker(engine, expire_on_commit=False)

if engine.url.get_backend_name() == "sqlite":
    @event.listens_for(engine.sync_engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


class Base(DeclarativeBase):
    pass


class Entity(Base):
    __tablename__ = "entities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    max_users: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    max_projects: Mapped[int] = mapped_column(Integer, nullable=False, default=1_000)
    max_storage_bytes: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=10 * 1024 * 1024 * 1024
    )
    max_monthly_generations: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1_000
    )
    max_pending_generations: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    work_columns: Mapped[list | None] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True
    )
    work_item_types: Mapped[list | None] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True
    )
    data_region: Mapped[str] = mapped_column(String(40), nullable=False, default="us-central")
    data_residency_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    governance_settings: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("entities.id"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="admin")
    job_title: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    manager_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    skills: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    weekly_capacity_hours: Mapped[float] = mapped_column(Float, nullable=False, default=40)
    profile: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    account_status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)
    provisioning_source: Mapped[str] = mapped_column(String(20), nullable=False, default="local")
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    mfa_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    mfa_recovery_hashes: Mapped[list] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        Index("ix_auth_sessions_user_active", "user_id", "revoked_at", "expires_at"),
        Index("ix_auth_sessions_entity_created", "entity_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    entity_id: Mapped[str] = mapped_column(String(36), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)
    user_agent: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    ip_digest: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    auth_level: Mapped[str] = mapped_column(String(20), nullable=False, default="password")
    identity_provider_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("identity_providers.id", ondelete="SET NULL"), nullable=True, index=True)
    external_session_index: Mapped[str | None] = mapped_column(String(500), nullable=True, index=True)
    external_subject: Mapped[str | None] = mapped_column(String(500), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)


class IdentityProvider(Base):
    __tablename__ = "identity_providers"
    __table_args__ = (UniqueConstraint("entity_id", "name", name="uq_identity_provider_entity_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(String(36), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    protocol: Mapped[str] = mapped_column(String(20), nullable=False, default="oidc")
    issuer_url: Mapped[str] = mapped_column(String(500), nullable=False)
    client_id: Mapped[str] = mapped_column(String(300), nullable=False)
    client_secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    scopes: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=lambda: ["openid", "profile", "email"])
    saml_sso_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    saml_slo_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    saml_email_attribute: Mapped[str | None] = mapped_column(String(500), nullable=True)
    saml_sign_authn_requests: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    saml_sp_private_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    saml_sp_certificate: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enforce_sso: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    jit_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    default_role: Mapped[str] = mapped_column(String(20), nullable=False, default="basic")
    allow_admin_password_fallback: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)


class IdentityProviderDomain(Base):
    __tablename__ = "identity_provider_domains"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    provider_id: Mapped[str] = mapped_column(String(36), ForeignKey("identity_providers.id", ondelete="CASCADE"), nullable=False, index=True)
    entity_id: Mapped[str] = mapped_column(String(36), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)
    domain: Mapped[str] = mapped_column(String(253), nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ExternalIdentity(Base):
    __tablename__ = "external_identities"
    __table_args__ = (
        UniqueConstraint("provider_id", "subject", name="uq_external_identity_provider_subject"),
        UniqueConstraint("provider_id", "user_id", name="uq_external_identity_provider_user"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(String(36), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)
    provider_id: Mapped[str] = mapped_column(String(36), ForeignKey("identity_providers.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    email_at_link: Mapped[str] = mapped_column(String(320), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SsoAuthorizationState(Base):
    __tablename__ = "sso_authorization_states"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    provider_id: Mapped[str] = mapped_column(String(36), ForeignKey("identity_providers.id", ondelete="CASCADE"), nullable=False, index=True)
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    nonce: Mapped[str] = mapped_column(String(100), nullable=False)
    verifier_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    return_path: Mapped[str] = mapped_column(String(500), nullable=False, default="/")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SamlAssertionReplay(Base):
    __tablename__ = "saml_assertion_replays"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    provider_id: Mapped[str] = mapped_column(String(36), ForeignKey("identity_providers.id", ondelete="CASCADE"), nullable=False, index=True)
    assertion_id: Mapped[str] = mapped_column(String(500), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    consumed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class SamlSigningCertificate(Base):
    __tablename__ = "saml_signing_certificates"
    __table_args__ = (
        UniqueConstraint("provider_id", "fingerprint_sha256", name="uq_saml_certificate_provider_fingerprint"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    provider_id: Mapped[str] = mapped_column(String(36), ForeignKey("identity_providers.id", ondelete="CASCADE"), nullable=False, index=True)
    entity_id: Mapped[str] = mapped_column(String(36), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)
    certificate_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_by_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class SamlLogoutState(Base):
    __tablename__ = "saml_logout_states"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    provider_id: Mapped[str] = mapped_column(String(36), ForeignKey("identity_providers.id", ondelete="CASCADE"), nullable=False, index=True)
    auth_session_id: Mapped[str] = mapped_column(String(36), ForeignKey("auth_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    request_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    return_path: Mapped[str] = mapped_column(String(500), nullable=False, default="/")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SamlLogoutReplay(Base):
    __tablename__ = "saml_logout_replays"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    provider_id: Mapped[str] = mapped_column(String(36), ForeignKey("identity_providers.id", ondelete="CASCADE"), nullable=False, index=True)
    request_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    consumed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class ScimAccessToken(Base):
    __tablename__ = "scim_access_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(String(36), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    scopes: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=lambda: ["users:read", "users:write", "groups:read", "groups:write"])
    created_by_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        Index("ix_projects_entity_updated_id", "entity_id", "updated_at", "id"),
        Index("ix_projects_title", "title"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True, index=True
    )
    entity_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("entities.id"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    visibility: Mapped[str] = mapped_column(String(20), nullable=False, default="workspace")
    approval_status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    profile: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict
    )
    settings: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    source_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    graph: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc), nullable=False
    )


class ProjectCollaborator(Base):
    __tablename__ = "project_collaborators"

    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), primary_key=True, index=True
    )
    access_role: Mapped[str] = mapped_column(String(20), nullable=False, default="viewer")
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class ProjectRevision(Base):
    __tablename__ = "project_revisions"
    __table_args__ = (
        UniqueConstraint("project_id", "version", name="uq_project_revision_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    profile: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict
    )
    source_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    graph: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False)
    change_summary: Mapped[str] = mapped_column(String(240), nullable=False, default="Saved changes")
    created_by_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class ProjectApproval(Base):
    __tablename__ = "project_approvals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    revision_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("project_revisions.id", ondelete="CASCADE"), nullable=False,
        index=True,
    )
    requested_by_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    reviewer_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    request_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    decision_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("entities.id"), nullable=False, index=True
    )
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    actor_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(40), nullable=False, default="project")
    target_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    details: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict
    )
    request_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    previous_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False,
        index=True,
    )


class Invitation(Base):
    __tablename__ = "invitations"
    __table_args__ = (UniqueConstraint("entity_id", "email", name="uq_invitation_entity_email"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("entities.id"), nullable=False, index=True
    )
    invited_by_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    accepted_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    job_title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="basic")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    delivery_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc), nullable=False
    )


class ProjectMessage(Base):
    __tablename__ = "project_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class DirectMessage(Base):
    __tablename__ = "direct_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("entities.id"), nullable=False, index=True
    )
    sender_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    recipient_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    parent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("direct_messages.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reactions: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False, default=dict
    )
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    bookmark_user_ids: Mapped[list] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False, default=list
    )
    attachments: Mapped[list] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False, default=list
    )
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class CommunicationChannel(Base):
    __tablename__ = "communication_channels"
    __table_args__ = (
        UniqueConstraint("entity_id", "name", name="uq_communication_channel_entity_name"),
        Index("ix_communication_channels_entity_created", "entity_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("entities.id"), nullable=False, index=True
    )
    created_by_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    channel_type: Mapped[str] = mapped_column(String(20), nullable=False, default="channel")
    visibility: Mapped[str] = mapped_column(String(20), nullable=False, default="workspace")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc), nullable=False
    )


class CommunicationChannelMember(Base):
    __tablename__ = "communication_channel_members"
    __table_args__ = (
        UniqueConstraint("channel_id", "user_id", name="uq_communication_channel_member"),
        Index("ix_communication_channel_members_user_channel", "user_id", "channel_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    channel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("communication_channels.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="member")
    last_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class CommunicationChannelMessage(Base):
    __tablename__ = "communication_channel_messages"
    __table_args__ = (
        Index("ix_communication_channel_messages_channel_created", "channel_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("entities.id"), nullable=False, index=True
    )
    channel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("communication_channels.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sender_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    parent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("communication_channel_messages.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reactions: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False, default=dict
    )
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    bookmark_user_ids: Mapped[list] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False, default=list
    )
    attachments: Mapped[list] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False, default=list
    )
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class KnowledgeSpace(Base):
    __tablename__ = "knowledge_spaces"
    __table_args__ = (
        UniqueConstraint("entity_id", "name", name="uq_knowledge_space_entity_name"),
        Index("ix_knowledge_spaces_entity_updated", "entity_id", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(String(36), ForeignKey("entities.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    visibility: Mapped[str] = mapped_column(String(20), nullable=False, default="workspace")
    created_by_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)


class KnowledgeSpaceMember(Base):
    __tablename__ = "knowledge_space_members"
    __table_args__ = (UniqueConstraint("space_id", "user_id", name="uq_knowledge_space_member"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    space_id: Mapped[str] = mapped_column(String(36), ForeignKey("knowledge_spaces.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="viewer")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        Index("ix_knowledge_documents_entity_updated", "entity_id", "updated_at"),
        Index("ix_knowledge_documents_space_updated", "space_id", "updated_at"),
        UniqueConstraint("entity_id", "slug", name="uq_knowledge_document_entity_slug"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(String(36), ForeignKey("entities.id"), nullable=False, index=True)
    space_id: Mapped[str] = mapped_column(String(36), ForeignKey("knowledge_spaces.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    parent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("knowledge_documents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    slug: Mapped[str] = mapped_column(String(220), nullable=False)
    summary: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    visibility: Mapped[str] = mapped_column(String(20), nullable=False, default="workspace")
    classification: Mapped[str] = mapped_column(String(20), nullable=False, default="internal")
    template: Mapped[str] = mapped_column(String(40), nullable=False, default="blank")
    icon: Mapped[str] = mapped_column(String(16), nullable=False, default="▤")
    labels: Mapped[list] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list
    )
    watcher_ids: Mapped[list] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=1024)
    review_due_at: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    expires_at: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)


class KnowledgeDocumentAccess(Base):
    __tablename__ = "knowledge_document_access"
    __table_args__ = (UniqueConstraint("document_id", "user_id", name="uq_knowledge_document_access"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="viewer")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class KnowledgeDocumentRevision(Base):
    __tablename__ = "knowledge_document_revisions"
    __table_args__ = (UniqueConstraint("document_id", "version", name="uq_knowledge_document_revision_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    summary: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    classification: Mapped[str] = mapped_column(String(20), nullable=False)
    change_summary: Mapped[str] = mapped_column(String(240), nullable=False, default="Saved changes")
    created_by_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class KnowledgeComment(Base):
    __tablename__ = "knowledge_comments"
    __table_args__ = (Index("ix_knowledge_comments_document_created", "document_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    author_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    parent_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("knowledge_comments.id", ondelete="SET NULL"), nullable=True, index=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)


class KnowledgeDocumentLink(Base):
    __tablename__ = "knowledge_document_links"
    __table_args__ = (UniqueConstraint("source_document_id", "target_document_id", name="uq_knowledge_document_link"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    source_document_id: Mapped[str] = mapped_column(String(36), ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    target_document_id: Mapped[str] = mapped_column(String(36), ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class OrganizationUnit(Base):
    __tablename__ = "organization_units"
    __table_args__ = (UniqueConstraint("entity_id", "name", "unit_type", name="uq_org_unit_entity_name_type"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(String(36), ForeignKey("entities.id"), nullable=False, index=True)
    parent_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("organization_units.id", ondelete="SET NULL"), nullable=True, index=True)
    manager_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(140), nullable=False)
    unit_type: Mapped[str] = mapped_column(String(24), nullable=False, default="team")
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    weekly_capacity_hours: Mapped[float] = mapped_column(Float, nullable=False, default=40)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)


class OrganizationUnitMember(Base):
    __tablename__ = "organization_unit_members"
    __table_args__ = (UniqueConstraint("unit_id", "user_id", name="uq_org_unit_member"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    unit_id: Mapped[str] = mapped_column(String(36), ForeignKey("organization_units.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    membership_role: Mapped[str] = mapped_column(String(24), nullable=False, default="member")
    allocation_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class ProjectGroupAccess(Base):
    __tablename__ = "project_group_access"
    __table_args__ = (UniqueConstraint("project_id", "unit_id", name="uq_project_group_access"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    unit_id: Mapped[str] = mapped_column(String(36), ForeignKey("organization_units.id", ondelete="CASCADE"), nullable=False, index=True)
    access_role: Mapped[str] = mapped_column(String(20), nullable=False, default="viewer")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class ObjectRelationship(Base):
    __tablename__ = "object_relationships"
    __table_args__ = (
        UniqueConstraint("entity_id", "source_type", "source_id", "target_type", "target_id", "relationship_type", name="uq_object_relationship"),
        Index("ix_object_relationships_source", "entity_id", "source_type", "source_id"),
        Index("ix_object_relationships_target", "entity_id", "target_type", "target_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(String(36), ForeignKey("entities.id"), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_id: Mapped[str] = mapped_column(String(80), nullable=False)
    target_type: Mapped[str] = mapped_column(String(40), nullable=False)
    target_id: Mapped[str] = mapped_column(String(80), nullable=False)
    relationship_type: Mapped[str] = mapped_column(String(40), nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    created_by_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class ObjectRelationshipHistory(Base):
    __tablename__ = "object_relationship_history"
    __table_args__ = (
        Index("ix_relationship_history_entity_relationship", "entity_id", "relationship_id", "created_at"),
        Index("ix_relationship_history_object", "entity_id", "source_type", "source_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(String(36), ForeignKey("entities.id"), nullable=False, index=True)
    relationship_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_id: Mapped[str] = mapped_column(String(80), nullable=False)
    target_type: Mapped[str] = mapped_column(String(40), nullable=False)
    target_id: Mapped[str] = mapped_column(String(80), nullable=False)
    relationship_type: Mapped[str] = mapped_column(String(40), nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    actor_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class ChangeProposal(Base):
    """A reviewed, idempotent and reversible mutation of the canonical work graph."""

    __tablename__ = "change_proposals"
    __table_args__ = (
        UniqueConstraint("entity_id", "idempotency_key", name="uq_change_proposal_entity_idempotency"),
        Index("ix_change_proposals_entity_status_updated", "entity_id", "status", "updated_at"),
        Index("ix_change_proposals_target", "entity_id", "target_type", "target_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(String(36), ForeignKey("entities.id"), nullable=False, index=True)
    created_by_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    reviewed_by_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    applied_by_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    rolled_back_by_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    target_type: Mapped[str] = mapped_column(String(40), nullable=False, default="relationship")
    target_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    operations: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    preview: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    evidence: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    before_snapshot: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    after_snapshot: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    decision_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    failure_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)


class SavedSearch(Base):
    __tablename__ = "saved_searches"
    __table_args__ = (
        UniqueConstraint("owner_id", "name", name="uq_saved_search_owner_name"),
        Index("ix_saved_searches_entity_owner", "entity_id", "owner_id", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(String(36), ForeignKey("entities.id"), nullable=False, index=True)
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    query: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="keyword")
    filters: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    shared: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)


class RecentSearch(Base):
    __tablename__ = "recent_searches"
    __table_args__ = (
        Index("ix_recent_searches_user_searched", "user_id", "searched_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(String(36), ForeignKey("entities.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    query: Mapped[str] = mapped_column(String(500), nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="keyword")
    filters: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    searched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)


class ProjectRisk(Base):
    __tablename__ = "project_risks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(String(36), ForeignKey("entities.id"), nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    probability: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    impact: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open")
    mitigation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)


class ProjectDecision(Base):
    __tablename__ = "project_decisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(String(36), ForeignKey("entities.id"), nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    context: Mapped[str] = mapped_column(Text, nullable=False, default="")
    decision: Mapped[str] = mapped_column(Text, nullable=False, default="")
    alternatives: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    consequences: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="proposed")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"
    __table_args__ = (UniqueConstraint("user_id", "kind", name="uq_notification_preference_user_kind"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    in_app: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    email: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    push: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    digest: Mapped[str] = mapped_column(String(20), nullable=False, default="none")
    muted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class SavedWorkspaceView(Base):
    __tablename__ = "saved_workspace_views"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(String(36), ForeignKey("entities.id"), nullable=False, index=True)
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    view_type: Mapped[str] = mapped_column(String(40), nullable=False)
    scope_type: Mapped[str] = mapped_column(String(40), nullable=False, default="workspace")
    scope_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    config: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    shared: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)


class WorkspaceDashboard(Base):
    __tablename__ = "workspace_dashboards"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(String(36), ForeignKey("entities.id"), nullable=False, index=True)
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    layout: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    widgets: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    shared: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    delivery: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)


class WorkspaceFile(Base):
    __tablename__ = "workspace_files"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(String(36), ForeignKey("entities.id"), nullable=False, index=True)
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    parent_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("workspace_files.id", ondelete="CASCADE"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    item_type: Mapped[str] = mapped_column(String(20), nullable=False, default="file")
    mime_type: Mapped[str] = mapped_column(String(160), nullable=False, default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    external_url: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    provider: Mapped[str] = mapped_column(String(40), nullable=False, default="workspace")
    classification: Mapped[str] = mapped_column(String(24), nullable=False, default="internal")
    tags: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    visibility: Mapped[str] = mapped_column(String(20), nullable=False, default="workspace")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    preview_url: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    shared_with_ids: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)


class ApprovalDefinition(Base):
    __tablename__ = "approval_definitions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(String(36), ForeignKey("entities.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    target_types: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    stages: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    reminder_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=24)
    escalation_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=72)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class ApprovalInstance(Base):
    __tablename__ = "approval_instances"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(String(36), ForeignKey("entities.id"), nullable=False, index=True)
    definition_id: Mapped[str] = mapped_column(String(36), ForeignKey("approval_definitions.id", ondelete="SET NULL"), nullable=True, index=True)
    target_type: Mapped[str] = mapped_column(String(40), nullable=False)
    target_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    requested_by_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    current_stage: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    decisions: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    delegated_to_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)


class CalendarEvent(Base):
    __tablename__ = "calendar_events"
    __table_args__ = (
        Index("ix_calendar_events_entity_start", "entity_id", "starts_at"),
        Index("ix_calendar_events_organizer_start", "organizer_id", "starts_at"),
        Index("ix_calendar_events_series_start", "series_id", "starts_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("entities.id"), nullable=False, index=True
    )
    organizer_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    event_type: Mapped[str] = mapped_column(String(20), nullable=False, default="meeting")
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    all_day: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    location: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    meeting_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    agenda: Mapped[str] = mapped_column(Text, nullable=False, default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    action_items: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    transcript: Mapped[str] = mapped_column(Text, nullable=False, default="")
    recording_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="scheduled")
    series_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    recurrence_frequency: Mapped[str | None] = mapped_column(String(20), nullable=True)
    recurrence_interval: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    recurrence_ends_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    recurrence_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    occurrence_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc), nullable=False
    )


class CalendarEventAttendee(Base):
    __tablename__ = "calendar_event_attendees"
    __table_args__ = (
        UniqueConstraint("event_id", "user_id", name="uq_calendar_event_attendee"),
        Index("ix_calendar_event_attendees_user_event", "user_id", "event_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    event_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("calendar_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    response: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reminder_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True, default=15)
    reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class CalendarEventExternalAttendee(Base):
    __tablename__ = "calendar_event_external_attendees"
    __table_args__ = (
        UniqueConstraint("event_id", "email", name="uq_calendar_event_external_attendee"),
        Index("ix_calendar_external_attendees_event_status", "event_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    event_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("calendar_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    response: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    delivery_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc), nullable=False
    )


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("entities.id"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    actor_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    project_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    contact_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    calendar_event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("calendar_events.id", ondelete="CASCADE"), nullable=True, index=True
    )
    work_item_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("work_items.id", ondelete="CASCADE"), nullable=True, index=True
    )
    communication_channel_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("communication_channels.id", ondelete="CASCADE"), nullable=True, index=True
    )
    communication_message_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    document_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=True, index=True
    )
    group_key: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class ProjectNote(Base):
    __tablename__ = "project_notes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    author_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    node_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class ProjectDeliverable(Base):
    __tablename__ = "project_deliverables"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    creator_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    owner_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="planned")
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    node_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc), nullable=False
    )


class ProjectTask(Base):
    __tablename__ = "project_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    creator_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    assignee_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True, index=True
    )
    deliverable_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("project_deliverables.id", ondelete="SET NULL"), nullable=True,
        index=True,
    )
    node_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    details: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="todo")
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="medium")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc), nullable=False
    )


class AgileSprint(Base):
    __tablename__ = "agile_sprints"
    __table_args__ = (
        Index("ix_agile_sprints_entity_status", "entity_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("entities.id"), nullable=False, index=True
    )
    created_by_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    goal: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="planned")
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    capacity_points: Mapped[int | None] = mapped_column(Integer, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc), nullable=False
    )


class AgileRelease(Base):
    __tablename__ = "agile_releases"
    __table_args__ = (
        Index("ix_agile_releases_entity_status", "entity_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("entities.id"), nullable=False, index=True
    )
    created_by_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="planned")
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    baseline: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    scenario: Mapped[str] = mapped_column(String(40), nullable=False, default="committed")
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc), nullable=False
    )


class WorkItem(Base):
    __tablename__ = "work_items"
    __table_args__ = (
        UniqueConstraint("entity_id", "sequence_number", name="uq_work_item_entity_sequence"),
        UniqueConstraint("entity_id", "key", name="uq_work_item_entity_key"),
        Index("ix_work_items_entity_status_rank", "entity_id", "status", "rank"),
        Index("ix_work_items_entity_sprint_rank", "entity_id", "sprint_id", "rank"),
        Index("ix_work_items_entity_assignee_status", "entity_id", "assignee_id", "status"),
        Index("ix_work_items_project_node", "project_id", "node_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("entities.id"), nullable=False, index=True
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    key: Mapped[str] = mapped_column(String(24), nullable=False)
    reporter_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    assignee_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True, index=True
    )
    owner_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True, index=True
    )
    sprint_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agile_sprints.id", ondelete="SET NULL"), nullable=True, index=True
    )
    release_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agile_releases.id", ondelete="SET NULL"), nullable=True, index=True
    )
    project_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    parent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("work_items.id", ondelete="SET NULL"), nullable=True, index=True
    )
    node_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    item_type: Mapped[str] = mapped_column(String(40), nullable=False, default="task")
    summary: Mapped[str] = mapped_column(String(180), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    acceptance_criteria: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="backlog")
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="medium")
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="none")
    story_points: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimate_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    component: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    team: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    labels: Mapped[list] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list
    )
    checklist: Mapped[list] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list
    )
    watcher_ids: Mapped[list] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list
    )
    custom_fields: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    rank: Mapped[float] = mapped_column(Float, nullable=False, default=1024)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc), nullable=False
    )


class NodePlanningBinding(Base):
    __tablename__ = "node_planning_bindings"
    __table_args__ = (
        UniqueConstraint("project_id", "node_id", name="uq_node_planning_project_node"),
        Index("ix_node_planning_entity_project", "entity_id", "project_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("entities.id"), nullable=False, index=True
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    node_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    primary_work_item_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("work_items.id", ondelete="SET NULL"), nullable=True, index=True
    )
    sprint_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agile_sprints.id", ondelete="SET NULL"), nullable=True, index=True
    )
    subflow_project_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_by_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc), nullable=False
    )


class WorkItemComment(Base):
    __tablename__ = "work_item_comments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("entities.id"), nullable=False, index=True
    )
    work_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    author_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    parent_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("work_item_comments.id", ondelete="SET NULL"), nullable=True, index=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    reactions: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    attachments: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class WorkItemLink(Base):
    __tablename__ = "work_item_links"
    __table_args__ = (
        UniqueConstraint("source_id", "target_id", "link_type", name="uq_work_item_link"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("entities.id"), nullable=False, index=True
    )
    source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    link_type: Mapped[str] = mapped_column(String(24), nullable=False, default="relates_to")
    created_by_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class WorkItemActivity(Base):
    __tablename__ = "work_item_activity"
    __table_args__ = (
        Index("ix_work_item_activity_item_created", "work_item_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("entities.id"), nullable=False, index=True
    )
    work_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    changes: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class ProjectAttachment(Base):
    __tablename__ = "project_attachments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("entities.id"), nullable=False, index=True
    )
    uploaded_by_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    node_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    filename: Mapped[str] = mapped_column(String(240), nullable=False)
    content_type: Mapped[str] = mapped_column(String(160), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(900), nullable=True, unique=True)
    upload_status: Mapped[str] = mapped_column(String(20), nullable=False, default="complete")
    scan_status: Mapped[str] = mapped_column(String(20), nullable=False, default="clean", index=True)
    scan_message: Mapped[str | None] = mapped_column(String(240), nullable=True)
    object_etag: Mapped[str | None] = mapped_column(String(160), nullable=True)
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class BackgroundJob(Base):
    __tablename__ = "background_jobs"
    __table_args__ = (
        Index("ix_background_jobs_claim", "status", "available_at", "created_at"),
        Index("ix_background_jobs_entity_created", "entity_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("entities.id"), nullable=False, index=True
    )
    created_by_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued", index=True)
    payload: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict
    )
    result: Mapped[dict | None] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc), nullable=False
    )


class GeneratedArtifact(Base):
    __tablename__ = "generated_artifacts"
    __table_args__ = (
        Index("ix_generated_artifacts_entity_created", "entity_id", "created_at"),
        Index("ix_generated_artifacts_project_created", "project_id", "created_at"),
        Index("ix_generated_artifacts_expires", "expires_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("entities.id"), nullable=False, index=True
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("background_jobs.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
    )
    created_by_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    format: Mapped[str] = mapped_column(String(20), nullable=False)
    filename: Mapped[str] = mapped_column(String(240), nullable=False)
    content_type: Mapped[str] = mapped_column(String(160), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(900), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class ProcessEventImport(Base):
    __tablename__ = "process_event_imports"
    __table_args__ = (
        Index("ix_process_event_imports_project_created", "project_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("entities.id"), nullable=False, index=True
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    imported_by_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(240), nullable=False)
    event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    case_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    activity_node_map: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class ProcessEvent(Base):
    __tablename__ = "process_events"
    __table_args__ = (
        Index("ix_process_events_project_occurred", "project_id", "occurred_at"),
        Index("ix_process_events_project_case_occurred", "project_id", "case_id", "occurred_at"),
        Index("ix_process_events_project_node", "project_id", "node_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("entities.id"), nullable=False, index=True
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    import_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("process_event_imports.id", ondelete="CASCADE"), nullable=False,
        index=True,
    )
    case_id: Mapped[str] = mapped_column(String(160), nullable=False)
    activity: Mapped[str] = mapped_column(String(240), nullable=False)
    node_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    owner: Mapped[str | None] = mapped_column(String(160), nullable=True)
    cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    attributes: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict
    )


class ProcessInsight(Base):
    __tablename__ = "process_insights"
    __table_args__ = (
        Index("ix_process_insights_project_status_detected", "project_id", "status", "detected_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("entities.id"), nullable=False, index=True
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    import_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("process_event_imports.id", ondelete="CASCADE"), nullable=True,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="medium")
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    node_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open", index=True)
    evidence: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict
    )
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )


class PolicyRule(Base):
    __tablename__ = "policy_rules"
    __table_args__ = (
        Index("ix_policy_rules_entity_resource", "entity_id", "resource_type", "active", "priority"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(String(36), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(140), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    effect: Mapped[str] = mapped_column(String(12), nullable=False, default="deny")
    actions: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    subject_type: Mapped[str] = mapped_column(String(20), nullable=False, default="role")
    subject_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    resource_type: Mapped[str] = mapped_column(String(40), nullable=False, default="*")
    resource_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    fields: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    conditions: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)


class DataGovernancePolicy(Base):
    __tablename__ = "data_governance_policies"
    __table_args__ = (
        UniqueConstraint("entity_id", "name", name="uq_data_governance_policy_name"),
        Index("ix_data_governance_policy_entity_kind", "entity_id", "kind", "active"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(String(36), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(140), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    applies_to: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    classification: Mapped[str] = mapped_column(String(24), nullable=False, default="internal")
    enforcement: Mapped[str] = mapped_column(String(16), nullable=False, default="audit")
    configuration: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)


class LegalHold(Base):
    __tablename__ = "legal_holds"
    __table_args__ = (Index("ix_legal_holds_entity_scope", "entity_id", "scope_type", "scope_id", "status"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(String(36), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    scope_type: Mapped[str] = mapped_column(String(40), nullable=False, default="entity")
    scope_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_by_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    released_by_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EncryptionKeyReference(Base):
    __tablename__ = "encryption_key_references"
    __table_args__ = (UniqueConstraint("entity_id", "name", name="uq_encryption_key_reference_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(String(36), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    provider: Mapped[str] = mapped_column(String(30), nullable=False, default="platform")
    key_reference: Mapped[str] = mapped_column(String(1000), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class IntegrationConnection(Base):
    __tablename__ = "integration_connections"
    __table_args__ = (UniqueConstraint("entity_id", "name", name="uq_integration_connection_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(String(36), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(140), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    scopes: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    credentials_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    configuration: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    sync_cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    conflict_policy: Mapped[str] = mapped_column(String(24), nullable=False, default="source_wins")
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)


class WebhookSubscription(Base):
    __tablename__ = "webhook_subscriptions"
    __table_args__ = (Index("ix_webhooks_entity_status", "entity_id", "status"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(String(36), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(140), nullable=False)
    target_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    event_types: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    signing_secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_delivery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        UniqueConstraint("subscription_id", "event_id", name="uq_webhook_delivery_event"),
        Index("ix_webhook_deliveries_entity_status", "entity_id", "status", "next_attempt_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(String(36), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)
    subscription_id: Mapped[str] = mapped_column(String(36), ForeignKey("webhook_subscriptions.id", ondelete="CASCADE"), nullable=False, index=True)
    event_id: Mapped[str] = mapped_column(String(80), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_excerpt: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class ApiAccessToken(Base):
    __tablename__ = "api_access_tokens"
    __table_args__ = (Index("ix_api_access_tokens_entity_active", "entity_id", "revoked_at", "expires_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(String(36), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    token_prefix: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    scopes: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    created_by_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class SupportAccessGrant(Base):
    __tablename__ = "support_access_grants"
    __table_args__ = (Index("ix_support_access_entity_status", "entity_id", "status", "expires_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(String(36), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)
    requested_for: Mapped[str] = mapped_column(String(320), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    scopes: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    requested_by_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    approved_by_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class FeatureEntitlement(Base):
    __tablename__ = "feature_entitlements"
    __table_args__ = (UniqueConstraint("entity_id", "feature", name="uq_feature_entitlement"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(String(36), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)
    feature: Mapped[str] = mapped_column(String(80), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    limit_value: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    configuration: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_by_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)


class OperationalEvent(Base):
    __tablename__ = "operational_events"
    __table_args__ = (Index("ix_operational_events_entity_service_created", "entity_id", "service", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(String(36), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)
    service: Mapped[str] = mapped_column(String(60), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="error")
    fingerprint: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    message: Mapped[str] = mapped_column(String(1000), nullable=False)
    context: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class ServiceObjective(Base):
    __tablename__ = "service_objectives"
    __table_args__ = (UniqueConstraint("entity_id", "service", "metric", name="uq_service_objective"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(String(36), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)
    service: Mapped[str] = mapped_column(String(60), nullable=False)
    metric: Mapped[str] = mapped_column(String(60), nullable=False)
    target: Mapped[float] = mapped_column(Float, nullable=False)
    window_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    warning_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.8)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_by_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)


class ServiceTicket(Base):
    __tablename__ = "service_tickets"
    __table_args__ = (
        Index("ix_service_tickets_entity_status_updated", "entity_id", "status", "updated_at"),
        Index("ix_service_tickets_entity_assignee", "entity_id", "assignee_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(String(36), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)
    requester_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    assignee_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    project_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    ticket_type: Mapped[str] = mapped_column(String(30), nullable=False, default="request", index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open", index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="normal", index=True)
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="medium", index=True)
    service: Mapped[str] = mapped_column(String(80), nullable=False, default="workspace")
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="portal")
    external_requester_email: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    tags: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    custom_fields: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    response_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    resolution_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    first_response_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)


class ServiceTicketComment(Base):
    __tablename__ = "service_ticket_comments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    ticket_id: Mapped[str] = mapped_column(String(36), ForeignKey("service_tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    entity_id: Mapped[str] = mapped_column(String(36), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)
    author_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    external_author: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    internal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class OnCallSchedule(Base):
    __tablename__ = "on_call_schedules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(String(36), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)
    service: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    member_ids: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    rotation: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class GuestAccessGrant(Base):
    __tablename__ = "guest_access_grants"
    __table_args__ = (Index("ix_guest_access_entity_resource", "entity_id", "resource_type", "resource_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity_id: Mapped[str] = mapped_column(String(36), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)
    guest_email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    guest_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    resource_type: Mapped[str] = mapped_column(String(30), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(80), nullable=False)
    permissions: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=lambda: ["view"])
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    created_by_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class GuestPortalActivity(Base):
    __tablename__ = "guest_portal_activities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    grant_id: Mapped[str] = mapped_column(String(36), ForeignKey("guest_access_grants.id", ondelete="CASCADE"), nullable=False, index=True)
    entity_id: Mapped[str] = mapped_column(String(36), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


@event.listens_for(Session, "before_flush")
def chain_new_audit_events(session: Session, _flush_context, _instances) -> None:
    """Chain audit events per tenant so later tampering can be detected."""
    pending = [item for item in session.new if isinstance(item, AuditEvent) and not item.event_hash]
    previous_by_entity: dict[str, str | None] = {}
    for item in pending:
        if item.entity_id not in previous_by_entity:
            previous_by_entity[item.entity_id] = session.scalar(
                select(AuditEvent.event_hash)
                .where(AuditEvent.entity_id == item.entity_id, AuditEvent.event_hash.is_not(None))
                .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(1)
            )
        item.id = item.id or str(uuid4())
        item.created_at = item.created_at or datetime.now(timezone.utc)
        item.previous_hash = previous_by_entity[item.entity_id]
        canonical = json.dumps({
            "id": item.id, "entity_id": item.entity_id, "actor_id": item.actor_id,
            "action": item.action, "target_type": item.target_type, "target_id": item.target_id,
            "details": item.details or {}, "created_at": item.created_at.isoformat(),
            "previous_hash": item.previous_hash,
        }, sort_keys=True, separators=(",", ":"), default=str)
        item.event_hash = sha256(canonical.encode("utf-8")).hexdigest()
        previous_by_entity[item.entity_id] = item.event_hash


async def init_database() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

        def migrate_existing_data(sync_connection) -> None:
            entity_columns = {
                column["name"] for column in inspect(sync_connection).get_columns("entities")
            }
            entity_additions = {
                "max_users": "INTEGER NOT NULL DEFAULT 100",
                "max_projects": "INTEGER NOT NULL DEFAULT 1000",
                "max_storage_bytes": "BIGINT NOT NULL DEFAULT 10737418240",
                "max_monthly_generations": "INTEGER NOT NULL DEFAULT 1000",
                "max_pending_generations": "INTEGER NOT NULL DEFAULT 20",
                "work_columns": "JSON",
                "work_item_types": "JSON",
            }
            for column_name, column_type in entity_additions.items():
                if column_name not in entity_columns:
                    sync_connection.execute(
                        text(f"ALTER TABLE entities ADD COLUMN {column_name} {column_type}")
                    )

            user_columns = {
                column["name"] for column in inspect(sync_connection).get_columns("users")
            }
            if "entity_id" not in user_columns:
                sync_connection.execute(text("ALTER TABLE users ADD COLUMN entity_id VARCHAR(36)"))
            if "role" not in user_columns:
                sync_connection.execute(
                    text("ALTER TABLE users ADD COLUMN role VARCHAR(20) DEFAULT 'admin'")
                )

            now = datetime.now(timezone.utc)
            legacy_users = sync_connection.execute(
                text("SELECT id, display_name FROM users WHERE entity_id IS NULL")
            ).mappings()
            for legacy_user in legacy_users:
                entity_id = str(uuid4())
                sync_connection.execute(
                    text(
                        "INSERT INTO entities (id, name, created_at) "
                        "VALUES (:id, :name, :created_at)"
                    ),
                    {
                        "id": entity_id,
                        "name": f"{legacy_user['display_name']}'s workspace",
                        "created_at": now,
                    },
                )
                sync_connection.execute(
                    text(
                        "UPDATE users SET entity_id = :entity_id, role = 'admin' WHERE id = :user_id"
                    ),
                    {"entity_id": entity_id, "user_id": legacy_user["id"]},
                )

            project_columns = {
                column["name"] for column in inspect(sync_connection).get_columns("projects")
            }
            if "owner_id" not in project_columns:
                sync_connection.execute(text("ALTER TABLE projects ADD COLUMN owner_id VARCHAR(36)"))
            if "entity_id" not in project_columns:
                sync_connection.execute(text("ALTER TABLE projects ADD COLUMN entity_id VARCHAR(36)"))
            if "revision" not in project_columns:
                sync_connection.execute(
                    text("ALTER TABLE projects ADD COLUMN revision INTEGER DEFAULT 0")
                )
            if "description" not in project_columns:
                sync_connection.execute(
                    text("ALTER TABLE projects ADD COLUMN description TEXT NOT NULL DEFAULT ''")
                )
            if "status" not in project_columns:
                sync_connection.execute(
                    text("ALTER TABLE projects ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'active'")
                )
            if "visibility" not in project_columns:
                sync_connection.execute(
                    text(
                        "ALTER TABLE projects ADD COLUMN visibility VARCHAR(20) "
                        "NOT NULL DEFAULT 'workspace'"
                    )
                )
            if "approval_status" not in project_columns:
                sync_connection.execute(
                    text(
                        "ALTER TABLE projects ADD COLUMN approval_status VARCHAR(24) "
                        "NOT NULL DEFAULT 'draft'"
                    )
                )
            sync_connection.execute(
                text(
                    "UPDATE projects SET entity_id = "
                    "(SELECT entity_id FROM users WHERE users.id = projects.owner_id) "
                    "WHERE entity_id IS NULL AND owner_id IS NOT NULL"
                )
            )
            sync_connection.execute(
                text("CREATE INDEX IF NOT EXISTS ix_users_entity_id ON users (entity_id)")
            )
            sync_connection.execute(
                text("CREATE INDEX IF NOT EXISTS ix_projects_owner_id ON projects (owner_id)")
            )
            sync_connection.execute(
                text("CREATE INDEX IF NOT EXISTS ix_projects_entity_id ON projects (entity_id)")
            )
            sync_connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_projects_entity_updated_id "
                    "ON projects (entity_id, updated_at, id)"
                )
            )
            sync_connection.execute(
                text("CREATE INDEX IF NOT EXISTS ix_projects_title ON projects (title)")
            )
            sync_connection.execute(
                text(
                    "INSERT INTO project_collaborators (project_id, user_id, added_at) "
                    "SELECT projects.id, projects.owner_id, :added_at FROM projects "
                    "WHERE projects.owner_id IS NOT NULL AND NOT EXISTS ("
                    "SELECT 1 FROM project_collaborators "
                    "WHERE project_collaborators.project_id = projects.id "
                    "AND project_collaborators.user_id = projects.owner_id)"
                ),
                {"added_at": now},
            )
            collaborator_columns = {
                column["name"]
                for column in inspect(sync_connection).get_columns("project_collaborators")
            }
            if "access_role" not in collaborator_columns:
                sync_connection.execute(
                    text(
                        "ALTER TABLE project_collaborators ADD COLUMN access_role VARCHAR(20) "
                        "NOT NULL DEFAULT 'viewer'"
                    )
                )
            sync_connection.execute(
                text(
                    "UPDATE project_collaborators SET access_role = 'editor' "
                    "WHERE user_id IN (SELECT id FROM users WHERE role = 'admin') "
                    "AND access_role = 'viewer'"
                )
            )
            legacy_projects = sync_connection.execute(
                text(
                    "SELECT id, owner_id, title, description, status, source_text, graph, "
                    "created_at FROM projects WHERE owner_id IS NOT NULL AND NOT EXISTS ("
                    "SELECT 1 FROM project_revisions "
                    "WHERE project_revisions.project_id = projects.id)"
                )
            ).mappings()
            for legacy_project in legacy_projects:
                sync_connection.execute(
                    text(
                        "INSERT INTO project_revisions ("
                        "id, project_id, version, title, description, status, source_text, "
                        "graph, change_summary, created_by_id, created_at"
                        ") VALUES ("
                        ":id, :project_id, 1, :title, :description, :status, :source_text, "
                        ":graph, 'Imported existing flowchart', :created_by_id, :created_at"
                        ")"
                    ),
                    {
                        "id": str(uuid4()),
                        "project_id": legacy_project["id"],
                        "title": legacy_project["title"],
                        "description": legacy_project["description"] or "",
                        "status": legacy_project["status"] or "active",
                        "source_text": legacy_project["source_text"] or "",
                        "graph": legacy_project["graph"],
                        "created_by_id": legacy_project["owner_id"],
                        "created_at": legacy_project["created_at"] or now,
                    },
                )

            task_columns = {
                column["name"] for column in inspect(sync_connection).get_columns("project_tasks")
            }
            if "deliverable_id" not in task_columns:
                sync_connection.execute(
                    text(
                        "ALTER TABLE project_tasks ADD COLUMN deliverable_id VARCHAR(36) "
                        "REFERENCES project_deliverables(id) ON DELETE SET NULL"
                    )
                )
            if "node_id" not in task_columns:
                sync_connection.execute(
                    text("ALTER TABLE project_tasks ADD COLUMN node_id VARCHAR(80)")
                )
            sync_connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_project_tasks_deliverable_id "
                    "ON project_tasks (deliverable_id)"
                )
            )

            notification_columns = {
                column["name"] for column in inspect(sync_connection).get_columns("notifications")
            }
            if "calendar_event_id" not in notification_columns:
                sync_connection.execute(
                    text(
                        "ALTER TABLE notifications ADD COLUMN calendar_event_id VARCHAR(36) "
                        "REFERENCES calendar_events(id) ON DELETE CASCADE"
                    )
                )
            sync_connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_notifications_calendar_event_id "
                    "ON notifications (calendar_event_id)"
                )
            )

            calendar_attendee_columns = {
                column["name"]
                for column in inspect(sync_connection).get_columns("calendar_event_attendees")
            }
            if "reminder_minutes" not in calendar_attendee_columns:
                sync_connection.execute(
                    text(
                        "ALTER TABLE calendar_event_attendees ADD COLUMN "
                        "reminder_minutes INTEGER DEFAULT 15"
                    )
                )
            if "reminder_sent_at" not in calendar_attendee_columns:
                sync_connection.execute(
                    text(
                        "ALTER TABLE calendar_event_attendees ADD COLUMN "
                        "reminder_sent_at DATETIME"
                    )
                )

            calendar_event_columns = {
                column["name"]
                for column in inspect(sync_connection).get_columns("calendar_events")
            }
            calendar_event_additions = {
                "series_id": "VARCHAR(36)",
                "recurrence_frequency": "VARCHAR(20)",
                "recurrence_interval": "INTEGER NOT NULL DEFAULT 1",
                "recurrence_ends_at": "DATE",
                "recurrence_count": "INTEGER",
                "occurrence_index": "INTEGER NOT NULL DEFAULT 0",
            }
            for column_name, column_type in calendar_event_additions.items():
                if column_name not in calendar_event_columns:
                    sync_connection.execute(
                        text(f"ALTER TABLE calendar_events ADD COLUMN {column_name} {column_type}")
                    )
            sync_connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_calendar_events_series_start "
                    "ON calendar_events (series_id, starts_at)"
                )
            )

            attachment_columns = {
                column["name"]
                for column in inspect(sync_connection).get_columns("project_attachments")
            }
            attachment_additions = {
                "entity_id": "VARCHAR(36)",
                "storage_key": "VARCHAR(900)",
                "upload_status": "VARCHAR(20) NOT NULL DEFAULT 'complete'",
                "scan_status": "VARCHAR(20) NOT NULL DEFAULT 'clean'",
                "scan_message": "VARCHAR(240)",
                "object_etag": "VARCHAR(160)",
                "uploaded_at": "DATETIME",
            }
            for column_name, column_type in attachment_additions.items():
                if column_name not in attachment_columns:
                    sync_connection.execute(
                        text(
                            f"ALTER TABLE project_attachments ADD COLUMN "
                            f"{column_name} {column_type}"
                        )
                    )
            sync_connection.execute(
                text(
                    "UPDATE project_attachments SET entity_id = "
                    "(SELECT entity_id FROM projects "
                    "WHERE projects.id = project_attachments.project_id) "
                    "WHERE entity_id IS NULL"
                )
            )
            sync_connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_project_attachments_entity_id "
                    "ON project_attachments (entity_id)"
                )
            )
            sync_connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ix_project_attachments_storage_key "
                    "ON project_attachments (storage_key)"
                )
            )
            sync_connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_project_attachments_scan_status "
                    "ON project_attachments (scan_status)"
                )
            )

            background_job_columns = {
                column["name"] for column in inspect(sync_connection).get_columns("background_jobs")
            }
            if "purged_at" not in background_job_columns:
                sync_connection.execute(
                    text("ALTER TABLE background_jobs ADD COLUMN purged_at DATETIME")
                )

        await connection.run_sync(migrate_existing_data)


async def verify_database_revision() -> None:
    async with engine.connect() as connection:
        has_version_table = await connection.run_sync(
            lambda sync_connection: inspect(sync_connection).has_table("alembic_version")
        )
        if not has_version_table:
            raise RuntimeError(
                "Database migrations have not been applied. Run `alembic upgrade head` "
                "before starting the production API."
            )
        revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        if revision != EXPECTED_DATABASE_REVISION:
            raise RuntimeError(
                f"Database revision {revision or 'unknown'} is not supported; "
                f"expected {EXPECTED_DATABASE_REVISION}. Run `alembic upgrade head`."
            )


async def get_session() -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session
