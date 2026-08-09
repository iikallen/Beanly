"""Add POS registers, shifts, orders and immutable item snapshots.

Revision ID: 0010_sales_pos
Revises: 0009_modifiers
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_sales_pos"
down_revision: str | None = "0009_modifiers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def upgrade() -> None:
    op.execute("CREATE SEQUENCE sales_order_number_seq")
    op.create_table(
        "pos_registers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "location_id", "name"),
    )
    op.create_index("ix_pos_registers_organization_id", "pos_registers", ["organization_id"])
    op.create_index("ix_pos_registers_location_id", "pos_registers", ["location_id"])

    op.create_table(
        "register_shifts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("register_id", sa.Uuid(), nullable=False),
        sa.Column("warehouse_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("opened_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("closed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("status IN ('OPEN', 'CLOSED')", name="ck_register_shift_status"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"]),
        sa.ForeignKeyConstraint(["register_id"], ["pos_registers.id"]),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"]),
        sa.ForeignKeyConstraint(["opened_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["closed_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("organization_id", "location_id", "register_id", "status"):
        op.create_index(f"ix_register_shifts_{column}", "register_shifts", [column])
    op.create_index(
        "uq_register_shifts_open_register",
        "register_shifts",
        ["register_id"],
        unique=True,
        postgresql_where=sa.text("status = 'OPEN'"),
    )

    op.create_table(
        "sales_orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("shift_id", sa.Uuid(), nullable=False),
        sa.Column("warehouse_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.BigInteger(), nullable=False),
        sa.Column("client_order_id", sa.Uuid(), nullable=False),
        sa.Column("order_type", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("currency_code", sa.String(3), nullable=False),
        sa.Column("guest_count", sa.Integer(), nullable=True),
        sa.Column("table_label", sa.String(100), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("subtotal_minor", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("total_minor", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("cancelled_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "order_type IN ('DINE_IN', 'TAKEAWAY', 'DELIVERY')", name="ck_sales_order_type"
        ),
        sa.CheckConstraint(
            "status IN ('OPEN', 'PAID', 'CANCELLED')", name="ck_sales_order_status"
        ),
        sa.CheckConstraint("guest_count IS NULL OR guest_count > 0", name="ck_order_guest_count"),
        sa.CheckConstraint("subtotal_minor >= 0", name="ck_order_subtotal_nonnegative"),
        sa.CheckConstraint("total_minor >= 0", name="ck_order_total_nonnegative"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"]),
        sa.ForeignKeyConstraint(["shift_id"], ["register_shifts.id"]),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["cancelled_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "client_order_id"),
    )
    for column in ("organization_id", "location_id", "shift_id", "status", "created_at"):
        op.create_index(f"ix_sales_orders_{column}", "sales_orders", [column])
    op.create_index(
        "ix_sales_orders_organization_created",
        "sales_orders",
        ["organization_id", "created_at"],
    )

    op.create_table(
        "sales_order_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("client_item_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("product_variant_id", sa.Uuid(), nullable=False),
        sa.Column("product_name", sa.String(200), nullable=False),
        sa.Column("variant_name", sa.String(100), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("base_price_minor", sa.BigInteger(), nullable=False),
        sa.Column("modifier_price_minor", sa.BigInteger(), nullable=False),
        sa.Column("unit_price_minor", sa.BigInteger(), nullable=False),
        sa.Column("line_total_minor", sa.BigInteger(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("quantity > 0", name="ck_sales_order_item_quantity"),
        sa.CheckConstraint("base_price_minor >= 0", name="ck_order_item_base_price"),
        sa.CheckConstraint("modifier_price_minor >= 0", name="ck_order_item_modifier_price"),
        sa.CheckConstraint("unit_price_minor >= 0", name="ck_order_item_unit_price"),
        sa.CheckConstraint("line_total_minor >= 0", name="ck_order_item_line_total"),
        sa.ForeignKeyConstraint(["order_id"], ["sales_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["product_variant_id"], ["product_variants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_id", "client_item_id"),
    )
    op.create_index("ix_sales_order_items_order_id", "sales_order_items", ["order_id"])
    op.create_index(
        "ix_sales_order_items_product_variant_id",
        "sales_order_items",
        ["product_variant_id"],
    )

    op.create_table(
        "sales_order_item_modifiers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_item_id", sa.Uuid(), nullable=False),
        sa.Column("modifier_group_id", sa.Uuid(), nullable=False),
        sa.Column("modifier_group_name", sa.String(150), nullable=False),
        sa.Column("modifier_option_id", sa.Uuid(), nullable=False),
        sa.Column("modifier_option_name", sa.String(150), nullable=False),
        sa.Column("price_delta_minor", sa.BigInteger(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(
            ["order_item_id"], ["sales_order_items.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["modifier_group_id"], ["modifier_groups.id"]),
        sa.ForeignKeyConstraint(["modifier_option_id"], ["modifier_options.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_item_id", "modifier_option_id"),
    )
    op.create_index(
        "ix_sales_order_item_modifiers_order_item_id",
        "sales_order_item_modifiers",
        ["order_item_id"],
    )

    op.create_table(
        "sales_order_item_components",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_item_id", sa.Uuid(), nullable=False),
        sa.Column("inventory_item_id", sa.Uuid(), nullable=False),
        sa.Column("inventory_item_name", sa.String(200), nullable=False),
        sa.Column("base_unit", sa.String(16), nullable=False),
        sa.Column("quantity_per_unit", sa.Numeric(20, 6), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "quantity_per_unit > 0", name="ck_order_item_component_quantity"
        ),
        sa.ForeignKeyConstraint(
            ["order_item_id"], ["sales_order_items.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["inventory_item_id"], ["inventory_items.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_item_id", "inventory_item_id"),
    )
    op.create_index(
        "ix_sales_order_item_components_order_item_id",
        "sales_order_item_components",
        ["order_item_id"],
    )


def downgrade() -> None:
    op.drop_table("sales_order_item_components")
    op.drop_table("sales_order_item_modifiers")
    op.drop_table("sales_order_items")
    op.drop_table("sales_orders")
    op.drop_table("register_shifts")
    op.drop_table("pos_registers")
    op.execute("DROP SEQUENCE sales_order_number_seq")
