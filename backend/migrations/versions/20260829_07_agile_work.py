"""Add tenant-scoped agile work management.

Revision ID: 20260829_07
Revises: 20260829_06
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260829_07"
down_revision: str | None = "20260829_06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agile_sprints",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.id"), nullable=False),
        sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="planned"),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("capacity_points", sa.Integer(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agile_sprints_entity_id", "agile_sprints", ["entity_id"])
    op.create_index("ix_agile_sprints_created_by_id", "agile_sprints", ["created_by_id"])
    op.create_index("ix_agile_sprints_entity_status", "agile_sprints", ["entity_id", "status"])

    op.create_table(
        "agile_releases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.id"), nullable=False),
        sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="planned"),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agile_releases_entity_id", "agile_releases", ["entity_id"])
    op.create_index("ix_agile_releases_created_by_id", "agile_releases", ["created_by_id"])
    op.create_index("ix_agile_releases_entity_status", "agile_releases", ["entity_id", "status"])

    op.create_table(
        "work_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.id"), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(24), nullable=False),
        sa.Column("reporter_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("assignee_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("sprint_id", sa.String(36), sa.ForeignKey("agile_sprints.id", ondelete="SET NULL"), nullable=True),
        sa.Column("release_id", sa.String(36), sa.ForeignKey("agile_releases.id", ondelete="SET NULL"), nullable=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("parent_id", sa.String(36), sa.ForeignKey("work_items.id", ondelete="SET NULL"), nullable=True),
        sa.Column("node_id", sa.String(80), nullable=True),
        sa.Column("item_type", sa.String(20), nullable=False, server_default="task"),
        sa.Column("summary", sa.String(180), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("acceptance_criteria", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(24), nullable=False, server_default="backlog"),
        sa.Column("priority", sa.String(20), nullable=False, server_default="medium"),
        sa.Column("story_points", sa.Integer(), nullable=True),
        sa.Column("estimate_minutes", sa.Integer(), nullable=True),
        sa.Column("labels", sa.JSON(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("rank", sa.Float(), nullable=False, server_default="1024"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("entity_id", "sequence_number", name="uq_work_item_entity_sequence"),
        sa.UniqueConstraint("entity_id", "key", name="uq_work_item_entity_key"),
    )
    for name, columns in (
        ("ix_work_items_entity_id", ["entity_id"]), ("ix_work_items_reporter_id", ["reporter_id"]),
        ("ix_work_items_assignee_id", ["assignee_id"]), ("ix_work_items_sprint_id", ["sprint_id"]),
        ("ix_work_items_release_id", ["release_id"]), ("ix_work_items_project_id", ["project_id"]),
        ("ix_work_items_parent_id", ["parent_id"]),
        ("ix_work_items_entity_status_rank", ["entity_id", "status", "rank"]),
        ("ix_work_items_entity_sprint_rank", ["entity_id", "sprint_id", "rank"]),
        ("ix_work_items_entity_assignee_status", ["entity_id", "assignee_id", "status"]),
    ):
        op.create_index(name, "work_items", columns)

    op.create_table(
        "work_item_comments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.id"), nullable=False),
        sa.Column("work_item_id", sa.String(36), sa.ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_work_item_comments_entity_id", "work_item_comments", ["entity_id"])
    op.create_index("ix_work_item_comments_work_item_id", "work_item_comments", ["work_item_id"])
    op.create_index("ix_work_item_comments_author_id", "work_item_comments", ["author_id"])

    op.create_table(
        "work_item_links",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.id"), nullable=False),
        sa.Column("source_id", sa.String(36), sa.ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_id", sa.String(36), sa.ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("link_type", sa.String(24), nullable=False, server_default="relates_to"),
        sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_id", "target_id", "link_type", name="uq_work_item_link"),
    )
    for column in ("entity_id", "source_id", "target_id"):
        op.create_index(f"ix_work_item_links_{column}", "work_item_links", [column])

    op.create_table(
        "work_item_activity",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.id"), nullable=False),
        sa.Column("work_item_id", sa.String(36), sa.ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("changes", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_work_item_activity_entity_id", "work_item_activity", ["entity_id"])
    op.create_index("ix_work_item_activity_work_item_id", "work_item_activity", ["work_item_id"])
    op.create_index("ix_work_item_activity_actor_id", "work_item_activity", ["actor_id"])
    op.create_index("ix_work_item_activity_item_created", "work_item_activity", ["work_item_id", "created_at"])


def downgrade() -> None:
    op.drop_table("work_item_activity")
    op.drop_table("work_item_links")
    op.drop_table("work_item_comments")
    op.drop_table("work_items")
    op.drop_table("agile_releases")
    op.drop_table("agile_sprints")
