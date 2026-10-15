"""Add service desk, SLA, on-call, and guest portal records.

Revision ID: 20260915_29
Revises: 20260913_28
"""
from alembic import op
import sqlalchemy as sa


revision: str = "20260915_29"
down_revision: str | None = "20260913_28"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "service_tickets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requester_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("assignee_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(200), nullable=False), sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("ticket_type", sa.String(30), nullable=False, server_default="request"),
        sa.Column("status", sa.String(24), nullable=False, server_default="open"),
        sa.Column("severity", sa.String(16), nullable=False, server_default="normal"),
        sa.Column("priority", sa.String(16), nullable=False, server_default="medium"),
        sa.Column("service", sa.String(80), nullable=False, server_default="workspace"),
        sa.Column("source", sa.String(30), nullable=False, server_default="portal"),
        sa.Column("external_requester_email", sa.String(320), nullable=False, server_default=""),
        sa.Column("tags", sa.JSON(), nullable=False), sa.Column("custom_fields", sa.JSON(), nullable=False),
        sa.Column("response_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolution_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_response_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for name, columns in (
        ("ix_service_tickets_entity_id", ["entity_id"]), ("ix_service_tickets_requester_id", ["requester_id"]),
        ("ix_service_tickets_assignee_id", ["assignee_id"]), ("ix_service_tickets_project_id", ["project_id"]),
        ("ix_service_tickets_status", ["status"]), ("ix_service_tickets_severity", ["severity"]),
        ("ix_service_tickets_priority", ["priority"]), ("ix_service_tickets_ticket_type", ["ticket_type"]),
        ("ix_service_tickets_response_due_at", ["response_due_at"]), ("ix_service_tickets_resolution_due_at", ["resolution_due_at"]),
        ("ix_service_tickets_entity_status_updated", ["entity_id", "status", "updated_at"]),
        ("ix_service_tickets_entity_assignee", ["entity_id", "assignee_id", "status"]),
    ): op.create_index(name, "service_tickets", columns)
    op.create_table(
        "service_ticket_comments", sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ticket_id", sa.String(36), sa.ForeignKey("service_tickets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("external_author", sa.String(320), nullable=False, server_default=""), sa.Column("body", sa.Text(), nullable=False),
        sa.Column("internal", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_service_ticket_comments_ticket_id", "service_ticket_comments", ["ticket_id"])
    op.create_index("ix_service_ticket_comments_entity_id", "service_ticket_comments", ["entity_id"])
    op.create_table(
        "on_call_schedules", sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("service", sa.String(80), nullable=False), sa.Column("name", sa.String(160), nullable=False),
        sa.Column("member_ids", sa.JSON(), nullable=False), sa.Column("timezone", sa.String(64), nullable=False, server_default="UTC"),
        sa.Column("rotation", sa.JSON(), nullable=False), sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_on_call_schedules_entity_id", "on_call_schedules", ["entity_id"])
    op.create_index("ix_on_call_schedules_service", "on_call_schedules", ["service"])
    op.create_table(
        "guest_access_grants", sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("guest_email", sa.String(320), nullable=False), sa.Column("guest_name", sa.String(120), nullable=False, server_default=""),
        sa.Column("resource_type", sa.String(30), nullable=False), sa.Column("resource_id", sa.String(80), nullable=False),
        sa.Column("permissions", sa.JSON(), nullable=False), sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False), sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for name, columns in (("ix_guest_access_grants_entity_id", ["entity_id"]), ("ix_guest_access_grants_guest_email", ["guest_email"]), ("ix_guest_access_grants_token_hash", ["token_hash"]), ("ix_guest_access_grants_expires_at", ["expires_at"]), ("ix_guest_access_grants_revoked_at", ["revoked_at"]), ("ix_guest_access_entity_resource", ["entity_id", "resource_type", "resource_id"])):
        op.create_index(name, "guest_access_grants", columns)
    op.create_table(
        "guest_portal_activities", sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("grant_id", sa.String(36), sa.ForeignKey("guest_access_grants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action", sa.String(30), nullable=False), sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("metadata", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_guest_portal_activities_grant_id", "guest_portal_activities", ["grant_id"])
    op.create_index("ix_guest_portal_activities_entity_id", "guest_portal_activities", ["entity_id"])


def downgrade() -> None:
    op.drop_table("guest_portal_activities")
    op.drop_table("guest_access_grants")
    op.drop_table("on_call_schedules")
    op.drop_table("service_ticket_comments")
    op.drop_table("service_tickets")
