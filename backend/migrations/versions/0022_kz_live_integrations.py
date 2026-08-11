"""Kazakhstan live integration foundation.

Revision ID: 0022_kz_live_integrations
Revises: 0021_refunds_fiscal_tax
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0022_kz_live_integrations"
down_revision = "0021_refunds_fiscal_tax"
branch_labels = None
depends_on = None


def upgrade() -> None:
    json_document = postgresql.JSONB(astext_type=sa.Text())
    op.create_table(
        "fiscal_nkt_cache",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("external_product_id", sa.String(255), nullable=False),
        sa.Column("ntin", sa.String(13), nullable=False),
        sa.Column("gtins", json_document, nullable=False),
        sa.Column("name_ru", sa.String(500), nullable=False),
        sa.Column("name_kk", sa.String(500), nullable=False),
        sa.Column("category_code", sa.String(100), nullable=False),
        sa.Column("unit_code", sa.String(50), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.UniqueConstraint("ntin"),
        sa.CheckConstraint(
            "length(ntin) = 13 AND "
            + " AND ".join(
                f"substr(ntin, {position}, 1) BETWEEN '0' AND '9'"
                for position in range(1, 14)
            ),
            name="ck_fiscal_nkt_ntin",
        ),
    )
    op.create_index("ix_fiscal_nkt_cache_name_ru", "fiscal_nkt_cache", ["name_ru"])
    op.create_index("ix_fiscal_nkt_cache_name_kk", "fiscal_nkt_cache", ["name_kk"])
    op.create_index("ix_fiscal_nkt_cache_expires_at", "fiscal_nkt_cache", ["expires_at"])
    if op.get_bind().dialect.name == "postgresql":
        op.create_index(
            "ix_fiscal_nkt_cache_gtins",
            "fiscal_nkt_cache",
            ["gtins"],
            postgresql_using="gin",
        )

    op.add_column(
        "fiscal_variant_profiles",
        sa.Column("nkt_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "fiscal_variant_profiles",
        sa.Column("nkt_external_product_id", sa.String(255), nullable=True),
    )
    op.add_column(
        "locations",
        sa.Column(
            "fiscal_enforcement_mode",
            sa.String(24),
            nullable=False,
            server_default=sa.text("'DISABLED'"),
        ),
    )
    op.create_check_constraint(
        "ck_location_fiscal_enforcement_mode",
        "locations",
        "fiscal_enforcement_mode IN ('DISABLED','TEST','LIVE_REQUIRED')",
    )

    op.create_table(
        "fiscal_routes",
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
            sa.ForeignKey("locations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "register_id",
            sa.Uuid(),
            sa.ForeignKey("pos_registers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "provider_connection_id",
            sa.Uuid(),
            sa.ForeignKey("integration_connections.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_mode", sa.String(32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "source_mode IN ('EXTERNAL_KKM','PAYMENT_TERMINAL_KKM')",
            name="ck_fiscal_route_source_mode",
        ),
    )
    op.create_index("ix_fiscal_routes_organization_id", "fiscal_routes", ["organization_id"])
    op.create_index("ix_fiscal_routes_location_id", "fiscal_routes", ["location_id"])
    op.create_index(
        "uq_fiscal_routes_active_register",
        "fiscal_routes",
        ["register_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
        sqlite_where=sa.text("is_active = 1"),
    )

    op.create_table(
        "fiscal_receipts",
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
            sa.ForeignKey("locations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "connection_id",
            sa.Uuid(),
            sa.ForeignKey("integration_connections.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_type", sa.String(16), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("provider_code", sa.String(80), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("external_receipt_id", sa.String(255), nullable=True),
        sa.Column("receipt_number", sa.String(255), nullable=True),
        sa.Column("receipt_url", sa.String(2000), nullable=True),
        sa.Column("provider_request_id", sa.String(255), nullable=True),
        sa.Column("provider_correlation_id", sa.String(255), nullable=False),
        sa.Column("fiscalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(100), nullable=True),
        sa.Column("last_error_message", sa.String(1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "organization_id", "source_type", "source_id", name="uq_fiscal_receipt_source"
        ),
        sa.UniqueConstraint(
            "connection_id",
            "provider_correlation_id",
            name="uq_fiscal_receipt_correlation",
        ),
        sa.CheckConstraint("source_type IN ('SALE','REFUND')", name="ck_fiscal_receipt_source"),
        sa.CheckConstraint(
            "status IN ('PENDING','PROCESSING','SUCCEEDED','RETRYING','UNKNOWN','DEAD')",
            name="ck_fiscal_receipt_status",
        ),
    )
    op.create_index(
        "ix_fiscal_receipts_org_created", "fiscal_receipts", ["organization_id", "created_at"]
    )
    op.create_index(
        "ix_fiscal_receipts_location_status",
        "fiscal_receipts",
        ["location_id", "status"],
    )

    op.create_table(
        "integration_terminal_bindings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "connection_id",
            sa.Uuid(),
            sa.ForeignKey("integration_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "location_id",
            sa.Uuid(),
            sa.ForeignKey("locations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "register_id",
            sa.Uuid(),
            sa.ForeignKey("pos_registers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider_code", sa.String(80), nullable=False),
        sa.Column("external_terminal_id", sa.String(255), nullable=True),
        sa.Column("transport_config", json_document, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("register_id", "provider_code"),
    )
    op.create_index(
        "ix_terminal_bindings_organization_id",
        "integration_terminal_bindings",
        ["organization_id"],
    )
    op.create_index(
        "ix_terminal_bindings_location_id", "integration_terminal_bindings", ["location_id"]
    )

    op.create_table(
        "external_payment_attempts",
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
            sa.ForeignKey("locations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("order_id", sa.Uuid(), sa.ForeignKey("sales_orders.id"), nullable=False),
        sa.Column(
            "register_id", sa.Uuid(), sa.ForeignKey("pos_registers.id"), nullable=False
        ),
        sa.Column("pos_device_id", sa.Uuid(), sa.ForeignKey("pos_devices.id"), nullable=True),
        sa.Column(
            "connection_id",
            sa.Uuid(),
            sa.ForeignKey("integration_connections.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("client_attempt_id", sa.Uuid(), nullable=False),
        sa.Column("provider_code", sa.String(80), nullable=False),
        sa.Column("method", sa.String(20), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency_code", sa.String(3), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("provider_operation_id", sa.String(255), nullable=True),
        sa.Column("provider_reference", sa.String(255), nullable=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("payment_id", sa.Uuid(), sa.ForeignKey("payments.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(100), nullable=True),
        sa.UniqueConstraint("organization_id", "client_attempt_id"),
        sa.UniqueConstraint("payment_id"),
        sa.CheckConstraint(
            "status IN ('CREATED','TERMINAL_PENDING','APPROVED','DECLINED','CANCELLED','UNKNOWN')",
            name="ck_external_payment_attempt_status",
        ),
        sa.CheckConstraint("method IN ('CARD','QR')", name="ck_external_payment_attempt_method"),
        sa.CheckConstraint("amount_minor > 0", name="ck_external_payment_attempt_amount"),
        sa.CheckConstraint("length(currency_code) = 3", name="ck_external_payment_currency"),
        sa.CheckConstraint(
            "(status = 'APPROVED' AND approved_at IS NOT NULL AND payment_id IS NOT NULL "
            "AND provider_operation_id IS NOT NULL AND provider_reference IS NOT NULL "
            "AND failed_at IS NULL AND failure_code IS NULL) OR "
            "(status <> 'APPROVED' AND approved_at IS NULL AND payment_id IS NULL)",
            name="ck_external_payment_attempt_approval",
        ),
    )
    op.create_index(
        "ix_external_payment_attempts_org_created",
        "external_payment_attempts",
        ["organization_id", "created_at"],
    )
    op.create_index(
        "ix_external_payment_attempts_order", "external_payment_attempts", ["order_id"]
    )
    op.create_index(
        "ix_external_payment_attempts_status", "external_payment_attempts", ["status"]
    )
    op.create_index(
        "uq_external_payment_attempts_unresolved_order",
        "external_payment_attempts",
        ["order_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('CREATED','TERMINAL_PENDING','UNKNOWN')"),
        sqlite_where=sa.text("status IN ('CREATED','TERMINAL_PENDING','UNKNOWN')"),
    )

    op.add_column(
        "payment_lines",
        sa.Column("external_payment_attempt_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_payment_lines_external_attempt",
        "payment_lines",
        "external_payment_attempts",
        ["external_payment_attempt_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_payment_lines_external_attempt", "payment_lines", ["external_payment_attempt_id"]
    )
    op.add_column("payment_lines", sa.Column("provider_code", sa.String(80), nullable=True))
    op.add_column(
        "payment_lines", sa.Column("provider_transaction_id", sa.String(255), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("payment_lines", "provider_transaction_id")
    op.drop_column("payment_lines", "provider_code")
    op.drop_constraint("uq_payment_lines_external_attempt", "payment_lines", type_="unique")
    op.drop_constraint("fk_payment_lines_external_attempt", "payment_lines", type_="foreignkey")
    op.drop_column("payment_lines", "external_payment_attempt_id")
    op.drop_table("external_payment_attempts")
    op.drop_table("integration_terminal_bindings")
    op.drop_table("fiscal_receipts")
    op.drop_table("fiscal_routes")
    op.drop_constraint("ck_location_fiscal_enforcement_mode", "locations", type_="check")
    op.drop_column("locations", "fiscal_enforcement_mode")
    op.drop_column("fiscal_variant_profiles", "nkt_external_product_id")
    op.drop_column("fiscal_variant_profiles", "nkt_verified_at")
    op.drop_table("fiscal_nkt_cache")
