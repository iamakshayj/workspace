"""Connect flowchart nodes to agile work, sprints, and subflows.

Revision ID: 20260829_08
Revises: 20260829_07
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260829_08"
down_revision: str | None = "20260829_07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_work_items_project_node", "work_items", ["project_id", "node_id"])
    op.create_table(
        "node_planning_bindings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.id"), nullable=False),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("node_id", sa.String(80), nullable=False),
        sa.Column("primary_work_item_id", sa.String(36), sa.ForeignKey("work_items.id", ondelete="SET NULL"), nullable=True),
        sa.Column("sprint_id", sa.String(36), sa.ForeignKey("agile_sprints.id", ondelete="SET NULL"), nullable=True),
        sa.Column("subflow_project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "node_id", name="uq_node_planning_project_node"),
    )
    for name, columns in (
        ("ix_node_planning_bindings_entity_id", ["entity_id"]),
        ("ix_node_planning_bindings_project_id", ["project_id"]),
        ("ix_node_planning_bindings_node_id", ["node_id"]),
        ("ix_node_planning_bindings_primary_work_item_id", ["primary_work_item_id"]),
        ("ix_node_planning_bindings_sprint_id", ["sprint_id"]),
        ("ix_node_planning_bindings_subflow_project_id", ["subflow_project_id"]),
        ("ix_node_planning_bindings_created_by_id", ["created_by_id"]),
        ("ix_node_planning_entity_project", ["entity_id", "project_id"]),
    ):
        op.create_index(name, "node_planning_bindings", columns)


def downgrade() -> None:
    op.drop_table("node_planning_bindings")
    op.drop_index("ix_work_items_project_node", table_name="work_items")
