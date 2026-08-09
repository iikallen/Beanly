"""Add completed payments and order settlement fields.

Revision ID: 0011_payments
Revises: 0010_sales_pos
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_payments"
down_revision: str | None = "0010_sales_pos"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sales_orders", sa.Column("paid_by_user_id", sa.Uuid(), nullable=True))
    op.add_column(
        "sales_orders", sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_foreign_key(
        "fk_sales_orders_paid_by_user_id_users",
        "sales_orders",
        "users",
        ["paid_by_user_id"],
        ["id"],
    )

    op.create_table(
        "payments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("shift_id", sa.Uuid(), nullable=False),
        sa.Column("client_payment_id", sa.Uuid(), nullable=False),
        sa.Column("currency_code", sa.String(3), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.CheckConstraint("amount_minor >= 0", name="ck_payment_amount_nonnegative"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"]),
        sa.ForeignKeyConstraint(["order_id"], ["sales_orders.id"]),
        sa.ForeignKeyConstraint(["shift_id"], ["register_shifts.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_id", name="uq_payments_order_id"),
        sa.UniqueConstraint(
            "organization_id",
            "client_payment_id",
            name="uq_payments_organization_client_payment_id",
        ),
    )
    for column in ("organization_id", "location_id", "shift_id", "completed_at"):
        op.create_index(f"ix_payments_{column}", "payments", [column])

    op.create_table(
        "payment_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("payment_id", sa.Uuid(), nullable=False),
        sa.Column("method", sa.String(20), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("cash_received_minor", sa.BigInteger(), nullable=True),
        sa.Column("change_minor", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("reference", sa.String(200), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "method IN ('CASH', 'CARD', 'OTHER')", name="ck_payment_line_method"
        ),
        sa.CheckConstraint(
            "amount_minor >= 0", name="ck_payment_line_amount_nonnegative"
        ),
        sa.CheckConstraint(
            "change_minor >= 0", name="ck_payment_line_change_nonnegative"
        ),
        sa.CheckConstraint("sort_order >= 0", name="ck_payment_line_sort_nonnegative"),
        sa.CheckConstraint(
            "(method = 'CASH' AND cash_received_minor IS NOT NULL "
            "AND cash_received_minor >= amount_minor "
            "AND change_minor = cash_received_minor - amount_minor) "
            "OR (method IN ('CARD', 'OTHER') AND cash_received_minor IS NULL "
            "AND change_minor = 0)",
            name="ck_payment_line_cash_values",
        ),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_payment_lines_payment_id", "payment_lines", ["payment_id"])
    op.create_index("ix_payment_lines_method", "payment_lines", ["method"])


def downgrade() -> None:
    op.drop_table("payment_lines")
    op.drop_table("payments")
    op.drop_constraint(
        "fk_sales_orders_paid_by_user_id_users", "sales_orders", type_="foreignkey"
    )
    op.drop_column("sales_orders", "paid_at")
    op.drop_column("sales_orders", "paid_by_user_id")
