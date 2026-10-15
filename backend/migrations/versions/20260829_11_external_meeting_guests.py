"""Add external email guests to calendar meetings.

Revision ID: 20260829_11
Revises: 20260829_10
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260829_11"
down_revision: str | None = "20260829_10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "calendar_event_external_attendees",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "event_id", sa.String(36),
            sa.ForeignKey("calendar_events.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("response", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("delivery_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("event_id", "email", name="uq_calendar_event_external_attendee"),
    )
    op.create_index(
        "ix_calendar_event_external_attendees_event_id",
        "calendar_event_external_attendees", ["event_id"],
    )
    op.create_index(
        "ix_calendar_event_external_attendees_email",
        "calendar_event_external_attendees", ["email"],
    )
    op.create_index(
        "ix_calendar_external_attendees_event_status",
        "calendar_event_external_attendees", ["event_id", "status"],
    )


def downgrade() -> None:
    op.drop_table("calendar_event_external_attendees")
