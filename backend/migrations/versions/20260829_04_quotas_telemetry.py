"""Add tenant quotas and retention metadata.

Revision ID: 20260829_04
Revises: 20260829_03
Create Date: 2026-08-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260829_04"
down_revision: Union[str, Sequence[str], None] = "20260829_03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "entities",
        sa.Column("max_users", sa.Integer(), nullable=False, server_default="100"),
    )
    op.add_column(
        "entities",
        sa.Column("max_projects", sa.Integer(), nullable=False, server_default="1000"),
    )
    op.add_column(
        "entities",
        sa.Column(
            "max_storage_bytes",
            sa.BigInteger(),
            nullable=False,
            server_default="10737418240",
        ),
    )
    op.add_column(
        "entities",
        sa.Column("max_monthly_generations", sa.Integer(), nullable=False, server_default="1000"),
    )
    op.add_column(
        "entities",
        sa.Column("max_pending_generations", sa.Integer(), nullable=False, server_default="20"),
    )

    op.add_column(
        "project_attachments",
        sa.Column("entity_id", sa.String(length=36), nullable=True),
    )
    op.execute(
        "UPDATE project_attachments SET entity_id = ("
        "SELECT projects.entity_id FROM projects "
        "WHERE projects.id = project_attachments.project_id)"
    )
    with op.batch_alter_table("project_attachments") as batch_op:
        batch_op.alter_column(
            "entity_id",
            existing_type=sa.String(length=36),
            nullable=False,
        )
        batch_op.create_foreign_key(
            "fk_project_attachments_entity_id_entities",
            "entities",
            ["entity_id"],
            ["id"],
        )
        batch_op.create_index(
            "ix_project_attachments_entity_id",
            ["entity_id"],
            unique=False,
        )

    op.add_column(
        "background_jobs",
        sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("background_jobs", "purged_at")
    with op.batch_alter_table("project_attachments") as batch_op:
        batch_op.drop_index("ix_project_attachments_entity_id")
        batch_op.drop_constraint(
            "fk_project_attachments_entity_id_entities",
            type_="foreignkey",
        )
        batch_op.drop_column("entity_id")

    for column_name in (
        "max_pending_generations",
        "max_monthly_generations",
        "max_storage_bytes",
        "max_projects",
        "max_users",
    ):
        op.drop_column("entities", column_name)
