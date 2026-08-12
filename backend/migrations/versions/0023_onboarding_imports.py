"""Onboarding and canonical imports.

Revision ID: 0023_onboarding_imports
Revises: 0022_kz_live_integrations
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0023_onboarding_imports"
down_revision = "0022_kz_live_integrations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    json_document = postgresql.JSONB(astext_type=sa.Text())
    op.create_table(
        "onboarding_states",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("current_step", sa.String(80), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('NOT_STARTED','IN_PROGRESS','READY_FOR_POS','COMPLETED')",
            name="ck_onboarding_state_status",
        ),
    )
    op.create_table(
        "onboarding_import_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "location_id",
            sa.Uuid(),
            sa.ForeignKey("locations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("client_import_id", sa.Uuid(), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_name", sa.String(200), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=True),
        sa.Column("file_name", sa.String(255), nullable=True),
        sa.Column("file_hash", sa.String(64), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("entity_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("warning_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("mapping", json_document, nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "organization_id", "client_import_id", name="uq_onboarding_import_client"
        ),
        sa.CheckConstraint(
            "source_type IN ('BEANLY_TEMPLATE','BEANLY_SPREADSHEET',"
            "'GENERIC_SPREADSHEET','POSTER_EXPORT','AI_EXTRACTION')",
            name="ck_onboarding_import_source",
        ),
        sa.CheckConstraint(
            "status IN ('UPLOADED','PARSING','NEEDS_REVIEW','READY','APPLYING',"
            "'APPLIED','FAILED','CANCELLED')",
            name="ck_onboarding_import_status",
        ),
        sa.CheckConstraint("entity_count >= 0", name="ck_onboarding_import_entity_count"),
        sa.CheckConstraint("error_count >= 0", name="ck_onboarding_import_error_count"),
        sa.CheckConstraint("warning_count >= 0", name="ck_onboarding_import_warning_count"),
    )
    op.create_index(
        "ix_onboarding_import_org_created",
        "onboarding_import_runs",
        ["organization_id", "created_at"],
    )
    op.create_index(
        "ix_onboarding_import_org_status", "onboarding_import_runs", ["organization_id", "status"]
    )
    op.create_table(
        "onboarding_import_entities",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "import_run_id",
            sa.Uuid(),
            sa.ForeignKey("onboarding_import_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("source_key", sa.String(255), nullable=False),
        sa.Column("payload", json_document, nullable=False),
        sa.Column("resolution", sa.String(24), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column("error_codes", json_document, nullable=False),
        sa.Column("warning_codes", json_document, nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.UniqueConstraint("import_run_id", "source_key", name="uq_onboarding_entity_source"),
        sa.CheckConstraint(
            "entity_type IN ('CATEGORY','INVENTORY_ITEM','PRODUCT','VARIANT','RECIPE',"
            "'MODIFIER_GROUP','MODIFIER_OPTION','LOCATION_PRICE','OPENING_BALANCE')",
            name="ck_onboarding_entity_type",
        ),
        sa.CheckConstraint(
            "resolution IN ('CREATE','MATCH_EXISTING','SKIP')",
            name="ck_onboarding_entity_resolution",
        ),
        sa.CheckConstraint("sort_order >= 0", name="ck_onboarding_entity_sort_order"),
    )
    op.create_index(
        "ix_onboarding_entity_run_order",
        "onboarding_import_entities",
        ["import_run_id", "sort_order"],
    )


def downgrade() -> None:
    op.drop_table("onboarding_import_entities")
    op.drop_table("onboarding_import_runs")
    op.drop_table("onboarding_states")
