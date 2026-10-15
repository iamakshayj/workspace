"""Add process intelligence events, imports, and drift insights.

Revision ID: 20260829_06
Revises: 20260829_05
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260829_06"
down_revision: str | None = "20260829_05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "process_event_imports",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("imported_by_id", sa.String(length=36), nullable=False),
        sa.Column("filename", sa.String(length=240), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.Column("case_count", sa.Integer(), nullable=False),
        sa.Column("activity_node_map", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["entity_id"], ["entities.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["imported_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_process_event_imports_entity_id", "process_event_imports", ["entity_id"])
    op.create_index("ix_process_event_imports_project_id", "process_event_imports", ["project_id"])
    op.create_index("ix_process_event_imports_imported_by_id", "process_event_imports", ["imported_by_id"])
    op.create_index(
        "ix_process_event_imports_project_created",
        "process_event_imports",
        ["project_id", "created_at"],
    )

    op.create_table(
        "process_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("import_id", sa.String(length=36), nullable=False),
        sa.Column("case_id", sa.String(length=160), nullable=False),
        sa.Column("activity", sa.String(length=240), nullable=False),
        sa.Column("node_id", sa.String(length=80), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=80), nullable=True),
        sa.Column("owner", sa.String(length=160), nullable=True),
        sa.Column("cost", sa.Float(), nullable=True),
        sa.Column("attributes", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["entity_id"], ["entities.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["import_id"], ["process_event_imports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for name, columns in (
        ("ix_process_events_entity_id", ["entity_id"]),
        ("ix_process_events_project_id", ["project_id"]),
        ("ix_process_events_import_id", ["import_id"]),
        ("ix_process_events_node_id", ["node_id"]),
        ("ix_process_events_project_occurred", ["project_id", "occurred_at"]),
        ("ix_process_events_project_case_occurred", ["project_id", "case_id", "occurred_at"]),
        ("ix_process_events_project_node", ["project_id", "node_id"]),
    ):
        op.create_index(name, "process_events", columns)

    op.create_table(
        "process_insights",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("import_id", sa.String(length=36), nullable=True),
        sa.Column("kind", sa.String(length=60), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=180), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("node_id", sa.String(length=80), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by_id", sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(["entity_id"], ["entities.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["import_id"], ["process_event_imports.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resolved_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for name, columns in (
        ("ix_process_insights_entity_id", ["entity_id"]),
        ("ix_process_insights_project_id", ["project_id"]),
        ("ix_process_insights_import_id", ["import_id"]),
        ("ix_process_insights_kind", ["kind"]),
        ("ix_process_insights_node_id", ["node_id"]),
        ("ix_process_insights_status", ["status"]),
        ("ix_process_insights_project_status_detected", ["project_id", "status", "detected_at"]),
    ):
        op.create_index(name, "process_insights", columns)


def downgrade() -> None:
    op.drop_table("process_insights")
    op.drop_table("process_events")
    op.drop_table("process_event_imports")
