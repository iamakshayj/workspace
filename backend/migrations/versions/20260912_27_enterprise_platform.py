"""Add enterprise policy, governance, integration, and operations control plane.

Revision ID: 20260912_27
Revises: 20260912_26
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260912_27"
down_revision: str | None = "20260912_26"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_DEFAULT = sa.text("'{}'")
LIST_DEFAULT = sa.text("'[]'")


def created() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def updated() -> sa.Column:
    return sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def upgrade() -> None:
    op.create_table(
        "policy_rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(140), nullable=False),
        sa.Column("description", sa.String(500), nullable=False, server_default=""),
        sa.Column("effect", sa.String(12), nullable=False, server_default="deny"),
        sa.Column("actions", sa.JSON(), nullable=False, server_default=LIST_DEFAULT),
        sa.Column("subject_type", sa.String(20), nullable=False, server_default="role"),
        sa.Column("subject_id", sa.String(80), nullable=True),
        sa.Column("resource_type", sa.String(40), nullable=False, server_default="*"),
        sa.Column("resource_id", sa.String(80), nullable=True),
        sa.Column("fields", sa.JSON(), nullable=False, server_default=LIST_DEFAULT),
        sa.Column("conditions", sa.JSON(), nullable=False, server_default=JSON_DEFAULT),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        created(), updated(),
    )
    op.create_index("ix_policy_rules_entity_id", "policy_rules", ["entity_id"])
    op.create_index("ix_policy_rules_subject_id", "policy_rules", ["subject_id"])
    op.create_index("ix_policy_rules_resource_id", "policy_rules", ["resource_id"])
    op.create_index("ix_policy_rules_entity_resource", "policy_rules", ["entity_id", "resource_type", "active", "priority"])

    op.create_table(
        "data_governance_policies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(140), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("applies_to", sa.JSON(), nullable=False, server_default=LIST_DEFAULT),
        sa.Column("classification", sa.String(24), nullable=False, server_default="internal"),
        sa.Column("enforcement", sa.String(16), nullable=False, server_default="audit"),
        sa.Column("configuration", sa.JSON(), nullable=False, server_default=JSON_DEFAULT),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        created(), updated(),
        sa.UniqueConstraint("entity_id", "name", name="uq_data_governance_policy_name"),
    )
    op.create_index("ix_data_governance_policies_entity_id", "data_governance_policies", ["entity_id"])
    op.create_index("ix_data_governance_policy_entity_kind", "data_governance_policies", ["entity_id", "kind", "active"])

    op.create_table(
        "legal_holds",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("scope_type", sa.String(40), nullable=False, server_default="entity"),
        sa.Column("scope_id", sa.String(80), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("released_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        created(),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_legal_holds_entity_id", "legal_holds", ["entity_id"])
    op.create_index("ix_legal_holds_entity_scope", "legal_holds", ["entity_id", "scope_type", "scope_id", "status"])

    op.create_table(
        "encryption_key_references",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False, server_default="platform"),
        sa.Column("key_reference", sa.String(1000), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        created(),
        sa.UniqueConstraint("entity_id", "name", name="uq_encryption_key_reference_name"),
    )
    op.create_index("ix_encryption_key_references_entity_id", "encryption_key_references", ["entity_id"])

    op.create_table(
        "integration_connections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(140), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("scopes", sa.JSON(), nullable=False, server_default=LIST_DEFAULT),
        sa.Column("credentials_encrypted", sa.Text(), nullable=True),
        sa.Column("configuration", sa.JSON(), nullable=False, server_default=JSON_DEFAULT),
        sa.Column("sync_cursor", sa.Text(), nullable=True),
        sa.Column("conflict_policy", sa.String(24), nullable=False, server_default="source_wins"),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(1000), nullable=False, server_default=""),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        created(), updated(),
        sa.UniqueConstraint("entity_id", "name", name="uq_integration_connection_name"),
    )
    op.create_index("ix_integration_connections_entity_id", "integration_connections", ["entity_id"])
    op.create_index("ix_integration_connections_provider", "integration_connections", ["provider"])
    op.create_index("ix_integration_connections_status", "integration_connections", ["status"])

    op.create_table(
        "webhook_subscriptions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(140), nullable=False),
        sa.Column("target_url", sa.String(1000), nullable=False),
        sa.Column("event_types", sa.JSON(), nullable=False, server_default=LIST_DEFAULT),
        sa.Column("signing_secret_encrypted", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_delivery_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status_code", sa.Integer(), nullable=True),
        sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        created(),
    )
    op.create_index("ix_webhook_subscriptions_entity_id", "webhook_subscriptions", ["entity_id"])
    op.create_index("ix_webhooks_entity_status", "webhook_subscriptions", ["entity_id", "status"])

    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subscription_id", sa.String(36), sa.ForeignKey("webhook_subscriptions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_id", sa.String(80), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=JSON_DEFAULT),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("response_excerpt", sa.String(500), nullable=False, server_default=""),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        created(),
        sa.UniqueConstraint("subscription_id", "event_id", name="uq_webhook_delivery_event"),
    )
    op.create_index("ix_webhook_deliveries_entity_id", "webhook_deliveries", ["entity_id"])
    op.create_index("ix_webhook_deliveries_subscription_id", "webhook_deliveries", ["subscription_id"])
    op.create_index("ix_webhook_deliveries_entity_status", "webhook_deliveries", ["entity_id", "status", "next_attempt_at"])

    op.create_table(
        "api_access_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("token_prefix", sa.String(20), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("scopes", sa.JSON(), nullable=False, server_default=LIST_DEFAULT),
        sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        created(),
    )
    op.create_index("ix_api_access_tokens_entity_id", "api_access_tokens", ["entity_id"])
    op.create_index("ix_api_access_tokens_token_prefix", "api_access_tokens", ["token_prefix"])
    op.create_index("ix_api_access_tokens_entity_active", "api_access_tokens", ["entity_id", "revoked_at", "expires_at"])

    op.create_table(
        "support_access_grants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requested_for", sa.String(320), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False, server_default=LIST_DEFAULT),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("requested_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("approved_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        created(),
    )
    op.create_index("ix_support_access_grants_entity_id", "support_access_grants", ["entity_id"])
    op.create_index("ix_support_access_entity_status", "support_access_grants", ["entity_id", "status", "expires_at"])

    op.create_table(
        "feature_entitlements",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("feature", sa.String(80), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("limit_value", sa.BigInteger(), nullable=True),
        sa.Column("configuration", sa.JSON(), nullable=False, server_default=JSON_DEFAULT),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        updated(),
        sa.UniqueConstraint("entity_id", "feature", name="uq_feature_entitlement"),
    )
    op.create_index("ix_feature_entitlements_entity_id", "feature_entitlements", ["entity_id"])

    op.create_table(
        "operational_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("service", sa.String(60), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False, server_default="error"),
        sa.Column("fingerprint", sa.String(128), nullable=False),
        sa.Column("message", sa.String(1000), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False, server_default=JSON_DEFAULT),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        created(),
    )
    op.create_index("ix_operational_events_entity_id", "operational_events", ["entity_id"])
    op.create_index("ix_operational_events_fingerprint", "operational_events", ["fingerprint"])
    op.create_index("ix_operational_events_entity_service_created", "operational_events", ["entity_id", "service", "created_at"])

    op.create_table(
        "service_objectives",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("service", sa.String(60), nullable=False),
        sa.Column("metric", sa.String(60), nullable=False),
        sa.Column("target", sa.Float(), nullable=False),
        sa.Column("window_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("warning_threshold", sa.Float(), nullable=False, server_default="0.8"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        updated(),
        sa.UniqueConstraint("entity_id", "service", "metric", name="uq_service_objective"),
    )
    op.create_index("ix_service_objectives_entity_id", "service_objectives", ["entity_id"])


def downgrade() -> None:
    for table in (
        "service_objectives", "operational_events", "feature_entitlements",
        "support_access_grants", "api_access_tokens", "webhook_deliveries", "webhook_subscriptions",
        "integration_connections", "encryption_key_references", "legal_holds",
        "data_governance_policies", "policy_rules",
    ):
        op.drop_table(table)
