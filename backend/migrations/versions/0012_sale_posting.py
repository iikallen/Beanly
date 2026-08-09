"""Link paid sales to inventory posting and actual COGS.

Revision ID: 0012_sale_posting
Revises: 0011_payments
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_sale_posting"
down_revision: str | None = "0011_payments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sales_orders",
        sa.Column("inventory_transaction_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "sales_orders", sa.Column("cogs_amount", sa.Numeric(20, 6), nullable=True)
    )
    op.add_column(
        "sales_orders", sa.Column("cogs_status", sa.String(16), nullable=True)
    )
    op.create_foreign_key(
        "fk_sales_orders_inventory_transaction_id_inventory_transactions",
        "sales_orders",
        "inventory_transactions",
        ["inventory_transaction_id"],
        ["id"],
    )
    op.create_unique_constraint(
        "uq_sales_orders_inventory_transaction_id",
        "sales_orders",
        ["inventory_transaction_id"],
    )
    op.create_check_constraint(
        "ck_sales_order_cogs_nonnegative",
        "sales_orders",
        "cogs_amount IS NULL OR cogs_amount >= 0",
    )
    op.create_check_constraint(
        "ck_sales_order_cogs_status",
        "sales_orders",
        "cogs_status IS NULL OR cogs_status IN ('COMPLETE', 'INCOMPLETE')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_sales_order_cogs_status", "sales_orders", type_="check"
    )
    op.drop_constraint(
        "ck_sales_order_cogs_nonnegative", "sales_orders", type_="check"
    )
    op.drop_constraint(
        "uq_sales_orders_inventory_transaction_id",
        "sales_orders",
        type_="unique",
    )
    op.drop_constraint(
        "fk_sales_orders_inventory_transaction_id_inventory_transactions",
        "sales_orders",
        type_="foreignkey",
    )
    op.drop_column("sales_orders", "cogs_status")
    op.drop_column("sales_orders", "cogs_amount")
    op.drop_column("sales_orders", "inventory_transaction_id")
