"""Add personalized calendars and team meetings.

Revision ID: 20260829_10
Revises: 20260829_09
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260829_10"
down_revision: str | None = "20260829_09"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "calendar_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.id"), nullable=False),
        sa.Column("organizer_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("event_type", sa.String(20), nullable=False, server_default="meeting"),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="UTC"),
        sa.Column("all_day", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("location", sa.String(240), nullable=False, server_default=""),
        sa.Column("meeting_url", sa.String(500), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="scheduled"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_calendar_events_entity_id", "calendar_events", ["entity_id"])
    op.create_index("ix_calendar_events_organizer_id", "calendar_events", ["organizer_id"])
    op.create_index("ix_calendar_events_starts_at", "calendar_events", ["starts_at"])
    op.create_index("ix_calendar_events_ends_at", "calendar_events", ["ends_at"])
    op.create_index("ix_calendar_events_entity_start", "calendar_events", ["entity_id", "starts_at"])
    op.create_index("ix_calendar_events_organizer_start", "calendar_events", ["organizer_id", "starts_at"])

    op.create_table(
        "calendar_event_attendees",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("calendar_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("response", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("event_id", "user_id", name="uq_calendar_event_attendee"),
    )
    op.create_index("ix_calendar_event_attendees_event_id", "calendar_event_attendees", ["event_id"])
    op.create_index("ix_calendar_event_attendees_user_id", "calendar_event_attendees", ["user_id"])
    op.create_index("ix_calendar_event_attendees_user_event", "calendar_event_attendees", ["user_id", "event_id"])

    with op.batch_alter_table("notifications") as batch_op:
        batch_op.add_column(sa.Column("calendar_event_id", sa.String(36), nullable=True))
        batch_op.create_foreign_key(
            "fk_notifications_calendar_event_id",
            "calendar_events",
            ["calendar_event_id"],
            ["id"],
            ondelete="CASCADE",
        )
    op.create_index("ix_notifications_calendar_event_id", "notifications", ["calendar_event_id"])


def downgrade() -> None:
    op.drop_index("ix_notifications_calendar_event_id", table_name="notifications")
    with op.batch_alter_table("notifications") as batch_op:
        batch_op.drop_constraint("fk_notifications_calendar_event_id", type_="foreignkey")
        batch_op.drop_column("calendar_event_id")
    op.drop_table("calendar_event_attendees")
    op.drop_table("calendar_events")
