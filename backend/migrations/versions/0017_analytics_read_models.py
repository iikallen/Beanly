"""Add event-driven analytics read models.

Revision ID: 0017_analytics_read_models
Revises: 0016_dashboard_query_indexes
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_analytics_read_models"
down_revision: str | None = "0016_dashboard_query_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ZERO_NUMERIC = sa.text("0")


def _uuid() -> sa.Uuid:
    return sa.Uuid()


def _amount(name: str) -> sa.Column:
    return sa.Column(name, sa.Numeric(20, 6), nullable=False, server_default=ZERO_NUMERIC)


def _count(name: str) -> sa.Column:
    return sa.Column(name, sa.BigInteger(), nullable=False, server_default=sa.text("0"))


def upgrade() -> None:
    op.create_table(
        "analytics_projection_receipts",
        sa.Column("projection_name", sa.String(80), nullable=False),
        sa.Column("source_type", sa.String(80), nullable=False),
        sa.Column("source_id", _uuid(), nullable=False),
        sa.Column("organization_id", _uuid(), nullable=False),
        sa.Column("source_event_id", _uuid(), nullable=True),
        sa.Column("source_occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("projected_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("projection_name", "source_type", "source_id"),
    )
    op.create_index(
        "ix_analytics_receipts_org_occurred",
        "analytics_projection_receipts",
        ["organization_id", "source_occurred_at"],
    )

    op.create_table(
        "analytics_sales_daily",
        sa.Column("organization_id", _uuid(), nullable=False),
        sa.Column("location_id", _uuid(), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("currency_code", sa.String(3), nullable=False),
        _amount("revenue_amount"),
        _count("paid_orders"),
        _count("items_sold"),
        _amount("cogs_amount"),
        _count("incomplete_cogs_orders"),
        _count("dine_in_orders"),
        _count("takeaway_orders"),
        _count("delivery_orders"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(currency_code) = 3", name="ck_an_sales_currency"),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("organization_id", "location_id", "local_date"),
    )
    op.create_index(
        "ix_an_sales_org_date",
        "analytics_sales_daily",
        ["organization_id", "local_date"],
    )

    op.create_table(
        "analytics_product_sales_daily",
        sa.Column("organization_id", _uuid(), nullable=False),
        sa.Column("location_id", _uuid(), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("product_id", _uuid(), nullable=False),
        sa.Column("product_variant_id", _uuid(), nullable=False),
        sa.Column("product_name", sa.String(200), nullable=False),
        sa.Column("variant_name", sa.String(100), nullable=False),
        _count("quantity_sold"),
        _count("orders_count"),
        _amount("revenue_amount"),
        _amount("cogs_amount"),
        _count("incomplete_cogs_orders"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint(
            "organization_id", "location_id", "local_date", "product_variant_id"
        ),
    )
    op.create_index(
        "ix_an_product_org_location_date",
        "analytics_product_sales_daily",
        ["organization_id", "location_id", "local_date"],
    )
    op.create_index(
        "ix_an_product_product", "analytics_product_sales_daily", ["product_id"]
    )
    op.create_index(
        "ix_an_product_variant",
        "analytics_product_sales_daily",
        ["product_variant_id"],
    )

    op.create_table(
        "analytics_hourly_sales",
        sa.Column("organization_id", _uuid(), nullable=False),
        sa.Column("location_id", _uuid(), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("local_hour", sa.SmallInteger(), nullable=False),
        _amount("revenue_amount"),
        _count("paid_orders"),
        _count("items_sold"),
        _amount("cogs_amount"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "local_hour BETWEEN 0 AND 23", name="ck_an_hour_local_hour"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint(
            "organization_id", "location_id", "local_date", "local_hour"
        ),
    )
    op.create_index(
        "ix_an_hour_org_date",
        "analytics_hourly_sales",
        ["organization_id", "local_date"],
    )

    op.create_table(
        "analytics_location_metrics_daily",
        sa.Column("organization_id", _uuid(), nullable=False),
        sa.Column("location_id", _uuid(), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        _amount("revenue_amount"),
        _count("paid_orders"),
        _count("items_sold"),
        _amount("cogs_amount"),
        _amount("operating_expenses"),
        _amount("inventory_losses"),
        _amount("inventory_gains"),
        _count("incomplete_cogs_orders"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("organization_id", "location_id", "local_date"),
    )
    op.create_index(
        "ix_an_location_org_date",
        "analytics_location_metrics_daily",
        ["organization_id", "local_date"],
    )

    op.create_table(
        "analytics_inventory_consumption_daily",
        sa.Column("organization_id", _uuid(), nullable=False),
        sa.Column("location_id", _uuid(), nullable=False),
        sa.Column("warehouse_id", _uuid(), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("inventory_item_id", _uuid(), nullable=False),
        sa.Column("inventory_item_name", sa.String(200), nullable=False),
        sa.Column("base_unit", sa.String(16), nullable=False),
        _amount("sale_quantity"),
        _amount("sale_cost_amount"),
        _amount("writeoff_quantity"),
        _amount("writeoff_cost_amount"),
        _amount("adjustment_quantity"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint(
            "organization_id",
            "location_id",
            "warehouse_id",
            "local_date",
            "inventory_item_id",
        ),
    )
    op.create_index(
        "ix_an_consumption_org_location_date",
        "analytics_inventory_consumption_daily",
        ["organization_id", "location_id", "local_date"],
    )
    op.create_index(
        "ix_an_consumption_item",
        "analytics_inventory_consumption_daily",
        ["inventory_item_id"],
    )


def downgrade() -> None:
    op.drop_table("analytics_inventory_consumption_daily")
    op.drop_table("analytics_location_metrics_daily")
    op.drop_table("analytics_hourly_sales")
    op.drop_table("analytics_product_sales_daily")
    op.drop_table("analytics_sales_daily")
    op.drop_table("analytics_projection_receipts")
