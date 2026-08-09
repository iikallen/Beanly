"""Add suppliers, purchase orders and goods receipts.

Revision ID: 0006_purchasing
Revises: 0005_inventory_ledger
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_purchasing"
down_revision: str | None = "0005_inventory_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE purchase_order_number_seq")
    op.execute("CREATE SEQUENCE goods_receipt_number_seq")
    op.create_table(
        "suppliers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("contact_name", sa.String(150), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("tax_id", sa.String(100), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_suppliers_organization_id", "suppliers", ["organization_id"])
    op.create_index("ix_suppliers_organization_name", "suppliers", ["organization_id", "name"])

    op.create_table(
        "purchase_orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("warehouse_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("currency_code", sa.String(3), nullable=False),
        sa.Column("ordered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'ORDERED', 'PARTIALLY_RECEIVED', 'RECEIVED', 'CANCELLED')",
            name="ck_purchase_order_status",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"]),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"]),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "number"),
    )
    for name in (
        "organization_id",
        "supplier_id",
        "location_id",
        "warehouse_id",
        "status",
        "created_at",
    ):
        op.create_index(f"ix_purchase_orders_{name}", "purchase_orders", [name])
    op.create_index(
        "ix_purchase_orders_organization_status_created",
        "purchase_orders",
        ["organization_id", "status", "created_at"],
    )

    op.create_table(
        "purchase_order_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("purchase_order_id", sa.Uuid(), nullable=False),
        sa.Column("inventory_item_id", sa.Uuid(), nullable=False),
        sa.Column("ordered_quantity", sa.Numeric(20, 6), nullable=False),
        sa.Column("base_quantity", sa.Numeric(20, 6), nullable=False),
        sa.Column("purchase_unit", sa.String(50), nullable=False),
        sa.Column("unit_multiplier", sa.Numeric(20, 6), nullable=False),
        sa.Column("unit_price", sa.Numeric(20, 6), nullable=False),
        sa.Column("line_total_minor", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("ordered_quantity > 0", name="ck_purchase_order_line_quantity"),
        sa.CheckConstraint("base_quantity > 0", name="ck_purchase_order_line_base_quantity"),
        sa.CheckConstraint("unit_multiplier > 0", name="ck_purchase_order_line_multiplier"),
        sa.CheckConstraint("unit_price >= 0", name="ck_purchase_order_line_unit_price"),
        sa.CheckConstraint("line_total_minor >= 0", name="ck_purchase_order_line_total"),
        sa.ForeignKeyConstraint(["purchase_order_id"], ["purchase_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["inventory_item_id"], ["inventory_items.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("purchase_order_id", "inventory_item_id"),
    )
    op.create_index(
        "ix_purchase_order_lines_purchase_order_id",
        "purchase_order_lines",
        ["purchase_order_id"],
    )
    op.create_index(
        "ix_purchase_order_lines_inventory_item_id",
        "purchase_order_lines",
        ["inventory_item_id"],
    )

    op.create_table(
        "goods_receipts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("warehouse_id", sa.Uuid(), nullable=False),
        sa.Column("purchase_order_id", sa.Uuid(), nullable=True),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("document_number", sa.String(100), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("posted_by", sa.Uuid(), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reversed_by", sa.Uuid(), nullable=True),
        sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("inventory_transaction_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'POSTED', 'REVERSED')",
            name="ck_goods_receipt_status",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"]),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"]),
        sa.ForeignKeyConstraint(["purchase_order_id"], ["purchase_orders.id"]),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["posted_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["reversed_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["inventory_transaction_id"], ["inventory_transactions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "number"),
        sa.UniqueConstraint("inventory_transaction_id"),
    )
    for name in (
        "organization_id",
        "location_id",
        "warehouse_id",
        "purchase_order_id",
        "supplier_id",
        "status",
        "received_at",
    ):
        op.create_index(f"ix_goods_receipts_{name}", "goods_receipts", [name])
    op.create_index(
        "ix_goods_receipts_organization_status_received",
        "goods_receipts",
        ["organization_id", "status", "received_at"],
    )

    op.create_table(
        "goods_receipt_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("goods_receipt_id", sa.Uuid(), nullable=False),
        sa.Column("purchase_order_line_id", sa.Uuid(), nullable=True),
        sa.Column("inventory_item_id", sa.Uuid(), nullable=False),
        sa.Column("received_quantity", sa.Numeric(20, 6), nullable=False),
        sa.Column("base_quantity", sa.Numeric(20, 6), nullable=False),
        sa.Column("purchase_unit", sa.String(50), nullable=False),
        sa.Column("unit_multiplier", sa.Numeric(20, 6), nullable=False),
        sa.Column("unit_price", sa.Numeric(20, 6), nullable=False),
        sa.Column("line_total_minor", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("received_quantity > 0", name="ck_goods_receipt_line_quantity"),
        sa.CheckConstraint("base_quantity > 0", name="ck_goods_receipt_line_base_quantity"),
        sa.CheckConstraint("unit_multiplier > 0", name="ck_goods_receipt_line_multiplier"),
        sa.CheckConstraint("unit_price >= 0", name="ck_goods_receipt_line_unit_price"),
        sa.CheckConstraint("line_total_minor >= 0", name="ck_goods_receipt_line_total"),
        sa.ForeignKeyConstraint(["goods_receipt_id"], ["goods_receipts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["purchase_order_line_id"], ["purchase_order_lines.id"]),
        sa.ForeignKeyConstraint(["inventory_item_id"], ["inventory_items.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("goods_receipt_id", "inventory_item_id"),
    )
    op.create_index(
        "ix_goods_receipt_lines_goods_receipt_id",
        "goods_receipt_lines",
        ["goods_receipt_id"],
    )
    op.create_index(
        "ix_goods_receipt_lines_purchase_order_line_id",
        "goods_receipt_lines",
        ["purchase_order_line_id"],
    )
    op.create_index(
        "ix_goods_receipt_lines_inventory_item_id",
        "goods_receipt_lines",
        ["inventory_item_id"],
    )


def downgrade() -> None:
    op.execute(
        "UPDATE inventory_transactions SET reference_type = NULL, reference_id = NULL "
        "WHERE reference_type = 'GOODS_RECEIPT'"
    )
    op.drop_table("goods_receipt_lines")
    op.drop_table("goods_receipts")
    op.drop_table("purchase_order_lines")
    op.drop_table("purchase_orders")
    op.drop_table("suppliers")
    op.execute("DROP SEQUENCE goods_receipt_number_seq")
    op.execute("DROP SEQUENCE purchase_order_number_seq")
