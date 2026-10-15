"""Add indexes for tenant project pagination and search.

Revision ID: 20260827_02
Revises: 20260827_01
Create Date: 2026-08-27
"""
from typing import Sequence, Union

from alembic import op


revision: str = "20260827_02"
down_revision: Union[str, Sequence[str], None] = "20260827_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_projects_entity_updated_id",
        "projects",
        ["entity_id", "updated_at", "id"],
    )
    op.create_index("ix_projects_title", "projects", ["title"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX ix_projects_search ON projects USING GIN "
            "(to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(description, '')))"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_projects_search")
    op.drop_index("ix_projects_title", table_name="projects")
    op.drop_index("ix_projects_entity_updated_id", table_name="projects")
