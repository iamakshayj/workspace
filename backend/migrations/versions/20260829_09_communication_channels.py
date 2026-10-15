"""Add workspace channels, private groups, and channel messages.

Revision ID: 20260829_09
Revises: 20260829_08
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260829_09"
down_revision: str | None = "20260829_08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "communication_channels",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.id"), nullable=False),
        sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("description", sa.String(500), nullable=False, server_default=""),
        sa.Column("channel_type", sa.String(20), nullable=False, server_default="channel"),
        sa.Column("visibility", sa.String(20), nullable=False, server_default="workspace"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("entity_id", "name", name="uq_communication_channel_entity_name"),
    )
    op.create_index("ix_communication_channels_entity_id", "communication_channels", ["entity_id"])
    op.create_index("ix_communication_channels_created_by_id", "communication_channels", ["created_by_id"])
    op.create_index("ix_communication_channels_entity_created", "communication_channels", ["entity_id", "created_at"])

    op.create_table(
        "communication_channel_members",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("channel_id", sa.String(36), sa.ForeignKey("communication_channels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="member"),
        sa.Column("last_read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("channel_id", "user_id", name="uq_communication_channel_member"),
    )
    op.create_index("ix_communication_channel_members_channel_id", "communication_channel_members", ["channel_id"])
    op.create_index("ix_communication_channel_members_user_id", "communication_channel_members", ["user_id"])
    op.create_index("ix_communication_channel_members_user_channel", "communication_channel_members", ["user_id", "channel_id"])

    op.create_table(
        "communication_channel_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.id"), nullable=False),
        sa.Column("channel_id", sa.String(36), sa.ForeignKey("communication_channels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sender_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_communication_channel_messages_entity_id", "communication_channel_messages", ["entity_id"])
    op.create_index("ix_communication_channel_messages_channel_id", "communication_channel_messages", ["channel_id"])
    op.create_index("ix_communication_channel_messages_sender_id", "communication_channel_messages", ["sender_id"])
    op.create_index("ix_communication_channel_messages_channel_created", "communication_channel_messages", ["channel_id", "created_at"])


def downgrade() -> None:
    op.drop_table("communication_channel_messages")
    op.drop_table("communication_channel_members")
    op.drop_table("communication_channels")
