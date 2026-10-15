"""Add tenant residency controls and the knowledge module.

Revision ID: 20260903_17
Revises: 20260902_16
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260903_17"
down_revision: str | None = "20260902_16"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def upgrade() -> None:
    with op.batch_alter_table("entities") as batch_op:
        batch_op.add_column(sa.Column("data_region", sa.String(length=40), nullable=False, server_default="us-central"))
        batch_op.add_column(sa.Column("data_residency_locked", sa.Boolean(), nullable=False, server_default=sa.false()))

    op.create_table(
        "knowledge_spaces",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("entity_id", sa.String(length=36), sa.ForeignKey("entities.id"), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("visibility", sa.String(length=20), nullable=False, server_default="workspace"),
        sa.Column("created_by_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("entity_id", "name", name="uq_knowledge_space_entity_name"),
    )
    op.create_index("ix_knowledge_spaces_entity_id", "knowledge_spaces", ["entity_id"])
    op.create_index("ix_knowledge_spaces_created_by_id", "knowledge_spaces", ["created_by_id"])
    op.create_index("ix_knowledge_spaces_entity_updated", "knowledge_spaces", ["entity_id", "updated_at"])

    op.create_table(
        "knowledge_space_members",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("space_id", sa.String(length=36), sa.ForeignKey("knowledge_spaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False, server_default="viewer"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("space_id", "user_id", name="uq_knowledge_space_member"),
    )
    op.create_index("ix_knowledge_space_members_space_id", "knowledge_space_members", ["space_id"])
    op.create_index("ix_knowledge_space_members_user_id", "knowledge_space_members", ["user_id"])

    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("entity_id", sa.String(length=36), sa.ForeignKey("entities.id"), nullable=False),
        sa.Column("space_id", sa.String(length=36), sa.ForeignKey("knowledge_spaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(length=180), nullable=False),
        sa.Column("slug", sa.String(length=220), nullable=False),
        sa.Column("summary", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("visibility", sa.String(length=20), nullable=False, server_default="workspace"),
        sa.Column("classification", sa.String(length=20), nullable=False, server_default="internal"),
        sa.Column("template", sa.String(length=40), nullable=False, server_default="blank"),
        sa.Column("review_due_at", sa.Date(), nullable=True),
        sa.Column("expires_at", sa.Date(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        *timestamps(),
        sa.UniqueConstraint("entity_id", "slug", name="uq_knowledge_document_entity_slug"),
    )
    for column in ("entity_id", "space_id", "owner_id", "status", "review_due_at", "expires_at"):
        op.create_index(f"ix_knowledge_documents_{column}", "knowledge_documents", [column])
    op.create_index("ix_knowledge_documents_entity_updated", "knowledge_documents", ["entity_id", "updated_at"])
    op.create_index("ix_knowledge_documents_space_updated", "knowledge_documents", ["space_id", "updated_at"])

    op.create_table(
        "knowledge_document_access",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("document_id", sa.String(length=36), sa.ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False, server_default="viewer"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("document_id", "user_id", name="uq_knowledge_document_access"),
    )
    op.create_index("ix_knowledge_document_access_document_id", "knowledge_document_access", ["document_id"])
    op.create_index("ix_knowledge_document_access_user_id", "knowledge_document_access", ["user_id"])

    op.create_table(
        "knowledge_document_revisions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("document_id", sa.String(length=36), sa.ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=180), nullable=False),
        sa.Column("summary", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("classification", sa.String(length=20), nullable=False),
        sa.Column("change_summary", sa.String(length=240), nullable=False, server_default="Saved changes"),
        sa.Column("created_by_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("document_id", "version", name="uq_knowledge_document_revision_version"),
    )
    op.create_index("ix_knowledge_document_revisions_document_id", "knowledge_document_revisions", ["document_id"])
    op.create_index("ix_knowledge_document_revisions_created_by_id", "knowledge_document_revisions", ["created_by_id"])

    op.create_table(
        "knowledge_comments",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("document_id", sa.String(length=36), sa.ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("parent_id", sa.String(length=36), sa.ForeignKey("knowledge_comments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
    )
    for column in ("document_id", "author_id", "parent_id"):
        op.create_index(f"ix_knowledge_comments_{column}", "knowledge_comments", [column])
    op.create_index("ix_knowledge_comments_document_created", "knowledge_comments", ["document_id", "created_at"])

    op.create_table(
        "knowledge_document_links",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("source_document_id", sa.String(length=36), sa.ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_document_id", sa.String(length=36), sa.ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("source_document_id", "target_document_id", name="uq_knowledge_document_link"),
    )
    op.create_index("ix_knowledge_document_links_source_document_id", "knowledge_document_links", ["source_document_id"])
    op.create_index("ix_knowledge_document_links_target_document_id", "knowledge_document_links", ["target_document_id"])

    with op.batch_alter_table("notifications") as batch_op:
        batch_op.add_column(sa.Column("document_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key("fk_notifications_document_id", "knowledge_documents", ["document_id"], ["id"], ondelete="CASCADE")
        batch_op.create_index("ix_notifications_document_id", ["document_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("notifications") as batch_op:
        batch_op.drop_index("ix_notifications_document_id")
        batch_op.drop_constraint("fk_notifications_document_id", type_="foreignkey")
        batch_op.drop_column("document_id")
    op.drop_table("knowledge_document_links")
    op.drop_table("knowledge_comments")
    op.drop_table("knowledge_document_revisions")
    op.drop_table("knowledge_document_access")
    op.drop_table("knowledge_documents")
    op.drop_table("knowledge_space_members")
    op.drop_table("knowledge_spaces")
    with op.batch_alter_table("entities") as batch_op:
        batch_op.drop_column("data_residency_locked")
        batch_op.drop_column("data_region")
