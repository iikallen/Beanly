"""Create inventory ledger tables.

Revision ID: 0005_inventory_ledger
Revises: 0004_inventory_core
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_inventory_ledger"
down_revision: str | None = "0004_inventory_core"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "inventory_transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("warehouse_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("reference_type", sa.String(50), nullable=True),
        sa.Column("reference_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.String(255), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reversal_of_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "(reference_type IS NULL) = (reference_id IS NULL)",
            name="ck_inventory_transaction_reference_pair",
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'POSTED', 'REVERSED')",
            name="ck_inventory_transaction_status",
        ),
        sa.CheckConstraint(
            "type IN ('PURCHASE', 'SALE', 'WRITE_OFF', 'ADJUSTMENT', 'TRANSFER_IN', "
            "'TRANSFER_OUT', 'RETURN_IN', 'RETURN_OUT', 'PRODUCTION', 'OPENING_BALANCE')",
            name="ck_inventory_transaction_type",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"]),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["reversal_of_id"], ["inventory_transactions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reversal_of_id"),
    )
    op.create_index(
        "ix_inventory_transactions_organization_id",
        "inventory_transactions",
        ["organization_id"],
    )
    op.create_index(
        "ix_inventory_transactions_location_id",
        "inventory_transactions",
        ["location_id"],
    )
    op.create_index(
        "ix_inventory_transactions_warehouse_id",
        "inventory_transactions",
        ["warehouse_id"],
    )
    op.create_index(
        "ix_inventory_transactions_created_at",
        "inventory_transactions",
        ["created_at"],
    )
    op.create_index(
        "ix_inventory_transactions_reference_type",
        "inventory_transactions",
        ["reference_type"],
    )
    op.create_index(
        "ix_inventory_transactions_reference_id",
        "inventory_transactions",
        ["reference_id"],
    )
    op.create_index(
        "uq_inventory_transactions_idempotency",
        "inventory_transactions",
        ["organization_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
    )

    op.create_table(
        "inventory_transaction_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("inventory_item_id", sa.Uuid(), nullable=False),
        sa.Column("quantity_delta", sa.Numeric(20, 6), nullable=False),
        sa.Column("unit_cost_amount", sa.Numeric(20, 6), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("quantity_delta <> 0", name="ck_inventory_line_nonzero"),
        sa.ForeignKeyConstraint(
            ["transaction_id"], ["inventory_transactions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["inventory_item_id"], ["inventory_items.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_inventory_transaction_lines_transaction_id",
        "inventory_transaction_lines",
        ["transaction_id"],
    )
    op.create_index(
        "ix_inventory_transaction_lines_inventory_item_id",
        "inventory_transaction_lines",
        ["inventory_item_id"],
    )


def downgrade() -> None:
    # Core balances are projections of this ledger. Keeping them while removing
    # their source would make a later re-upgrade irreconcilable.
    op.execute(sa.text("DELETE FROM stock_balances"))
    op.drop_index(
        "ix_inventory_transaction_lines_inventory_item_id",
        table_name="inventory_transaction_lines",
    )
    op.drop_index(
        "ix_inventory_transaction_lines_transaction_id",
        table_name="inventory_transaction_lines",
    )
    op.drop_table("inventory_transaction_lines")
    op.drop_index("uq_inventory_transactions_idempotency", table_name="inventory_transactions")
    op.drop_index("ix_inventory_transactions_reference_id", table_name="inventory_transactions")
    op.drop_index("ix_inventory_transactions_reference_type", table_name="inventory_transactions")
    op.drop_index("ix_inventory_transactions_created_at", table_name="inventory_transactions")
    op.drop_index("ix_inventory_transactions_warehouse_id", table_name="inventory_transactions")
    op.drop_index("ix_inventory_transactions_location_id", table_name="inventory_transactions")
    op.drop_index("ix_inventory_transactions_organization_id", table_name="inventory_transactions")
    op.drop_table("inventory_transactions")
