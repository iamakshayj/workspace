"""Add cross-module enterprise management foundations.

Revision ID: 20260903_18
Revises: 20260903_17
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260903_18"
down_revision: str | None = "20260903_17"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_DEFAULT = sa.text("'{}'")
LIST_DEFAULT = sa.text("'[]'")


def created() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def updated() -> sa.Column:
    return sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def upgrade() -> None:
    with op.batch_alter_table("entities") as b:
        b.add_column(sa.Column("governance_settings", sa.JSON(), nullable=False, server_default=JSON_DEFAULT))
    with op.batch_alter_table("users") as b:
        b.add_column(sa.Column("job_title", sa.String(120), nullable=False, server_default=""))
        b.add_column(sa.Column("timezone", sa.String(64), nullable=False, server_default="UTC"))
        b.add_column(sa.Column("manager_id", sa.String(36), nullable=True))
        b.add_column(sa.Column("skills", sa.JSON(), nullable=False, server_default=LIST_DEFAULT))
        b.add_column(sa.Column("weekly_capacity_hours", sa.Float(), nullable=False, server_default="40"))
        b.add_column(sa.Column("profile", sa.JSON(), nullable=False, server_default=JSON_DEFAULT))
        b.create_foreign_key("fk_users_manager_id", "users", ["manager_id"], ["id"], ondelete="SET NULL")
        b.create_index("ix_users_manager_id", ["manager_id"])
    with op.batch_alter_table("projects") as b:
        b.add_column(sa.Column("settings", sa.JSON(), nullable=False, server_default=JSON_DEFAULT))
    with op.batch_alter_table("audit_events") as b:
        b.add_column(sa.Column("request_id", sa.String(80), nullable=True))
        b.add_column(sa.Column("previous_hash", sa.String(64), nullable=True))
        b.add_column(sa.Column("event_hash", sa.String(64), nullable=True))
        b.create_index("ix_audit_events_request_id", ["request_id"])
        b.create_unique_constraint("uq_audit_events_event_hash", ["event_hash"])
    with op.batch_alter_table("calendar_events") as b:
        b.add_column(sa.Column("agenda", sa.Text(), nullable=False, server_default=""))
        b.add_column(sa.Column("notes", sa.Text(), nullable=False, server_default=""))
        b.add_column(sa.Column("action_items", sa.JSON(), nullable=False, server_default=LIST_DEFAULT))
        b.add_column(sa.Column("transcript", sa.Text(), nullable=False, server_default=""))
        b.add_column(sa.Column("recording_url", sa.String(500), nullable=False, server_default=""))
    with op.batch_alter_table("notifications") as b:
        b.add_column(sa.Column("group_key", sa.String(120), nullable=True))
        b.add_column(sa.Column("snoozed_until", sa.DateTime(timezone=True), nullable=True))
        b.create_index("ix_notifications_group_key", ["group_key"])
        b.create_index("ix_notifications_snoozed_until", ["snoozed_until"])
    with op.batch_alter_table("work_items") as b:
        b.add_column(sa.Column("custom_fields", sa.JSON(), nullable=False, server_default=JSON_DEFAULT))
    with op.batch_alter_table("agile_releases") as b:
        b.add_column(sa.Column("baseline", sa.JSON(), nullable=False, server_default=JSON_DEFAULT))
        b.add_column(sa.Column("scenario", sa.String(40), nullable=False, server_default="committed"))
    with op.batch_alter_table("work_item_comments") as b:
        b.add_column(sa.Column("parent_id", sa.String(36), nullable=True))
        b.add_column(sa.Column("reactions", sa.JSON(), nullable=False, server_default=JSON_DEFAULT))
        b.add_column(sa.Column("attachments", sa.JSON(), nullable=False, server_default=LIST_DEFAULT))
        b.create_foreign_key("fk_work_item_comments_parent_id", "work_item_comments", ["parent_id"], ["id"], ondelete="SET NULL")
        b.create_index("ix_work_item_comments_parent_id", ["parent_id"])

    op.create_table("organization_units",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.id"), nullable=False, index=True),
        sa.Column("parent_id", sa.String(36), sa.ForeignKey("organization_units.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("manager_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("name", sa.String(140), nullable=False), sa.Column("unit_type", sa.String(24), nullable=False, server_default="team"),
        sa.Column("description", sa.String(500), nullable=False, server_default=""), sa.Column("timezone", sa.String(64), nullable=False, server_default="UTC"),
        sa.Column("weekly_capacity_hours", sa.Float(), nullable=False, server_default="40"), created(), updated(),
        sa.UniqueConstraint("entity_id", "name", "unit_type", name="uq_org_unit_entity_name_type"))
    op.create_table("organization_unit_members",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("unit_id", sa.String(36), sa.ForeignKey("organization_units.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("membership_role", sa.String(24), nullable=False, server_default="member"), sa.Column("allocation_percent", sa.Integer(), nullable=False, server_default="100"), created(),
        sa.UniqueConstraint("unit_id", "user_id", name="uq_org_unit_member"))
    op.create_table("project_group_access",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("unit_id", sa.String(36), sa.ForeignKey("organization_units.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("access_role", sa.String(20), nullable=False, server_default="viewer"), created(),
        sa.UniqueConstraint("project_id", "unit_id", name="uq_project_group_access"))
    op.create_table("object_relationships",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.id"), nullable=False, index=True),
        sa.Column("source_type", sa.String(40), nullable=False), sa.Column("source_id", sa.String(80), nullable=False), sa.Column("target_type", sa.String(40), nullable=False), sa.Column("target_id", sa.String(80), nullable=False),
        sa.Column("relationship_type", sa.String(40), nullable=False), sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=JSON_DEFAULT), sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, index=True), created(),
        sa.UniqueConstraint("entity_id", "source_type", "source_id", "target_type", "target_id", "relationship_type", name="uq_object_relationship"))
    op.create_index("ix_object_relationships_source", "object_relationships", ["entity_id", "source_type", "source_id"])
    op.create_index("ix_object_relationships_target", "object_relationships", ["entity_id", "target_type", "target_id"])
    op.create_table("project_risks",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.id"), nullable=False, index=True), sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True), sa.Column("title", sa.String(180), nullable=False), sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("probability", sa.Integer(), nullable=False, server_default="1"), sa.Column("impact", sa.Integer(), nullable=False, server_default="1"), sa.Column("status", sa.String(24), nullable=False, server_default="open"),
        sa.Column("mitigation", sa.Text(), nullable=False, server_default=""), sa.Column("due_date", sa.Date(), nullable=True), created(), updated())
    op.create_table("project_decisions",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.id"), nullable=False, index=True), sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, index=True), sa.Column("title", sa.String(180), nullable=False), sa.Column("context", sa.Text(), nullable=False, server_default=""),
        sa.Column("decision", sa.Text(), nullable=False, server_default=""), sa.Column("alternatives", sa.JSON(), nullable=False, server_default=LIST_DEFAULT), sa.Column("consequences", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(24), nullable=False, server_default="proposed"), sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True), created(), updated())
    op.create_table("notification_preferences",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("kind", sa.String(40), nullable=False), sa.Column("in_app", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("email", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("push", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("digest", sa.String(20), nullable=False, server_default="none"), sa.Column("muted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("user_id", "kind", name="uq_notification_preference_user_kind"))
    op.create_table("saved_workspace_views",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.id"), nullable=False, index=True), sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("name", sa.String(120), nullable=False), sa.Column("view_type", sa.String(40), nullable=False), sa.Column("scope_type", sa.String(40), nullable=False, server_default="workspace"), sa.Column("scope_id", sa.String(80), nullable=True, index=True),
        sa.Column("config", sa.JSON(), nullable=False, server_default=JSON_DEFAULT), sa.Column("shared", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()), created(), updated())
    op.create_table("workspace_dashboards",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.id"), nullable=False, index=True), sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("name", sa.String(120), nullable=False), sa.Column("layout", sa.JSON(), nullable=False, server_default=LIST_DEFAULT), sa.Column("widgets", sa.JSON(), nullable=False, server_default=LIST_DEFAULT), sa.Column("shared", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("delivery", sa.JSON(), nullable=False, server_default=JSON_DEFAULT), created(), updated())
    op.create_table("workspace_files",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.id"), nullable=False, index=True), sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("parent_id", sa.String(36), sa.ForeignKey("workspace_files.id", ondelete="CASCADE"), nullable=True, index=True), sa.Column("name", sa.String(240), nullable=False), sa.Column("item_type", sa.String(20), nullable=False, server_default="file"),
        sa.Column("mime_type", sa.String(160), nullable=False, server_default="application/octet-stream"), sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"), sa.Column("storage_key", sa.String(500), nullable=False, server_default=""),
        sa.Column("external_url", sa.String(1000), nullable=False, server_default=""), sa.Column("provider", sa.String(40), nullable=False, server_default="workspace"), sa.Column("classification", sa.String(24), nullable=False, server_default="internal"),
        sa.Column("tags", sa.JSON(), nullable=False, server_default=LIST_DEFAULT), sa.Column("version", sa.Integer(), nullable=False, server_default="1"), sa.Column("visibility", sa.String(20), nullable=False, server_default="workspace"),
        sa.Column("description", sa.Text(), nullable=False, server_default=""), sa.Column("content_text", sa.Text(), nullable=False, server_default=""), sa.Column("preview_url", sa.String(1000), nullable=False, server_default=""), sa.Column("shared_with_ids", sa.JSON(), nullable=False, server_default=LIST_DEFAULT), created(), updated())
    op.create_table("approval_definitions",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.id"), nullable=False, index=True), sa.Column("name", sa.String(120), nullable=False),
        sa.Column("target_types", sa.JSON(), nullable=False, server_default=LIST_DEFAULT), sa.Column("stages", sa.JSON(), nullable=False, server_default=LIST_DEFAULT), sa.Column("reminder_hours", sa.Integer(), nullable=False, server_default="24"), sa.Column("escalation_hours", sa.Integer(), nullable=False, server_default="72"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False), created())
    op.create_table("approval_instances",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.id"), nullable=False, index=True), sa.Column("definition_id", sa.String(36), sa.ForeignKey("approval_definitions.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("target_type", sa.String(40), nullable=False), sa.Column("target_id", sa.String(80), nullable=False, index=True), sa.Column("requested_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("current_stage", sa.Integer(), nullable=False, server_default="0"), sa.Column("status", sa.String(24), nullable=False, server_default="pending"), sa.Column("decisions", sa.JSON(), nullable=False, server_default=LIST_DEFAULT),
        sa.Column("delegated_to_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True), sa.Column("due_at", sa.DateTime(timezone=True), nullable=True), created(), updated())


def downgrade() -> None:
    for table in ("approval_instances", "approval_definitions", "workspace_files", "workspace_dashboards", "saved_workspace_views", "notification_preferences", "project_decisions", "project_risks", "object_relationships", "project_group_access", "organization_unit_members", "organization_units"):
        op.drop_table(table)
    with op.batch_alter_table("work_item_comments") as b:
        b.drop_index("ix_work_item_comments_parent_id"); b.drop_constraint("fk_work_item_comments_parent_id", type_="foreignkey")
        b.drop_column("attachments"); b.drop_column("reactions"); b.drop_column("parent_id")
    with op.batch_alter_table("agile_releases") as b:
        b.drop_column("scenario"); b.drop_column("baseline")
    with op.batch_alter_table("work_items") as b: b.drop_column("custom_fields")
    with op.batch_alter_table("notifications") as b:
        b.drop_index("ix_notifications_snoozed_until"); b.drop_index("ix_notifications_group_key"); b.drop_column("snoozed_until"); b.drop_column("group_key")
    with op.batch_alter_table("calendar_events") as b:
        b.drop_column("recording_url"); b.drop_column("transcript"); b.drop_column("action_items"); b.drop_column("notes"); b.drop_column("agenda")
    with op.batch_alter_table("audit_events") as b:
        b.drop_constraint("uq_audit_events_event_hash", type_="unique"); b.drop_index("ix_audit_events_request_id"); b.drop_column("event_hash"); b.drop_column("previous_hash"); b.drop_column("request_id")
    with op.batch_alter_table("projects") as b: b.drop_column("settings")
    with op.batch_alter_table("users") as b:
        b.drop_index("ix_users_manager_id"); b.drop_constraint("fk_users_manager_id", type_="foreignkey")
        b.drop_column("profile"); b.drop_column("weekly_capacity_hours"); b.drop_column("skills"); b.drop_column("manager_id"); b.drop_column("timezone"); b.drop_column("job_title")
    with op.batch_alter_table("entities") as b: b.drop_column("governance_settings")
