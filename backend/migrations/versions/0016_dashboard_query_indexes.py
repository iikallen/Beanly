"""Add indexes for live dashboard aggregate queries.

Revision ID: 0016_dashboard_query_indexes
Revises: 0015_finance
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_dashboard_query_indexes"
down_revision: str | None = "0015_finance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_sales_orders_dashboard_paid",
        "sales_orders",
        ["organization_id", "location_id", "paid_at"],
        postgresql_where=sa.text("status = 'PAID'"),
        sqlite_where=sa.text("status = 'PAID'"),
    )
    op.create_index(
        "ix_payments_dashboard_completed",
        "payments",
        ["organization_id", "location_id", "completed_at"],
    )
    op.create_index(
        "ix_finance_entries_dashboard_scope",
        "finance_entries",
        ["organization_id", "location_id", "effective_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_finance_entries_dashboard_scope", table_name="finance_entries"
    )
    op.drop_index("ix_payments_dashboard_completed", table_name="payments")
    op.drop_index("ix_sales_orders_dashboard_paid", table_name="sales_orders")
