"""Add session authentication assurance level.

Revision ID: 20260912_22
Revises: 20260912_21
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260912_22"
down_revision: str | None = "20260912_21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("auth_sessions") as batch_op:
        batch_op.add_column(sa.Column("auth_level", sa.String(20), nullable=False, server_default="password"))


def downgrade() -> None:
    with op.batch_alter_table("auth_sessions") as batch_op:
        batch_op.drop_column("auth_level")
