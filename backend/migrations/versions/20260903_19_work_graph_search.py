"""Add enterprise work graph history and saved search state.

Revision ID: 20260903_19
Revises: 20260903_18
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260903_19"
down_revision: str | None = "20260903_18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_DEFAULT = sa.text("'{}'")


def upgrade() -> None:
    op.create_table(
        "object_relationship_history",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.id"), nullable=False, index=True),
        sa.Column("relationship_id", sa.String(36), nullable=False, index=True),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("source_id", sa.String(80), nullable=False),
        sa.Column("target_type", sa.String(40), nullable=False),
        sa.Column("target_id", sa.String(80), nullable=False),
        sa.Column("relationship_type", sa.String(40), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=JSON_DEFAULT),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_relationship_history_entity_relationship",
        "object_relationship_history",
        ["entity_id", "relationship_id", "created_at"],
    )
    op.create_index(
        "ix_relationship_history_object",
        "object_relationship_history",
        ["entity_id", "source_type", "source_id", "created_at"],
    )

    op.create_table(
        "saved_searches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.id"), nullable=False, index=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("query", sa.String(500), nullable=False, server_default=""),
        sa.Column("mode", sa.String(20), nullable=False, server_default="keyword"),
        sa.Column("filters", sa.JSON(), nullable=False, server_default=JSON_DEFAULT),
        sa.Column("shared", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("owner_id", "name", name="uq_saved_search_owner_name"),
    )
    op.create_index("ix_saved_searches_entity_owner", "saved_searches", ["entity_id", "owner_id", "updated_at"])

    op.create_table(
        "recent_searches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.id"), nullable=False, index=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("query", sa.String(500), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False, server_default="keyword"),
        sa.Column("filters", sa.JSON(), nullable=False, server_default=JSON_DEFAULT),
        sa.Column("result_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("searched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), index=True),
    )
    op.create_index("ix_recent_searches_user_searched", "recent_searches", ["user_id", "searched_at"])


def downgrade() -> None:
    op.drop_table("recent_searches")
    op.drop_table("saved_searches")
    op.drop_table("object_relationship_history")
