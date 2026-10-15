"""Add SAML provider settings and assertion replay protection.

Revision ID: 20260912_24
Revises: 20260912_23
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260912_24"
down_revision: str | None = "20260912_23"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("identity_providers") as batch_op:
        batch_op.add_column(sa.Column("saml_sso_url", sa.String(1000), nullable=True))
        batch_op.add_column(sa.Column("saml_email_attribute", sa.String(500), nullable=True))

    op.create_table(
        "saml_assertion_replays",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "provider_id",
            sa.String(36),
            sa.ForeignKey("identity_providers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("assertion_id", sa.String(500), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_saml_assertion_replays_provider_id", "saml_assertion_replays", ["provider_id"])
    op.create_index("ix_saml_assertion_replays_assertion_id", "saml_assertion_replays", ["assertion_id"])
    op.create_index("ix_saml_assertion_replays_expires_at", "saml_assertion_replays", ["expires_at"])


def downgrade() -> None:
    op.drop_table("saml_assertion_replays")
    with op.batch_alter_table("identity_providers") as batch_op:
        batch_op.drop_column("saml_email_attribute")
        batch_op.drop_column("saml_sso_url")
