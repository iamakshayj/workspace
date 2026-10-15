"""Add hierarchical and subscribable knowledge pages.

Revision ID: 20260912_20
Revises: 20260903_19
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260912_20"
down_revision: str | None = "20260903_19"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("knowledge_documents") as batch_op:
        batch_op.add_column(sa.Column("parent_id", sa.String(36), nullable=True))
        batch_op.add_column(sa.Column("icon", sa.String(16), nullable=False, server_default="▤"))
        batch_op.add_column(sa.Column("labels", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
        batch_op.add_column(sa.Column("watcher_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
        batch_op.add_column(sa.Column("position", sa.Integer(), nullable=False, server_default="1024"))
        batch_op.create_foreign_key(
            "fk_knowledge_documents_parent_id", "knowledge_documents", ["parent_id"], ["id"], ondelete="SET NULL",
        )
        batch_op.create_index("ix_knowledge_documents_parent_id", ["parent_id"], unique=False)
        batch_op.create_index("ix_knowledge_documents_space_position", ["space_id", "position"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("knowledge_documents") as batch_op:
        batch_op.drop_index("ix_knowledge_documents_space_position")
        batch_op.drop_index("ix_knowledge_documents_parent_id")
        batch_op.drop_constraint("fk_knowledge_documents_parent_id", type_="foreignkey")
        batch_op.drop_column("position")
        batch_op.drop_column("watcher_ids")
        batch_op.drop_column("labels")
        batch_op.drop_column("icon")
        batch_op.drop_column("parent_id")
