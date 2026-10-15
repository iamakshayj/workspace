"""Add SAML Single Logout session binding and request state.

Revision ID: 20260912_26
Revises: 20260912_25
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260912_26"
down_revision: str | None = "20260912_25"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("identity_providers") as batch_op:
        batch_op.add_column(sa.Column("saml_slo_url", sa.String(1000), nullable=True))

    with op.batch_alter_table("auth_sessions") as batch_op:
        batch_op.add_column(sa.Column("identity_provider_id", sa.String(36), nullable=True))
        batch_op.add_column(sa.Column("external_session_index", sa.String(500), nullable=True))
        batch_op.add_column(sa.Column("external_subject", sa.String(500), nullable=True))
        batch_op.create_foreign_key("fk_auth_sessions_identity_provider", "identity_providers", ["identity_provider_id"], ["id"], ondelete="SET NULL")
        batch_op.create_index("ix_auth_sessions_identity_provider_id", ["identity_provider_id"])
        batch_op.create_index("ix_auth_sessions_external_session_index", ["external_session_index"])
        batch_op.create_index("ix_auth_sessions_external_subject", ["external_subject"])

    op.create_table(
        "saml_logout_states",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider_id", sa.String(36), sa.ForeignKey("identity_providers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("auth_session_id", sa.String(36), sa.ForeignKey("auth_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("request_id", sa.String(100), nullable=False, unique=True),
        sa.Column("state_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("return_path", sa.String(500), nullable=False, server_default="/"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_saml_logout_states_provider_id", "saml_logout_states", ["provider_id"])
    op.create_index("ix_saml_logout_states_auth_session_id", "saml_logout_states", ["auth_session_id"])
    op.create_index("ix_saml_logout_states_request_id", "saml_logout_states", ["request_id"])
    op.create_index("ix_saml_logout_states_state_hash", "saml_logout_states", ["state_hash"])
    op.create_index("ix_saml_logout_states_expires_at", "saml_logout_states", ["expires_at"])

    op.create_table(
        "saml_logout_replays",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider_id", sa.String(36), sa.ForeignKey("identity_providers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("request_id", sa.String(100), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_saml_logout_replays_provider_id", "saml_logout_replays", ["provider_id"])
    op.create_index("ix_saml_logout_replays_request_id", "saml_logout_replays", ["request_id"])
    op.create_index("ix_saml_logout_replays_expires_at", "saml_logout_replays", ["expires_at"])


def downgrade() -> None:
    op.drop_table("saml_logout_replays")
    op.drop_table("saml_logout_states")
    with op.batch_alter_table("auth_sessions") as batch_op:
        batch_op.drop_index("ix_auth_sessions_external_subject")
        batch_op.drop_index("ix_auth_sessions_external_session_index")
        batch_op.drop_index("ix_auth_sessions_identity_provider_id")
        batch_op.drop_constraint("fk_auth_sessions_identity_provider", type_="foreignkey")
        batch_op.drop_column("external_subject")
        batch_op.drop_column("external_session_index")
        batch_op.drop_column("identity_provider_id")
    with op.batch_alter_table("identity_providers") as batch_op:
        batch_op.drop_column("saml_slo_url")
