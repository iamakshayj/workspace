"""Add governed, reversible work-graph change proposals.

Revision ID: 20260913_28
Revises: 20260912_27
"""
from alembic import op
import sqlalchemy as sa


revision: str = "20260913_28"
down_revision: str | None = "20260912_27"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "change_proposals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.id"), nullable=False),
        sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reviewed_by_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("applied_by_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("rolled_back_by_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False, server_default=""),
        sa.Column("target_type", sa.String(40), nullable=False, server_default="relationship"),
        sa.Column("target_id", sa.String(80), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("operations", sa.JSON(), nullable=False),
        sa.Column("preview", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("before_snapshot", sa.JSON(), nullable=False),
        sa.Column("after_snapshot", sa.JSON(), nullable=False),
        sa.Column("decision_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("failure_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("entity_id", "idempotency_key", name="uq_change_proposal_entity_idempotency"),
    )
    op.create_index("ix_change_proposals_entity_id", "change_proposals", ["entity_id"])
    op.create_index("ix_change_proposals_created_by_id", "change_proposals", ["created_by_id"])
    op.create_index("ix_change_proposals_reviewed_by_id", "change_proposals", ["reviewed_by_id"])
    op.create_index("ix_change_proposals_applied_by_id", "change_proposals", ["applied_by_id"])
    op.create_index("ix_change_proposals_rolled_back_by_id", "change_proposals", ["rolled_back_by_id"])
    op.create_index("ix_change_proposals_status", "change_proposals", ["status"])
    op.create_index("ix_change_proposals_entity_status_updated", "change_proposals", ["entity_id", "status", "updated_at"])
    op.create_index("ix_change_proposals_target", "change_proposals", ["entity_id", "target_type", "target_id"])


def downgrade() -> None:
    op.drop_table("change_proposals")
