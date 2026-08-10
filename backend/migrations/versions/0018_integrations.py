"""Add durable provider integrations.

Revision ID: 0018_integrations
Revises: 0017_analytics_read_models
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018_integrations"
down_revision: str | None = "0017_analytics_read_models"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "integration_connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("provider_code", sa.String(80), nullable=False),
        sa.Column("display_name", sa.String(150), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("auth_type", sa.String(24), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("credentials_ciphertext", sa.Text(), nullable=True),
        sa.Column("credentials_key_version", sa.Integer(), nullable=True),
        sa.Column("external_account_id", sa.String(255), nullable=True),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_health_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(100), nullable=True),
        sa.Column("last_error_message", sa.String(500), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('PENDING','ACTIVE','DEGRADED','REVOKED')",
            name="ck_integration_connection_status",
        ),
        sa.CheckConstraint(
            "auth_type IN ('NONE','API_KEY','OAUTH2')",
            name="ck_integration_connection_auth",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_integration_connections_org_provider",
        "integration_connections",
        ["organization_id", "provider_code"],
    )
    op.create_index(
        "ix_integration_connections_organization_id",
        "integration_connections",
        ["organization_id"],
    )
    op.create_index(
        "ix_integration_connections_status", "integration_connections", ["status"]
    )

    op.create_table(
        "integration_location_bindings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("capability", sa.String(24), nullable=False),
        sa.Column("external_location_id", sa.String(255), nullable=True),
        sa.Column("settings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "capability IN ('PAYMENT','FISCAL','DELIVERY','NOTIFICATION')",
            name="ck_integration_binding_capability",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["integration_connections.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("connection_id", "location_id", "capability"),
    )
    op.create_index(
        "ix_integration_location_bindings_organization_id",
        "integration_location_bindings",
        ["organization_id"],
    )
    op.create_index(
        "ix_integration_location_bindings_connection_id",
        "integration_location_bindings",
        ["connection_id"],
    )
    op.create_index(
        "ix_integration_location_bindings_location_id",
        "integration_location_bindings",
        ["location_id"],
    )

    op.create_table(
        "integration_oauth_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider_code", sa.String(80), nullable=False),
        sa.Column("state_hash", sa.String(64), nullable=False),
        sa.Column("code_verifier_ciphertext", sa.Text(), nullable=False),
        sa.Column("redirect_uri", sa.String(500), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("state_hash"),
    )
    op.create_index(
        "ix_integration_oauth_sessions_organization_id",
        "integration_oauth_sessions",
        ["organization_id"],
    )
    op.create_index(
        "ix_integration_oauth_sessions_expires_at",
        "integration_oauth_sessions",
        ["expires_at"],
    )

    op.create_table(
        "integration_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=True),
        sa.Column("capability", sa.String(24), nullable=False),
        sa.Column("job_type", sa.String(100), nullable=False),
        sa.Column("source_event_id", sa.Uuid(), nullable=True),
        sa.Column("source_type", sa.String(80), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("locked_by", sa.String(120), nullable=True),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dead_lettered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(100), nullable=True),
        sa.Column("last_error_message", sa.String(1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "capability IN ('PAYMENT','FISCAL','DELIVERY','NOTIFICATION')",
            name="ck_integration_job_capability",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','PROCESSING','RETRYING','SUCCESS','DEAD')",
            name="ck_integration_job_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_integration_job_attempts"),
        sa.CheckConstraint(
            "(locked_by IS NULL) = (locked_until IS NULL)",
            name="ck_integration_job_lock_pair",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["integration_connections.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("connection_id", "idempotency_key"),
    )
    op.create_index(
        "ix_integration_jobs_claim",
        "integration_jobs",
        ["status", "available_at", "locked_until"],
    )
    op.create_index(
        "ix_integration_jobs_org_created",
        "integration_jobs",
        ["organization_id", "created_at"],
    )
    for column in ("organization_id", "connection_id", "job_type", "status", "available_at"):
        op.create_index(f"ix_integration_jobs_{column}", "integration_jobs", [column])

    op.create_table(
        "integration_job_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("provider_request_id", sa.String(255), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("error_message", sa.String(1000), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["integration_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "attempt_number"),
    )
    op.create_index(
        "ix_integration_job_attempts_job_id", "integration_job_attempts", ["job_id"]
    )

    op.create_table(
        "integration_inbox_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("provider_code", sa.String(80), nullable=False),
        sa.Column("external_event_id", sa.String(255), nullable=False),
        sa.Column("event_type", sa.String(150), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_by", sa.String(120), nullable=True),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dead_lettered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.CheckConstraint("attempts >= 0", name="ck_integration_inbox_attempts"),
        sa.CheckConstraint(
            "(locked_by IS NULL) = (locked_until IS NULL)",
            name="ck_integration_inbox_lock_pair",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["integration_connections.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("connection_id", "external_event_id"),
    )
    op.create_index(
        "ix_integration_inbox_claim",
        "integration_inbox_events",
        ["available_at", "locked_until"],
    )
    for column in ("organization_id", "connection_id", "available_at"):
        op.create_index(
            f"ix_integration_inbox_events_{column}", "integration_inbox_events", [column]
        )


def downgrade() -> None:
    op.drop_table("integration_inbox_events")
    op.drop_table("integration_job_attempts")
    op.drop_table("integration_jobs")
    op.drop_table("integration_oauth_sessions")
    op.drop_table("integration_location_bindings")
    op.drop_table("integration_connections")
