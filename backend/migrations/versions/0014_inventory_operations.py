"""Add full inventory operation documents.

Revision ID: 0014_inventory_operations
Revises: 0013_transactional_outbox
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_inventory_operations"
down_revision: str | None = "0013_transactional_outbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for name in (
        "inventory_writeoff_number_seq",
        "inventory_count_number_seq",
        "inventory_transfer_number_seq",
        "supplier_return_number_seq",
    ):
        op.execute(f"CREATE SEQUENCE {name}")

    op.create_table(
        "inventory_writeoff_reasons",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_inventory_writeoff_reasons_organization_id",
        "inventory_writeoff_reasons",
        ["organization_id"],
    )

    op.create_table(
        "inventory_writeoffs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("warehouse_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.String(32), nullable=False),
        sa.Column("reason_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("posted_by", sa.Uuid(), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reversed_by", sa.Uuid(), nullable=True),
        sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("inventory_transaction_id", sa.Uuid(), nullable=True),
        sa.Column("total_cost_amount", sa.Numeric(20, 6), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'POSTED', 'REVERSED')", name="ck_writeoff_status"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["inventory_transaction_id"], ["inventory_transactions.id"]),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["posted_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["reason_id"], ["inventory_writeoff_reasons.id"]),
        sa.ForeignKeyConstraint(["reversed_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("inventory_transaction_id"),
        sa.UniqueConstraint("organization_id", "number"),
    )
    for column in ("organization_id", "location_id", "warehouse_id", "reason_id", "occurred_at"):
        op.create_index(f"ix_inventory_writeoffs_{column}", "inventory_writeoffs", [column])
    op.create_index(
        "ix_inventory_writeoffs_organization_status_occurred",
        "inventory_writeoffs",
        ["organization_id", "status", "occurred_at"],
    )

    op.create_table(
        "inventory_writeoff_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("writeoff_id", sa.Uuid(), nullable=False),
        sa.Column("inventory_item_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Numeric(20, 6), nullable=False),
        sa.Column("unit_code", sa.String(8), nullable=False),
        sa.Column("base_quantity", sa.Numeric(20, 6), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_writeoff_line_quantity_positive"),
        sa.CheckConstraint(
            "base_quantity > 0", name="ck_writeoff_line_base_quantity_positive"
        ),
        sa.ForeignKeyConstraint(["inventory_item_id"], ["inventory_items.id"]),
        sa.ForeignKeyConstraint(
            ["writeoff_id"], ["inventory_writeoffs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("writeoff_id", "inventory_item_id"),
    )
    op.create_index(
        "ix_inventory_writeoff_lines_writeoff_id", "inventory_writeoff_lines", ["writeoff_id"]
    )
    op.create_index(
        "ix_inventory_writeoff_lines_inventory_item_id",
        "inventory_writeoff_lines",
        ["inventory_item_id"],
    )

    op.create_table(
        "inventory_counts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("warehouse_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.String(32), nullable=False),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_by", sa.Uuid(), nullable=False),
        sa.Column("posted_by", sa.Uuid(), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by", sa.Uuid(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("inventory_transaction_id", sa.Uuid(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("type IN ('FULL', 'PARTIAL')", name="ck_inventory_count_type"),
        sa.CheckConstraint(
            "status IN ('COUNTING', 'POSTED', 'CANCELLED')",
            name="ck_inventory_count_status",
        ),
        sa.ForeignKeyConstraint(["cancelled_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["inventory_transaction_id"], ["inventory_transactions.id"]),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["posted_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["started_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("inventory_transaction_id"),
        sa.UniqueConstraint("organization_id", "number"),
    )
    for column in ("organization_id", "location_id", "warehouse_id", "snapshot_at"):
        op.create_index(f"ix_inventory_counts_{column}", "inventory_counts", [column])
    op.create_index(
        "ix_inventory_counts_organization_status_snapshot",
        "inventory_counts",
        ["organization_id", "status", "snapshot_at"],
    )

    op.create_table(
        "inventory_count_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("inventory_count_id", sa.Uuid(), nullable=False),
        sa.Column("inventory_item_id", sa.Uuid(), nullable=False),
        sa.Column("expected_quantity", sa.Numeric(20, 6), nullable=False),
        sa.Column("counted_quantity", sa.Numeric(20, 6), nullable=True),
        sa.Column("current_quantity_before_post", sa.Numeric(20, 6), nullable=True),
        sa.Column("difference_quantity", sa.Numeric(20, 6), nullable=True),
        sa.Column("difference_cost_amount", sa.Numeric(20, 6), nullable=True),
        sa.Column("unit_cost_amount", sa.Numeric(20, 6), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "counted_quantity IS NULL OR counted_quantity >= 0",
            name="ck_inventory_count_line_counted_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["inventory_count_id"], ["inventory_counts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["inventory_item_id"], ["inventory_items.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("inventory_count_id", "inventory_item_id"),
    )
    op.create_index(
        "ix_inventory_count_lines_inventory_count_id",
        "inventory_count_lines",
        ["inventory_count_id"],
    )
    op.create_index(
        "ix_inventory_count_lines_inventory_item_id",
        "inventory_count_lines",
        ["inventory_item_id"],
    )

    op.create_table(
        "inventory_transfers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.String(32), nullable=False),
        sa.Column("source_location_id", sa.Uuid(), nullable=False),
        sa.Column("source_warehouse_id", sa.Uuid(), nullable=False),
        sa.Column("destination_location_id", sa.Uuid(), nullable=False),
        sa.Column("destination_warehouse_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("posted_by", sa.Uuid(), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reversed_by", sa.Uuid(), nullable=True),
        sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("out_transaction_id", sa.Uuid(), nullable=True),
        sa.Column("in_transaction_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'POSTED', 'REVERSED')", name="ck_inventory_transfer_status"
        ),
        sa.CheckConstraint(
            "source_warehouse_id <> destination_warehouse_id",
            name="ck_inventory_transfer_distinct_warehouses",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["destination_location_id"], ["locations.id"]),
        sa.ForeignKeyConstraint(["destination_warehouse_id"], ["warehouses.id"]),
        sa.ForeignKeyConstraint(["in_transaction_id"], ["inventory_transactions.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["out_transaction_id"], ["inventory_transactions.id"]),
        sa.ForeignKeyConstraint(["posted_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["reversed_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["source_location_id"], ["locations.id"]),
        sa.ForeignKeyConstraint(["source_warehouse_id"], ["warehouses.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("in_transaction_id"),
        sa.UniqueConstraint("out_transaction_id"),
        sa.UniqueConstraint("organization_id", "number"),
    )
    for column in (
        "organization_id",
        "source_location_id",
        "source_warehouse_id",
        "destination_location_id",
        "destination_warehouse_id",
        "status",
        "occurred_at",
    ):
        op.create_index(f"ix_inventory_transfers_{column}", "inventory_transfers", [column])
    op.create_index(
        "ix_inventory_transfers_organization_status_occurred",
        "inventory_transfers",
        ["organization_id", "status", "occurred_at"],
    )

    op.create_table(
        "inventory_transfer_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("transfer_id", sa.Uuid(), nullable=False),
        sa.Column("inventory_item_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Numeric(20, 6), nullable=False),
        sa.Column("unit_code", sa.String(8), nullable=False),
        sa.Column("base_quantity", sa.Numeric(20, 6), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "quantity > 0", name="ck_inventory_transfer_line_quantity_positive"
        ),
        sa.CheckConstraint(
            "base_quantity > 0", name="ck_inventory_transfer_line_base_quantity_positive"
        ),
        sa.ForeignKeyConstraint(["inventory_item_id"], ["inventory_items.id"]),
        sa.ForeignKeyConstraint(
            ["transfer_id"], ["inventory_transfers.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transfer_id", "inventory_item_id"),
    )
    op.create_index(
        "ix_inventory_transfer_lines_transfer_id",
        "inventory_transfer_lines",
        ["transfer_id"],
    )
    op.create_index(
        "ix_inventory_transfer_lines_inventory_item_id",
        "inventory_transfer_lines",
        ["inventory_item_id"],
    )

    op.create_table(
        "supplier_returns",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("warehouse_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("goods_receipt_id", sa.Uuid(), nullable=True),
        sa.Column("number", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("document_number", sa.String(100), nullable=True),
        sa.Column("returned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("posted_by", sa.Uuid(), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reversed_by", sa.Uuid(), nullable=True),
        sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("inventory_transaction_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'POSTED', 'REVERSED')", name="ck_supplier_return_status"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["goods_receipt_id"], ["goods_receipts.id"]),
        sa.ForeignKeyConstraint(["inventory_transaction_id"], ["inventory_transactions.id"]),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["posted_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["reversed_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"]),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("inventory_transaction_id"),
        sa.UniqueConstraint("organization_id", "number"),
    )
    for column in (
        "organization_id",
        "location_id",
        "warehouse_id",
        "supplier_id",
        "goods_receipt_id",
        "status",
        "returned_at",
    ):
        op.create_index(f"ix_supplier_returns_{column}", "supplier_returns", [column])
    op.create_index(
        "ix_supplier_returns_organization_status_returned",
        "supplier_returns",
        ["organization_id", "status", "returned_at"],
    )

    op.create_table(
        "supplier_return_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("supplier_return_id", sa.Uuid(), nullable=False),
        sa.Column("goods_receipt_line_id", sa.Uuid(), nullable=True),
        sa.Column("inventory_item_id", sa.Uuid(), nullable=False),
        sa.Column("return_quantity", sa.Numeric(20, 6), nullable=False),
        sa.Column("base_quantity", sa.Numeric(20, 6), nullable=False),
        sa.Column("purchase_unit", sa.String(50), nullable=False),
        sa.Column("unit_multiplier", sa.Numeric(20, 6), nullable=False),
        sa.Column("unit_price", sa.Numeric(20, 6), nullable=False),
        sa.Column("line_total_minor", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "return_quantity > 0", name="ck_supplier_return_line_quantity"
        ),
        sa.CheckConstraint(
            "base_quantity > 0", name="ck_supplier_return_line_base_quantity"
        ),
        sa.CheckConstraint(
            "unit_multiplier > 0", name="ck_supplier_return_line_multiplier"
        ),
        sa.CheckConstraint("unit_price >= 0", name="ck_supplier_return_line_unit_price"),
        sa.CheckConstraint(
            "line_total_minor >= 0", name="ck_supplier_return_line_total"
        ),
        sa.ForeignKeyConstraint(["goods_receipt_line_id"], ["goods_receipt_lines.id"]),
        sa.ForeignKeyConstraint(["inventory_item_id"], ["inventory_items.id"]),
        sa.ForeignKeyConstraint(
            ["supplier_return_id"], ["supplier_returns.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("supplier_return_id", "inventory_item_id"),
    )
    for column in ("supplier_return_id", "goods_receipt_line_id", "inventory_item_id"):
        op.create_index(
            f"ix_supplier_return_lines_{column}", "supplier_return_lines", [column]
        )


def downgrade() -> None:
    for table in (
        "supplier_return_lines",
        "supplier_returns",
        "inventory_transfer_lines",
        "inventory_transfers",
        "inventory_count_lines",
        "inventory_counts",
        "inventory_writeoff_lines",
        "inventory_writeoffs",
        "inventory_writeoff_reasons",
    ):
        op.drop_table(table)
    for name in (
        "supplier_return_number_seq",
        "inventory_transfer_number_seq",
        "inventory_count_number_seq",
        "inventory_writeoff_number_seq",
    ):
        op.execute(f"DROP SEQUENCE {name}")
