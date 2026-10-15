"""Add enterprise sessions and multi-factor identity state.

Revision ID: 20260912_21
Revises: 20260912_20
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260912_21"
down_revision: str | None = "20260912_20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("mfa_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("mfa_secret_encrypted", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("mfa_recovery_hashes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))

    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("user_agent", sa.String(500), nullable=False, server_default=""),
        sa.Column("ip_digest", sa.String(64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True, index=True),
    )
    op.create_index("ix_auth_sessions_user_active", "auth_sessions", ["user_id", "revoked_at", "expires_at"])
    op.create_index("ix_auth_sessions_entity_created", "auth_sessions", ["entity_id", "created_at"])


def downgrade() -> None:
    op.drop_table("auth_sessions")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("mfa_recovery_hashes")
        batch_op.drop_column("mfa_secret_encrypted")
        batch_op.drop_column("mfa_enabled")
