"""Add OIDC federation and SCIM provisioning records.

Revision ID: 20260912_23
Revises: 20260912_22
"""
from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "20260912_23"
down_revision: str | None = "20260912_22"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("account_status", sa.String(20), nullable=False, server_default="active"))
        batch_op.add_column(sa.Column("provisioning_source", sa.String(20), nullable=False, server_default="local"))
        batch_op.create_index("ix_users_account_status", ["account_status"])
    op.create_table("identity_providers",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False), sa.Column("protocol", sa.String(20), nullable=False, server_default="oidc"),
        sa.Column("issuer_url", sa.String(500), nullable=False), sa.Column("client_id", sa.String(300), nullable=False), sa.Column("client_secret_encrypted", sa.Text(), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False, server_default=sa.text("'[\"openid\",\"profile\",\"email\"]'")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("enforce_sso", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("jit_enabled", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("default_role", sa.String(20), nullable=False, server_default="basic"),
        sa.Column("allow_admin_password_fallback", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("entity_id", "name", name="uq_identity_provider_entity_name"))
    op.create_index("ix_identity_providers_entity_id", "identity_providers", ["entity_id"])
    op.create_table("identity_provider_domains",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("provider_id", sa.String(36), sa.ForeignKey("identity_providers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False), sa.Column("domain", sa.String(253), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"), sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.Column("verified_at", sa.DateTime(timezone=True)), sa.UniqueConstraint("domain"))
    for name, columns in (("ix_identity_provider_domains_provider_id", ["provider_id"]), ("ix_identity_provider_domains_entity_id", ["entity_id"]), ("ix_identity_provider_domains_domain", ["domain"]), ("ix_identity_provider_domains_status", ["status"])): op.create_index(name, "identity_provider_domains", columns)
    op.create_table("external_identities",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider_id", sa.String(36), sa.ForeignKey("identity_providers.id", ondelete="CASCADE"), nullable=False), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subject", sa.String(500), nullable=False), sa.Column("email_at_link", sa.String(320), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("provider_id", "subject", name="uq_external_identity_provider_subject"), sa.UniqueConstraint("provider_id", "user_id", name="uq_external_identity_provider_user"))
    for name, columns in (("ix_external_identities_entity_id", ["entity_id"]), ("ix_external_identities_provider_id", ["provider_id"]), ("ix_external_identities_user_id", ["user_id"])): op.create_index(name, "external_identities", columns)
    op.create_table("sso_authorization_states",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("provider_id", sa.String(36), sa.ForeignKey("identity_providers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("state_hash", sa.String(64), nullable=False), sa.Column("nonce", sa.String(100), nullable=False), sa.Column("verifier_encrypted", sa.Text(), nullable=False),
        sa.Column("return_path", sa.String(500), nullable=False, server_default="/"), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False), sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("state_hash"))
    op.create_index("ix_sso_authorization_states_provider_id", "sso_authorization_states", ["provider_id"]); op.create_index("ix_sso_authorization_states_state_hash", "sso_authorization_states", ["state_hash"]); op.create_index("ix_sso_authorization_states_expires_at", "sso_authorization_states", ["expires_at"])
    op.create_table("scim_access_tokens",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False), sa.Column("token_hash", sa.String(64), nullable=False), sa.Column("scopes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True)), sa.Column("last_used_at", sa.DateTime(timezone=True)), sa.Column("revoked_at", sa.DateTime(timezone=True)), sa.UniqueConstraint("token_hash"))
    for name, columns in (("ix_scim_access_tokens_entity_id", ["entity_id"]), ("ix_scim_access_tokens_token_hash", ["token_hash"]), ("ix_scim_access_tokens_revoked_at", ["revoked_at"])): op.create_index(name, "scim_access_tokens", columns)


def downgrade() -> None:
    op.drop_table("scim_access_tokens"); op.drop_table("sso_authorization_states"); op.drop_table("external_identities"); op.drop_table("identity_provider_domains"); op.drop_table("identity_providers")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_index("ix_users_account_status"); batch_op.drop_column("provisioning_source"); batch_op.drop_column("account_status")
