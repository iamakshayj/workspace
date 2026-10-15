"""Add durable jobs and object-storage attachment metadata.

Revision ID: 20260829_03
Revises: 20260827_02
Create Date: 2026-08-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260829_03"
down_revision: Union[str, Sequence[str], None] = "20260827_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def json_type() -> sa.types.TypeEngine:
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "background_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("created_by_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("payload", json_type(), nullable=False),
        sa.Column("result", json_type(), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["entity_id"], ["entities.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_background_jobs_claim", "background_jobs", ["status", "available_at", "created_at"])
    op.create_index("ix_background_jobs_created_by_id", "background_jobs", ["created_by_id"])
    op.create_index("ix_background_jobs_entity_created", "background_jobs", ["entity_id", "created_at"])
    op.create_index("ix_background_jobs_entity_id", "background_jobs", ["entity_id"])
    op.create_index("ix_background_jobs_kind", "background_jobs", ["kind"])
    op.create_index("ix_background_jobs_status", "background_jobs", ["status"])

    op.add_column("project_attachments", sa.Column("storage_key", sa.String(length=900), nullable=True))
    op.add_column(
        "project_attachments",
        sa.Column("upload_status", sa.String(length=20), nullable=False, server_default="complete"),
    )
    op.add_column(
        "project_attachments",
        sa.Column("scan_status", sa.String(length=20), nullable=False, server_default="clean"),
    )
    op.add_column("project_attachments", sa.Column("scan_message", sa.String(length=240), nullable=True))
    op.add_column("project_attachments", sa.Column("object_etag", sa.String(length=160), nullable=True))
    op.add_column("project_attachments", sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE project_attachments SET uploaded_at = created_at WHERE uploaded_at IS NULL")
    op.alter_column("project_attachments", "content", existing_type=sa.LargeBinary(), nullable=True)
    op.create_index(
        "ix_project_attachments_scan_status",
        "project_attachments",
        ["scan_status"],
    )
    op.create_index(
        "ix_project_attachments_storage_key",
        "project_attachments",
        ["storage_key"],
        unique=True,
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("UPDATE project_attachments SET content = ''::bytea WHERE content IS NULL")
    else:
        op.execute("UPDATE project_attachments SET content = X'' WHERE content IS NULL")
    op.drop_index("ix_project_attachments_storage_key", table_name="project_attachments")
    op.drop_index("ix_project_attachments_scan_status", table_name="project_attachments")
    op.alter_column("project_attachments", "content", existing_type=sa.LargeBinary(), nullable=False)
    for column_name in (
        "uploaded_at",
        "object_etag",
        "scan_message",
        "scan_status",
        "upload_status",
        "storage_key",
    ):
        op.drop_column("project_attachments", column_name)

    op.drop_index("ix_background_jobs_status", table_name="background_jobs")
    op.drop_index("ix_background_jobs_kind", table_name="background_jobs")
    op.drop_index("ix_background_jobs_entity_id", table_name="background_jobs")
    op.drop_index("ix_background_jobs_entity_created", table_name="background_jobs")
    op.drop_index("ix_background_jobs_created_by_id", table_name="background_jobs")
    op.drop_index("ix_background_jobs_claim", table_name="background_jobs")
    op.drop_table("background_jobs")
