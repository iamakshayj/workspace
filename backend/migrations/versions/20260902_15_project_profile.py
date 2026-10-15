"""Add revisioned enterprise project profile fields.

Revision ID: 20260902_15
Revises: 20260829_14
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260902_15"
down_revision: str | None = "20260829_14"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch_op:
        batch_op.add_column(
            sa.Column("profile", sa.JSON(), nullable=False, server_default=sa.text("'{}'"))
        )
    with op.batch_alter_table("project_revisions") as batch_op:
        batch_op.add_column(
            sa.Column("profile", sa.JSON(), nullable=False, server_default=sa.text("'{}'"))
        )
    with op.batch_alter_table("work_items") as batch_op:
        batch_op.add_column(sa.Column("owner_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("severity", sa.String(length=20), nullable=False, server_default="none"))
        batch_op.add_column(sa.Column("actual_minutes", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("component", sa.String(length=120), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("team", sa.String(length=120), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("checklist", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
        batch_op.add_column(sa.Column("watcher_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
        batch_op.add_column(sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.create_foreign_key("fk_work_items_owner_id_users", "users", ["owner_id"], ["id"])
        batch_op.create_index("ix_work_items_owner_id", ["owner_id"], unique=False)
        batch_op.create_index("ix_work_items_archived", ["archived"], unique=False)
    with op.batch_alter_table("notifications") as batch_op:
        batch_op.add_column(sa.Column("work_item_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_notifications_work_item_id_work_items", "work_items", ["work_item_id"], ["id"], ondelete="CASCADE"
        )
        batch_op.create_index("ix_notifications_work_item_id", ["work_item_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("notifications") as batch_op:
        batch_op.drop_index("ix_notifications_work_item_id")
        batch_op.drop_constraint("fk_notifications_work_item_id_work_items", type_="foreignkey")
        batch_op.drop_column("work_item_id")
    with op.batch_alter_table("work_items") as batch_op:
        batch_op.drop_index("ix_work_items_archived")
        batch_op.drop_index("ix_work_items_owner_id")
        batch_op.drop_constraint("fk_work_items_owner_id_users", type_="foreignkey")
        batch_op.drop_column("archived")
        batch_op.drop_column("watcher_ids")
        batch_op.drop_column("checklist")
        batch_op.drop_column("team")
        batch_op.drop_column("component")
        batch_op.drop_column("actual_minutes")
        batch_op.drop_column("severity")
        batch_op.drop_column("owner_id")
    with op.batch_alter_table("project_revisions") as batch_op:
        batch_op.drop_column("profile")
    with op.batch_alter_table("projects") as batch_op:
        batch_op.drop_column("profile")
