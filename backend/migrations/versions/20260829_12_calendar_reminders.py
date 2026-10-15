"""Add per-user calendar reminders.

Revision ID: 20260829_12
Revises: 20260829_11
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260829_12"
down_revision: str | None = "20260829_11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("calendar_event_attendees") as batch_op:
        batch_op.add_column(sa.Column("reminder_minutes", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("reminder_sent_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(
        "UPDATE calendar_event_attendees SET reminder_minutes = 15 "
        "WHERE reminder_minutes IS NULL"
    )


def downgrade() -> None:
    with op.batch_alter_table("calendar_event_attendees") as batch_op:
        batch_op.drop_column("reminder_sent_at")
        batch_op.drop_column("reminder_minutes")
