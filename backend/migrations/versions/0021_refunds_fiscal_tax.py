"""refunds fiscal tax

Revision ID: 0021_refunds_fiscal_tax
Revises: 0020_offline_pos
"""

from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0021_refunds_fiscal_tax"
down_revision = "0020_offline_pos"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fiscal_tax_profiles",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("tax_regime_code", sa.String(64), nullable=False),
        sa.Column("vat_registered", sa.Boolean(), nullable=False),
        sa.Column("default_vat_rate", sa.Numeric(7, 4), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(country_code) = 2", name="ck_fiscal_tax_country"),
        sa.CheckConstraint(
            "(vat_registered = false) OR (default_vat_rate IS NOT NULL AND default_vat_rate > 0)",
            name="ck_fiscal_tax_vat_profile",
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_fiscal_tax_effective_range",
        ),
    )
    op.create_index(
        "ix_fiscal_tax_profiles_organization_id", "fiscal_tax_profiles", ["organization_id"]
    )
    op.create_index(
        "uq_fiscal_tax_current_org",
        "fiscal_tax_profiles",
        ["organization_id"],
        unique=True,
        postgresql_where=sa.text("effective_to IS NULL"),
        sqlite_where=sa.text("effective_to IS NULL"),
    )
    op.create_table(
        "fiscal_variant_profiles",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "product_variant_id",
            sa.Uuid(),
            sa.ForeignKey("product_variants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("fiscal_name", sa.String(300), nullable=False),
        sa.Column("nkt_code", sa.String(100), nullable=True),
        sa.Column("nkt_code_type", sa.String(20), nullable=True),
        sa.Column("fiscal_unit_code", sa.String(50), nullable=False),
        sa.Column("vat_rate_override", sa.Numeric(7, 4), nullable=True),
        sa.Column(
            "requires_marking", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("product_variant_id"),
        sa.CheckConstraint("length(trim(fiscal_name)) > 0", name="ck_fiscal_variant_name"),
        sa.CheckConstraint(
            "nkt_code IS NULL OR length(trim(nkt_code)) > 0", name="ck_fiscal_variant_nkt"
        ),
        sa.CheckConstraint(
            "vat_rate_override IS NULL OR vat_rate_override >= 0", name="ck_fiscal_variant_vat"
        ),
    )
    op.create_index(
        "ix_fiscal_variant_profiles_organization_id", "fiscal_variant_profiles", ["organization_id"]
    )
    op.create_index(
        "ix_fiscal_variant_profiles_product_variant_id",
        "fiscal_variant_profiles",
        ["product_variant_id"],
    )
    op.create_table(
        "fiscal_sale_snapshots",
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
            "order_id", sa.Uuid(), sa.ForeignKey("sales_orders.id"), nullable=False, unique=True
        ),
        sa.Column(
            "payment_id", sa.Uuid(), sa.ForeignKey("payments.id"), nullable=False, unique=True
        ),
        sa.Column(
            "tax_profile_id", sa.Uuid(), sa.ForeignKey("fiscal_tax_profiles.id"), nullable=True
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("currency_code", sa.String(3), nullable=False),
        sa.Column("total_minor", sa.BigInteger(), nullable=False),
        sa.Column("vat_total_minor", sa.BigInteger(), nullable=False),
        sa.Column("compliance_status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(currency_code) = 3", name="ck_fiscal_snapshot_currency"),
        sa.CheckConstraint("total_minor >= 0", name="ck_fiscal_snapshot_total"),
        sa.CheckConstraint("vat_total_minor >= 0", name="ck_fiscal_snapshot_vat"),
        sa.CheckConstraint(
            "compliance_status IN ('COMPLETE','INCOMPLETE')", name="ck_fiscal_snapshot_compliance"
        ),
    )
    op.create_index(
        "ix_fiscal_sale_snapshots_organization_id", "fiscal_sale_snapshots", ["organization_id"]
    )
    op.create_index(
        "ix_fiscal_sale_snapshots_location_id", "fiscal_sale_snapshots", ["location_id"]
    )
    op.create_index(
        "ix_fiscal_sale_snapshots_occurred_at", "fiscal_sale_snapshots", ["occurred_at"]
    )
    op.create_table(
        "fiscal_sale_snapshot_lines",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "snapshot_id",
            sa.Uuid(),
            sa.ForeignKey("fiscal_sale_snapshots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "order_item_id", sa.Uuid(), sa.ForeignKey("sales_order_items.id"), nullable=False
        ),
        sa.Column("product_variant_id", sa.Uuid(), nullable=False),
        sa.Column("fiscal_name", sa.String(300), nullable=False),
        sa.Column("nkt_code", sa.String(100), nullable=True),
        sa.Column("nkt_code_type", sa.String(20), nullable=True),
        sa.Column("unit_code", sa.String(50), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price_minor", sa.BigInteger(), nullable=False),
        sa.Column("total_minor", sa.BigInteger(), nullable=False),
        sa.Column("vat_rate", sa.Numeric(7, 4), nullable=True),
        sa.Column("vat_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("marking_codes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("snapshot_id", "order_item_id"),
        sa.CheckConstraint("quantity > 0", name="ck_fiscal_snapshot_line_quantity"),
        sa.CheckConstraint("unit_price_minor >= 0", name="ck_fiscal_snapshot_line_unit_price"),
        sa.CheckConstraint("total_minor >= 0", name="ck_fiscal_snapshot_line_total"),
        sa.CheckConstraint("vat_amount_minor >= 0", name="ck_fiscal_snapshot_line_vat"),
    )
    op.create_index(
        "ix_fiscal_sale_snapshot_lines_snapshot_id", "fiscal_sale_snapshot_lines", ["snapshot_id"]
    )
    op.create_table(
        "refunds",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("location_id", sa.Uuid(), sa.ForeignKey("locations.id"), nullable=False),
        sa.Column("order_id", sa.Uuid(), sa.ForeignKey("sales_orders.id"), nullable=False),
        sa.Column("payment_id", sa.Uuid(), sa.ForeignKey("payments.id"), nullable=False),
        sa.Column("client_refund_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(32), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("currency_code", sa.String(3), nullable=False),
        sa.Column("total_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column(
            "inventory_transaction_id",
            sa.Uuid(),
            sa.ForeignKey("inventory_transactions.id"),
            nullable=True,
            unique=True,
        ),
        sa.Column("cogs_reversal_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("cogs_quality_status", sa.String(16), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_by_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(100), nullable=True),
        sa.UniqueConstraint("organization_id", "client_refund_id"),
        sa.CheckConstraint("status IN ('PENDING','COMPLETED','FAILED')", name="ck_refund_status"),
        sa.CheckConstraint(
            "reason IN ('QUALITY_ISSUE','WRONG_ITEM','ORDER_ERROR','CUSTOMER_RETURN',"
            "'DUPLICATE_PAYMENT','GOODWILL','OTHER')",
            name="ck_refund_reason",
        ),
        sa.CheckConstraint("length(currency_code) = 3", name="ck_refund_currency"),
        sa.CheckConstraint("total_amount_minor > 0", name="ck_refund_total_positive"),
        sa.CheckConstraint("cogs_reversal_amount >= 0", name="ck_refund_cogs_nonnegative"),
        sa.CheckConstraint(
            "cogs_quality_status IS NULL OR cogs_quality_status IN "
            "('COMPLETE','INCOMPLETE','ESTIMATED')",
            name="ck_refund_cogs_quality",
        ),
    )
    for name, cols in (
        ("ix_refunds_organization_id", ["organization_id"]),
        ("ix_refunds_location_id", ["location_id"]),
        ("ix_refunds_order_id", ["order_id"]),
        ("ix_refunds_org_created", ["organization_id", "created_at"]),
        ("ix_refunds_payment", ["payment_id", "status"]),
        ("ix_refunds_payment_id", ["payment_id"]),
        ("ix_refunds_status", ["status"]),
    ):
        op.create_index(name, "refunds", cols)
    op.create_table(
        "refund_lines",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "refund_id", sa.Uuid(), sa.ForeignKey("refunds.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "order_item_id", sa.Uuid(), sa.ForeignKey("sales_order_items.id"), nullable=False
        ),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("restock_quantity", sa.Integer(), nullable=False),
        sa.Column("unit_refund_minor", sa.BigInteger(), nullable=False),
        sa.Column("total_refund_minor", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("refund_id", "order_item_id"),
        sa.CheckConstraint("quantity > 0", name="ck_refund_line_quantity"),
        sa.CheckConstraint(
            "restock_quantity >= 0 AND restock_quantity <= quantity", name="ck_refund_line_restock"
        ),
        sa.CheckConstraint("unit_refund_minor >= 0", name="ck_refund_line_unit_amount"),
        sa.CheckConstraint("total_refund_minor >= 0", name="ck_refund_line_total"),
    )
    op.create_index("ix_refund_lines_refund_id", "refund_lines", ["refund_id"])
    op.create_index("ix_refund_lines_order_item_id", "refund_lines", ["order_item_id"])
    op.create_table(
        "refund_payment_lines",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "refund_id", sa.Uuid(), sa.ForeignKey("refunds.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "original_payment_line_id", sa.Uuid(), sa.ForeignKey("payment_lines.id"), nullable=False
        ),
        sa.Column("method", sa.String(20), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("external_refund_confirmed", sa.Boolean(), nullable=False),
        sa.Column("reference", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("refund_id", "original_payment_line_id"),
        sa.CheckConstraint("method IN ('CASH','CARD','OTHER')", name="ck_refund_payment_method"),
        sa.CheckConstraint("amount_minor > 0", name="ck_refund_payment_amount"),
    )
    op.create_index("ix_refund_payment_lines_refund_id", "refund_payment_lines", ["refund_id"])
    op.create_index(
        "ix_refund_payment_lines_original_payment_line_id",
        "refund_payment_lines",
        ["original_payment_line_id"],
    )

    op.add_column("integration_jobs", sa.Column("external_number", sa.String(255), nullable=True))
    op.add_column("integration_jobs", sa.Column("external_url", sa.String(2000), nullable=True))
    op.add_column(
        "analytics_sales_daily",
        sa.Column("refund_amount", sa.Numeric(20, 6), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "analytics_sales_daily",
        sa.Column("refund_count", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "analytics_sales_daily",
        sa.Column("refunded_items", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "analytics_product_sales_daily",
        sa.Column("refund_amount", sa.Numeric(20, 6), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "analytics_product_sales_daily",
        sa.Column(
            "refunded_quantity", sa.BigInteger(), nullable=False, server_default=sa.text("0")
        ),
    )
    op.add_column(
        "analytics_product_sales_daily",
        sa.Column("refund_orders", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "analytics_location_metrics_daily",
        sa.Column("refund_amount", sa.Numeric(20, 6), nullable=False, server_default=sa.text("0")),
    )
    _backfill_fiscal_snapshots()


def _backfill_fiscal_snapshots() -> None:
    bind = op.get_bind()
    paid = bind.execute(
        sa.text(
            "SELECT p.id AS payment_id, p.organization_id, p.location_id, p.order_id, "
            "p.completed_at, p.currency_code, p.amount_minor "
            "FROM payments p JOIN sales_orders o ON o.id = p.order_id WHERE o.status = 'PAID'"
        )
    ).mappings()
    now = datetime.now(UTC)
    for payment in paid:
        snapshot_id = uuid4()
        bind.execute(
            sa.text(
                "INSERT INTO fiscal_sale_snapshots "
                "(id, organization_id, location_id, order_id, payment_id, tax_profile_id, "
                "occurred_at, currency_code, total_minor, vat_total_minor, "
                "compliance_status, created_at) "
                "VALUES (:id,:organization_id,:location_id,:order_id,:payment_id,NULL,:occurred_at,"
                ":currency_code,:total_minor,0,'INCOMPLETE',:created_at)"
            ),
            {
                **payment,
                "id": snapshot_id,
                "occurred_at": payment["completed_at"],
                "total_minor": payment["amount_minor"],
                "created_at": now,
            },
        )
        items = bind.execute(
            sa.text(
                "SELECT id, product_variant_id, product_name, variant_name, quantity, "
                "unit_price_minor, line_total_minor FROM sales_order_items "
                "WHERE order_id = :order_id"
            ),
            {"order_id": payment["order_id"]},
        ).mappings()
        for item in items:
            name = item["product_name"] + (
                f" - {item['variant_name']}" if item["variant_name"] else ""
            )
            bind.execute(
                sa.text(
                    "INSERT INTO fiscal_sale_snapshot_lines "
                    "(id,snapshot_id,order_item_id,product_variant_id,fiscal_name,nkt_code,nkt_code_type,"
                    "unit_code,quantity,unit_price_minor,total_minor,vat_rate,"
                    "vat_amount_minor,marking_codes,created_at) "
                    "VALUES (:id,:snapshot_id,:order_item_id,:product_variant_id,"
                    ":fiscal_name,NULL,NULL,"
                    "'pcs',:quantity,:unit_price_minor,:total_minor,NULL,0,:marking_codes,:created_at)"
                ),
                {
                    "id": uuid4(),
                    "snapshot_id": snapshot_id,
                    "order_item_id": item["id"],
                    "product_variant_id": item["product_variant_id"],
                    "fiscal_name": name,
                    "quantity": item["quantity"],
                    "unit_price_minor": item["unit_price_minor"],
                    "total_minor": item["line_total_minor"],
                    "marking_codes": "[]",
                    "created_at": now,
                },
            )


def downgrade() -> None:
    op.drop_column("analytics_location_metrics_daily", "refund_amount")
    for column in ("refund_orders", "refunded_quantity", "refund_amount"):
        op.drop_column("analytics_product_sales_daily", column)
    for column in ("refunded_items", "refund_count", "refund_amount"):
        op.drop_column("analytics_sales_daily", column)
    op.drop_column("integration_jobs", "external_url")
    op.drop_column("integration_jobs", "external_number")
    op.drop_table("refund_payment_lines")
    op.drop_table("refund_lines")
    op.drop_table("refunds")
    op.drop_table("fiscal_sale_snapshot_lines")
    op.drop_table("fiscal_sale_snapshots")
    op.drop_table("fiscal_variant_profiles")
    op.drop_table("fiscal_tax_profiles")
