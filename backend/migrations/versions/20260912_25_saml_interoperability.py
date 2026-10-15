"""Add SAML metadata, signing-key, and certificate-rotation support.

Revision ID: 20260912_25
Revises: 20260912_24
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260912_25"
down_revision: str | None = "20260912_24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("identity_providers") as batch_op:
        batch_op.add_column(sa.Column("saml_sign_authn_requests", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("saml_sp_private_key_encrypted", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("saml_sp_certificate", sa.Text(), nullable=True))

    op.create_table(
        "saml_signing_certificates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider_id", sa.String(36), sa.ForeignKey("identity_providers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("certificate_encrypted", sa.Text(), nullable=False),
        sa.Column("fingerprint_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("provider_id", "fingerprint_sha256", name="uq_saml_certificate_provider_fingerprint"),
    )
    op.create_index("ix_saml_signing_certificates_provider_id", "saml_signing_certificates", ["provider_id"])
    op.create_index("ix_saml_signing_certificates_entity_id", "saml_signing_certificates", ["entity_id"])
    op.create_index("ix_saml_signing_certificates_fingerprint_sha256", "saml_signing_certificates", ["fingerprint_sha256"])
    op.create_index("ix_saml_signing_certificates_status", "saml_signing_certificates", ["status"])
    op.create_index("ix_saml_signing_certificates_valid_until", "saml_signing_certificates", ["valid_until"])


def downgrade() -> None:
    op.drop_table("saml_signing_certificates")
    with op.batch_alter_table("identity_providers") as batch_op:
        batch_op.drop_column("saml_sp_certificate")
        batch_op.drop_column("saml_sp_private_key_encrypted")
        batch_op.drop_column("saml_sign_authn_requests")
