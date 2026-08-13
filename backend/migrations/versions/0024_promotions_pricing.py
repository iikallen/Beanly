"""Promotions and deterministic pricing snapshots.

Revision ID: 0024_promotions_pricing
Revises: 0023_onboarding_imports
"""

import sqlalchemy as sa
from alembic import op

revision = "0024_promotions_pricing"
down_revision = "0023_onboarding_imports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "promotions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("pos_name", sa.String(100), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("application_mode", sa.String(16), nullable=False),
        sa.Column("discount_kind", sa.String(24), nullable=False),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("percent_rate", sa.Numeric(7, 4), nullable=True),
        sa.Column("amount_minor", sa.BigInteger(), nullable=True),
        sa.Column("fixed_price_minor", sa.BigInteger(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stacking_policy", sa.String(16), nullable=False),
        sa.Column(
            "include_modifier_price", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("minimum_subtotal_minor", sa.BigInteger(), nullable=True),
        sa.Column("maximum_discount_minor", sa.BigInteger(), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("all_locations", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "requires_override_permission", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('DRAFT','ACTIVE','ARCHIVED')", name="ck_promotions_status"),
        sa.CheckConstraint(
            "application_mode IN ('AUTOMATIC','MANUAL','CODE')", name="ck_promotions_application"
        ),
        sa.CheckConstraint(
            "discount_kind IN ('PERCENT','FIXED_AMOUNT','FIXED_PRICE','BOGO')",
            name="ck_promotions_kind",
        ),
        sa.CheckConstraint("scope IN ('ORDER','ITEM','COMBO')", name="ck_promotions_scope"),
        sa.CheckConstraint(
            "stacking_policy IN ('EXCLUSIVE','STACKABLE')", name="ck_promotions_stacking"
        ),
        sa.CheckConstraint(
            "percent_rate IS NULL OR (percent_rate > 0 AND percent_rate <= 100)",
            name="ck_promotions_percent",
        ),
        sa.CheckConstraint(
            "amount_minor IS NULL OR amount_minor >= 0", name="ck_promotions_amount"
        ),
        sa.CheckConstraint(
            "fixed_price_minor IS NULL OR fixed_price_minor >= 0", name="ck_promotions_fixed_price"
        ),
        sa.CheckConstraint(
            "minimum_subtotal_minor IS NULL OR minimum_subtotal_minor >= 0",
            name="ck_promotions_minimum",
        ),
        sa.CheckConstraint(
            "maximum_discount_minor IS NULL OR maximum_discount_minor >= 0",
            name="ck_promotions_maximum",
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from",
            name="ck_promotions_dates",
        ),
    )
    op.create_index("ix_promotions_org_status", "promotions", ["organization_id", "status"])
    op.create_table(
        "promotion_locations",
        sa.Column(
            "promotion_id",
            sa.Uuid(),
            sa.ForeignKey("promotions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "location_id",
            sa.Uuid(),
            sa.ForeignKey("locations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_table(
        "promotion_schedules",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "promotion_id",
            sa.Uuid(),
            sa.ForeignKey("promotions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("weekday", sa.SmallInteger(), nullable=False),
        sa.Column("start_local_time", sa.Time(), nullable=False),
        sa.Column("end_local_time", sa.Time(), nullable=False),
        sa.CheckConstraint("weekday >= 0 AND weekday <= 6", name="ck_promotion_schedule_weekday"),
        sa.CheckConstraint("start_local_time < end_local_time", name="ck_promotion_schedule_time"),
        sa.UniqueConstraint(
            "promotion_id",
            "weekday",
            "start_local_time",
            "end_local_time",
            name="uq_promotion_schedule_range",
        ),
    )
    op.create_index("ix_promotion_schedules_promotion", "promotion_schedules", ["promotion_id"])
    op.create_table(
        "promotion_targets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "promotion_id",
            sa.Uuid(),
            sa.ForeignKey("promotions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(24), nullable=False),
        sa.Column("target_type", sa.String(16), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint(
            "role IN ('ELIGIBLE','BUY','GET','COMBO_COMPONENT')", name="ck_promotion_target_role"
        ),
        sa.CheckConstraint(
            "target_type IN ('CATEGORY','PRODUCT','VARIANT','ALL')", name="ck_promotion_target_type"
        ),
        sa.CheckConstraint(
            "(target_type = 'ALL' AND target_id IS NULL) OR "
            "(target_type <> 'ALL' AND target_id IS NOT NULL)",
            name="ck_promotion_target_id",
        ),
        sa.CheckConstraint("quantity > 0", name="ck_promotion_target_quantity"),
        sa.CheckConstraint("sort_order >= 0", name="ck_promotion_target_sort"),
    )
    op.create_index(
        "ix_promotion_targets_promotion", "promotion_targets", ["promotion_id", "sort_order"]
    )
    op.create_table(
        "promotion_codes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "promotion_id",
            sa.Uuid(),
            sa.ForeignKey("promotions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code_normalized", sa.String(80), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("max_redemptions", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "organization_id", "code_normalized", name="uq_promotion_codes_org_code"
        ),
        sa.CheckConstraint(
            "max_redemptions IS NULL OR max_redemptions > 0", name="ck_promotion_codes_max"
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from",
            name="ck_promotion_codes_dates",
        ),
    )
    op.create_index("ix_promotion_codes_promotion", "promotion_codes", ["promotion_id"])

    op.add_column(
        "sales_orders",
        sa.Column("discount_total_minor", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "sales_orders",
        sa.Column("pricing_revision", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column("sales_orders", sa.Column("priced_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        "ck_sales_order_discount_nonnegative", "sales_orders", "discount_total_minor >= 0"
    )
    op.create_check_constraint(
        "ck_sales_order_discount_bounded", "sales_orders", "discount_total_minor <= subtotal_minor"
    )
    op.create_check_constraint(
        "ck_sales_order_pricing_revision", "sales_orders", "pricing_revision > 0"
    )
    op.add_column(
        "sales_order_items",
        sa.Column("discount_amount_minor", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "sales_order_items", sa.Column("net_line_total_minor", sa.BigInteger(), nullable=True)
    )
    op.execute("UPDATE sales_order_items SET net_line_total_minor = line_total_minor")
    op.alter_column("sales_order_items", "net_line_total_minor", nullable=False)
    op.create_check_constraint(
        "ck_order_item_discount_nonnegative", "sales_order_items", "discount_amount_minor >= 0"
    )
    op.create_check_constraint(
        "ck_order_item_discount_bounded",
        "sales_order_items",
        "discount_amount_minor <= line_total_minor",
    )
    op.create_check_constraint(
        "ck_order_item_net_nonnegative", "sales_order_items", "net_line_total_minor >= 0"
    )
    op.create_check_constraint(
        "ck_order_item_net_reconciles",
        "sales_order_items",
        "net_line_total_minor = line_total_minor - discount_amount_minor",
    )

    op.create_table(
        "sales_order_discounts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "order_id",
            sa.Uuid(),
            sa.ForeignKey("sales_orders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("client_discount_id", sa.Uuid(), nullable=True),
        sa.Column(
            "promotion_id",
            sa.Uuid(),
            sa.ForeignKey("promotions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("promotion_name", sa.String(200), nullable=False),
        sa.Column("discount_kind", sa.String(24), nullable=False),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("percent_rate", sa.Numeric(7, 4), nullable=True),
        sa.Column("configured_amount_minor", sa.BigInteger(), nullable=True),
        sa.Column("promo_code_snapshot", sa.String(80), nullable=True),
        sa.Column("reason", sa.String(1000), nullable=True),
        sa.Column("applied_by_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("discount_total_minor", sa.BigInteger(), nullable=False),
        sa.Column("promotion_config_hash", sa.String(64), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.UniqueConstraint("order_id", "client_discount_id", name="uq_order_discount_client"),
        sa.CheckConstraint(
            "source IN ('AUTOMATIC','MANUAL','PROMO_CODE','CUSTOM')",
            name="ck_order_discount_source",
        ),
        sa.CheckConstraint(
            "discount_kind IN ('PERCENT','FIXED_AMOUNT','FIXED_PRICE','BOGO')",
            name="ck_order_discount_kind",
        ),
        sa.CheckConstraint("scope IN ('ORDER','ITEM','COMBO')", name="ck_order_discount_scope"),
        sa.CheckConstraint("discount_total_minor >= 0", name="ck_order_discount_total"),
        sa.CheckConstraint("sort_order >= 0", name="ck_order_discount_sort"),
    )
    op.create_index(
        "ix_sales_order_discounts_order", "sales_order_discounts", ["order_id", "sort_order"]
    )
    op.create_index("ix_sales_order_discounts_promotion", "sales_order_discounts", ["promotion_id"])
    op.create_table(
        "sales_order_discount_allocations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "order_discount_id",
            sa.Uuid(),
            sa.ForeignKey("sales_order_discounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "order_item_id",
            sa.Uuid(),
            sa.ForeignKey("sales_order_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("eligible_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("discount_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.UniqueConstraint(
            "order_discount_id", "order_item_id", name="uq_order_discount_allocation_item"
        ),
        sa.CheckConstraint(
            "eligible_amount_minor >= 0", name="ck_order_discount_allocation_eligible"
        ),
        sa.CheckConstraint(
            "discount_amount_minor >= 0 AND discount_amount_minor <= eligible_amount_minor",
            name="ck_order_discount_allocation_amount",
        ),
    )

    op.add_column("refund_lines", sa.Column("gross_refund_minor", sa.BigInteger(), nullable=True))
    op.add_column(
        "refund_lines", sa.Column("discount_refund_minor", sa.BigInteger(), nullable=True)
    )
    op.add_column("refund_lines", sa.Column("net_refund_minor", sa.BigInteger(), nullable=True))
    op.execute(
        "UPDATE refund_lines SET gross_refund_minor=total_refund_minor, "
        "discount_refund_minor=0, net_refund_minor=total_refund_minor"
    )
    for column in ("gross_refund_minor", "discount_refund_minor", "net_refund_minor"):
        op.alter_column("refund_lines", column, nullable=False)
    op.create_check_constraint(
        "ck_refund_line_discount_values",
        "refund_lines",
        "gross_refund_minor >= 0 AND discount_refund_minor >= 0 AND "
        "net_refund_minor >= 0 AND "
        "net_refund_minor = gross_refund_minor - discount_refund_minor AND "
        "total_refund_minor = net_refund_minor",
    )
    op.create_table(
        "refund_discount_allocations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "refund_line_id",
            sa.Uuid(),
            sa.ForeignKey("refund_lines.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "order_discount_id",
            sa.Uuid(),
            sa.ForeignKey("sales_order_discounts.id"),
            nullable=False,
        ),
        sa.Column("discount_amount_minor", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint(
            "refund_line_id", "order_discount_id", name="uq_refund_discount_allocation"
        ),
        sa.CheckConstraint(
            "discount_amount_minor >= 0", name="ck_refund_discount_allocation_amount"
        ),
    )

    op.add_column(
        "fiscal_sale_snapshots",
        sa.Column("discount_total_minor", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "fiscal_sale_snapshot_lines", sa.Column("gross_total_minor", sa.BigInteger(), nullable=True)
    )
    op.add_column(
        "fiscal_sale_snapshot_lines",
        sa.Column("discount_minor", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.execute("UPDATE fiscal_sale_snapshot_lines SET gross_total_minor=total_minor")
    op.alter_column("fiscal_sale_snapshot_lines", "gross_total_minor", nullable=False)
    op.create_check_constraint(
        "ck_fiscal_snapshot_discount", "fiscal_sale_snapshots", "discount_total_minor >= 0"
    )
    op.create_check_constraint(
        "ck_fiscal_snapshot_line_discount",
        "fiscal_sale_snapshot_lines",
        "gross_total_minor >= 0 AND discount_minor >= 0 AND "
        "total_minor = gross_total_minor - discount_minor",
    )
    op.add_column(
        "external_payment_attempts",
        sa.Column("order_pricing_revision", sa.Integer(), nullable=True),
    )

    for table in ("analytics_sales_daily", "analytics_product_sales_daily"):
        op.add_column(
            table,
            sa.Column(
                "gross_revenue_amount", sa.Numeric(20, 6), nullable=False, server_default="0"
            ),
        )
        op.add_column(
            table,
            sa.Column("discount_amount", sa.Numeric(20, 6), nullable=False, server_default="0"),
        )
        op.execute(f"UPDATE {table} SET gross_revenue_amount = revenue_amount")
    op.create_table(
        "analytics_promotions_daily",
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "location_id",
            sa.Uuid(),
            sa.ForeignKey("locations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("local_date", sa.Date(), primary_key=True),
        sa.Column("promotion_id", sa.Uuid(), primary_key=True),
        sa.Column("promotion_name", sa.String(200), nullable=False),
        sa.Column("orders_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("discount_amount", sa.Numeric(20, 6), nullable=False, server_default="0"),
        sa.Column("gross_revenue_amount", sa.Numeric(20, 6), nullable=False, server_default="0"),
        sa.Column("net_revenue_amount", sa.Numeric(20, 6), nullable=False, server_default="0"),
        sa.Column(
            "refunded_discount_amount", sa.Numeric(20, 6), nullable=False, server_default="0"
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("orders_count >= 0", name="ck_analytics_promotion_orders"),
    )
    op.create_index(
        "ix_analytics_promotions_org_date",
        "analytics_promotions_daily",
        ["organization_id", "local_date"],
    )


def downgrade() -> None:
    op.drop_table("analytics_promotions_daily")
    for table in ("analytics_product_sales_daily", "analytics_sales_daily"):
        op.drop_column(table, "discount_amount")
        op.drop_column(table, "gross_revenue_amount")
    op.drop_column("external_payment_attempts", "order_pricing_revision")
    op.drop_constraint(
        "ck_fiscal_snapshot_line_discount", "fiscal_sale_snapshot_lines", type_="check"
    )
    op.drop_column("fiscal_sale_snapshot_lines", "discount_minor")
    op.drop_column("fiscal_sale_snapshot_lines", "gross_total_minor")
    op.drop_constraint("ck_fiscal_snapshot_discount", "fiscal_sale_snapshots", type_="check")
    op.drop_column("fiscal_sale_snapshots", "discount_total_minor")
    op.drop_table("refund_discount_allocations")
    op.drop_constraint("ck_refund_line_discount_values", "refund_lines", type_="check")
    for column in ("net_refund_minor", "discount_refund_minor", "gross_refund_minor"):
        op.drop_column("refund_lines", column)
    op.drop_table("sales_order_discount_allocations")
    op.drop_table("sales_order_discounts")
    for name in (
        "ck_order_item_net_reconciles",
        "ck_order_item_net_nonnegative",
        "ck_order_item_discount_bounded",
        "ck_order_item_discount_nonnegative",
    ):
        op.drop_constraint(name, "sales_order_items", type_="check")
    op.drop_column("sales_order_items", "net_line_total_minor")
    op.drop_column("sales_order_items", "discount_amount_minor")
    for name in (
        "ck_sales_order_pricing_revision",
        "ck_sales_order_discount_bounded",
        "ck_sales_order_discount_nonnegative",
    ):
        op.drop_constraint(name, "sales_orders", type_="check")
    op.drop_column("sales_orders", "priced_at")
    op.drop_column("sales_orders", "pricing_revision")
    op.drop_column("sales_orders", "discount_total_minor")
    op.drop_table("promotion_codes")
    op.drop_table("promotion_targets")
    op.drop_table("promotion_schedules")
    op.drop_table("promotion_locations")
    op.drop_table("promotions")
