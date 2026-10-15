"""Add threads, reactions, pins, bookmarks, attachments, and message lifecycle fields.

Revision ID: 20260902_16
Revises: 20260902_15
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260902_16"
down_revision: str | None = "20260902_15"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def add_message_fields(table: str, parent_table: str) -> None:
    with op.batch_alter_table(table) as batch_op:
        batch_op.add_column(sa.Column("parent_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("reactions", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
        batch_op.add_column(sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("bookmark_user_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
        batch_op.add_column(sa.Column("attachments", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
        batch_op.add_column(sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_foreign_key(
            f"fk_{table}_parent_id", parent_table, ["parent_id"], ["id"], ondelete="SET NULL"
        )
        batch_op.create_index(f"ix_{table}_parent_id", ["parent_id"], unique=False)


def drop_message_fields(table: str) -> None:
    with op.batch_alter_table(table) as batch_op:
        batch_op.drop_index(f"ix_{table}_parent_id")
        batch_op.drop_constraint(f"fk_{table}_parent_id", type_="foreignkey")
        batch_op.drop_column("deleted_at")
        batch_op.drop_column("edited_at")
        batch_op.drop_column("attachments")
        batch_op.drop_column("bookmark_user_ids")
        batch_op.drop_column("pinned")
        batch_op.drop_column("reactions")
        batch_op.drop_column("parent_id")


def upgrade() -> None:
    add_message_fields("direct_messages", "direct_messages")
    add_message_fields("communication_channel_messages", "communication_channel_messages")
    with op.batch_alter_table("notifications") as batch_op:
        batch_op.add_column(sa.Column("communication_channel_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("communication_message_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_notifications_communication_channel_id", "communication_channels",
            ["communication_channel_id"], ["id"], ondelete="CASCADE",
        )
        batch_op.create_index("ix_notifications_communication_channel_id", ["communication_channel_id"], unique=False)
        batch_op.create_index("ix_notifications_communication_message_id", ["communication_message_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("notifications") as batch_op:
        batch_op.drop_index("ix_notifications_communication_message_id")
        batch_op.drop_index("ix_notifications_communication_channel_id")
        batch_op.drop_constraint("fk_notifications_communication_channel_id", type_="foreignkey")
        batch_op.drop_column("communication_message_id")
        batch_op.drop_column("communication_channel_id")
    drop_message_fields("communication_channel_messages")
    drop_message_fields("direct_messages")
