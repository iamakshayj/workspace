"""Add project governance, revisions, approvals, and audit events.

Revision ID: 20260827_01
Revises: 20260826_00
Create Date: 2026-08-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260827_01"
down_revision: Union[str, Sequence[str], None] = "20260826_00"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("visibility", sa.String(length=20), nullable=False, server_default="workspace"),
    )
    op.add_column(
        "projects",
        sa.Column("approval_status", sa.String(length=24), nullable=False, server_default="draft"),
    )
    op.add_column(
        "project_collaborators",
        sa.Column("access_role", sa.String(length=20), nullable=False, server_default="viewer"),
    )
    op.execute(
        "UPDATE project_collaborators SET access_role = 'editor' "
        "WHERE user_id IN (SELECT id FROM users WHERE role = 'admin')"
    )
    op.create_table(
        "project_revisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("source_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("graph", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False),
        sa.Column("change_summary", sa.String(length=240), nullable=False, server_default="Saved changes"),
        sa.Column("created_by_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "version", name="uq_project_revision_version"),
    )
    op.create_index("ix_project_revisions_project_id", "project_revisions", ["project_id"])
    op.create_index("ix_project_revisions_created_by_id", "project_revisions", ["created_by_id"])
    op.create_table(
        "project_approvals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("revision_id", sa.String(length=36), nullable=False),
        sa.Column("requested_by_id", sa.String(length=36), nullable=False),
        sa.Column("reviewer_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="pending"),
        sa.Column("request_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("decision_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["revision_id"], ["project_revisions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("project_id", "revision_id", "requested_by_id", "reviewer_id"):
        op.create_index(f"ix_project_approvals_{column}", "project_approvals", [column])
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("actor_id", sa.String(length=36), nullable=True),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("target_type", sa.String(length=40), nullable=False, server_default="project"),
        sa.Column("target_id", sa.String(length=36), nullable=True),
        sa.Column("details", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["entity_id"], ["entities.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("entity_id", "project_id", "actor_id", "action", "created_at"):
        op.create_index(f"ix_audit_events_{column}", "audit_events", [column])


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("project_approvals")
    op.drop_table("project_revisions")
    op.drop_column("project_collaborators", "access_role")
    op.drop_column("projects", "approval_status")
    op.drop_column("projects", "visibility")
