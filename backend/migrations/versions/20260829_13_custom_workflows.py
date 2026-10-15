"""Add customizable entity work workflows.

Revision ID: 20260829_13
Revises: 20260829_12
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260829_13"
down_revision: str | None = "20260829_12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("entities") as batch_op:
        batch_op.add_column(sa.Column("work_columns", JSON_TYPE, nullable=True))
        batch_op.add_column(sa.Column("work_item_types", JSON_TYPE, nullable=True))
    with op.batch_alter_table("work_items") as batch_op:
        batch_op.alter_column("item_type", existing_type=sa.String(length=20), type_=sa.String(length=40), existing_nullable=False)
        batch_op.alter_column("status", existing_type=sa.String(length=24), type_=sa.String(length=40), existing_nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("work_items") as batch_op:
        batch_op.alter_column("status", existing_type=sa.String(length=40), type_=sa.String(length=24), existing_nullable=False)
        batch_op.alter_column("item_type", existing_type=sa.String(length=40), type_=sa.String(length=20), existing_nullable=False)
    with op.batch_alter_table("entities") as batch_op:
        batch_op.drop_column("work_item_types")
        batch_op.drop_column("work_columns")
