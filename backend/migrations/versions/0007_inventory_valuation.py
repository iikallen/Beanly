"""inventory valuation and moving weighted average cost

Revision ID: 0007_inventory_valuation
Revises: 0006_purchasing
"""

from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

import sqlalchemy as sa
from alembic import op

revision: str = "0007_inventory_valuation"
down_revision: str | None = "0006_purchasing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SIX_PLACES = Decimal("0.000001")


def _six(value: Decimal) -> Decimal:
    return value.quantize(_SIX_PLACES, rounding=ROUND_HALF_UP)


def _backfill_legacy_valuation() -> None:
    connection = op.get_bind()
    rows = list(
        connection.execute(
            sa.text(
            """
            SELECT line.id, tx.warehouse_id, line.inventory_item_id,
                   line.quantity_delta, line.unit_cost_amount,
                   tx.reversal_of_id
            FROM inventory_transaction_lines AS line
            JOIN inventory_transactions AS tx ON tx.id = line.transaction_id
            WHERE tx.status IN ('POSTED', 'REVERSED')
            ORDER BY tx.warehouse_id, line.inventory_item_id,
                     COALESCE(tx.posted_at, tx.created_at),
                     tx.created_at, line.created_at, line.id
            """
            )
        ).mappings()
    )
    states: dict[tuple[UUID, UUID], tuple[Decimal, Decimal]] = {}
    update_line = sa.text(
        """
        UPDATE inventory_transaction_lines
        SET requested_unit_cost_amount=:requested_unit_cost,
            unit_cost_amount=:unit_cost,
            total_cost_amount=:total_cost,
            quantity_after=:quantity_after,
            average_unit_cost_after=:average_after
        WHERE id=:line_id
        """
    )

    for row in rows:
        key = (row["warehouse_id"], row["inventory_item_id"])
        old_quantity, old_average = states.get(key, (Decimal(0), Decimal(0)))
        delta = Decimal(row["quantity_delta"])
        requested_cost = (
            Decimal(row["unit_cost_amount"])
            if row["unit_cost_amount"] is not None
            else None
        )
        quantity_after = _six(old_quantity + delta)

        if delta > 0:
            unit_cost = _six(requested_cost or Decimal(0))
            total_cost = _six(delta * unit_cost)
            average_after = (
                unit_cost
                if old_quantity <= 0
                else _six((old_quantity * old_average + total_cost) / quantity_after)
            )
        elif row["reversal_of_id"] is not None and requested_cost is not None:
            unit_cost = _six(requested_cost)
            total_cost = _six(delta * unit_cost)
            if quantity_after <= 0:
                average_after = old_average
            else:
                remaining_value = old_quantity * old_average + total_cost
                rounding_tolerance = (
                    abs(old_quantity) * (_SIX_PLACES / 2) + _SIX_PLACES / 2
                )
                average_after = (
                    Decimal(0)
                    if remaining_value < 0 and abs(remaining_value) <= rounding_tolerance
                    else _six(remaining_value / quantity_after)
                )
                if average_after < 0:
                    raise RuntimeError(
                        "Legacy reversal produces negative inventory valuation"
                    )
        else:
            unit_cost = old_average
            total_cost = _six(delta * unit_cost)
            average_after = old_average

        connection.execute(
            update_line,
            {
                "requested_unit_cost": requested_cost,
                "unit_cost": unit_cost,
                "total_cost": total_cost,
                "quantity_after": quantity_after,
                "average_after": average_after,
                "line_id": row["id"],
            },
        )
        states[key] = (quantity_after, average_after)

    update_balance = sa.text(
        """
        UPDATE stock_balances
        SET average_unit_cost=:average
        WHERE warehouse_id=:warehouse_id
          AND inventory_item_id=:inventory_item_id
        """
    )
    for (warehouse_id, item_id), (_, average) in states.items():
        connection.execute(
            update_balance,
            {
                "average": average,
                "warehouse_id": warehouse_id,
                "inventory_item_id": item_id,
            },
        )


def upgrade() -> None:
    op.add_column(
        "stock_balances",
        sa.Column(
            "average_unit_cost",
            sa.Numeric(20, 6),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "inventory_transaction_lines",
        sa.Column("requested_unit_cost_amount", sa.Numeric(20, 6), nullable=True),
    )
    op.add_column(
        "inventory_transaction_lines",
        sa.Column("requested_total_cost_amount", sa.Numeric(20, 6), nullable=True),
    )
    op.add_column(
        "inventory_transaction_lines",
        sa.Column("total_cost_amount", sa.Numeric(20, 6), nullable=True),
    )
    op.add_column(
        "inventory_transaction_lines",
        sa.Column("quantity_after", sa.Numeric(20, 6), nullable=True),
    )
    op.add_column(
        "inventory_transaction_lines",
        sa.Column("average_unit_cost_after", sa.Numeric(20, 6), nullable=True),
    )
    _backfill_legacy_valuation()


def downgrade() -> None:
    op.drop_column("inventory_transaction_lines", "average_unit_cost_after")
    op.drop_column("inventory_transaction_lines", "quantity_after")
    op.drop_column("inventory_transaction_lines", "total_cost_amount")
    op.drop_column("inventory_transaction_lines", "requested_total_cost_amount")
    op.drop_column("inventory_transaction_lines", "requested_unit_cost_amount")
    op.drop_column("stock_balances", "average_unit_cost")
