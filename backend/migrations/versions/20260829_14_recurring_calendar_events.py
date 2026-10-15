"""Add bounded recurring calendar series.

Revision ID: 20260829_14
Revises: 20260829_13
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260829_14"
down_revision: str | None = "20260829_13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("calendar_events") as batch_op:
        batch_op.add_column(sa.Column("series_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("recurrence_frequency", sa.String(length=20), nullable=True))
        batch_op.add_column(
            sa.Column("recurrence_interval", sa.Integer(), nullable=False, server_default="1")
        )
        batch_op.add_column(sa.Column("recurrence_ends_at", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("recurrence_count", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("occurrence_index", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.create_index(
            "ix_calendar_events_series_start", ["series_id", "starts_at"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("calendar_events") as batch_op:
        batch_op.drop_index("ix_calendar_events_series_start")
        batch_op.drop_column("occurrence_index")
        batch_op.drop_column("recurrence_count")
        batch_op.drop_column("recurrence_ends_at")
        batch_op.drop_column("recurrence_interval")
        batch_op.drop_column("recurrence_frequency")
        batch_op.drop_column("series_id")
