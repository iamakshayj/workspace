"""Add generated export and evidence artifacts.

Revision ID: 20260829_05
Revises: 20260829_04
Create Date: 2026-08-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260829_05"
down_revision: Union[str, Sequence[str], None] = "20260829_04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "generated_artifacts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=True),
        sa.Column("created_by_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("format", sa.String(length=20), nullable=False),
        sa.Column("filename", sa.String(length=240), nullable=False),
        sa.Column("content_type", sa.String(length=160), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("storage_key", sa.String(length=900), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["entity_id"], ["entities.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["background_jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_generated_artifacts_created_by_id",
        "generated_artifacts",
        ["created_by_id"],
    )
    op.create_index(
        "ix_generated_artifacts_entity_created",
        "generated_artifacts",
        ["entity_id", "created_at"],
    )
    op.create_index(
        "ix_generated_artifacts_entity_id",
        "generated_artifacts",
        ["entity_id"],
    )
    op.create_index(
        "ix_generated_artifacts_expires",
        "generated_artifacts",
        ["expires_at"],
    )
    op.create_index(
        "ix_generated_artifacts_job_id",
        "generated_artifacts",
        ["job_id"],
        unique=True,
    )
    op.create_index(
        "ix_generated_artifacts_kind",
        "generated_artifacts",
        ["kind"],
    )
    op.create_index(
        "ix_generated_artifacts_project_created",
        "generated_artifacts",
        ["project_id", "created_at"],
    )
    op.create_index(
        "ix_generated_artifacts_project_id",
        "generated_artifacts",
        ["project_id"],
    )
    op.create_index(
        "ix_generated_artifacts_storage_key",
        "generated_artifacts",
        ["storage_key"],
        unique=True,
    )


def downgrade() -> None:
    for index_name in (
        "ix_generated_artifacts_storage_key",
        "ix_generated_artifacts_project_id",
        "ix_generated_artifacts_project_created",
        "ix_generated_artifacts_kind",
        "ix_generated_artifacts_job_id",
        "ix_generated_artifacts_expires",
        "ix_generated_artifacts_entity_id",
        "ix_generated_artifacts_entity_created",
        "ix_generated_artifacts_created_by_id",
    ):
        op.drop_index(index_name, table_name="generated_artifacts")
    op.drop_table("generated_artifacts")
