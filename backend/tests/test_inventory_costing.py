from decimal import Decimal

import pytest

from beanly.modules.inventory.domain.costing import (
    WeightedAverageCostCalculator,
    inventory_value,
)


def test_weighted_average_purchase_and_outflow_snapshots() -> None:
    calculator = WeightedAverageCostCalculator()

    first = calculator.calculate(
        Decimal(0),
        Decimal(0),
        Decimal(1000),
        incoming_total_cost=Decimal(8000),
    )
    assert first.quantity_after == Decimal("1000")
    assert first.unit_cost_amount == Decimal("8.000000")
    assert first.total_cost_amount == Decimal("8000.000000")
    assert first.average_unit_cost_after == Decimal("8.000000")

    second = calculator.calculate(
        first.quantity_after,
        first.average_unit_cost_after,
        Decimal(1000),
        incoming_total_cost=Decimal(9000),
    )
    assert second.quantity_after == Decimal("2000")
    assert second.average_unit_cost_after == Decimal("8.500000")
    assert inventory_value(second.quantity_after, second.average_unit_cost_after) == Decimal(
        "17000.000000"
    )

    outflow = calculator.calculate(
        second.quantity_after,
        second.average_unit_cost_after,
        Decimal(-500),
    )
    assert outflow.unit_cost_amount == Decimal("8.500000")
    assert outflow.total_cost_amount == Decimal("-4250.000000")
    assert outflow.quantity_after == Decimal("1500")
    assert outflow.average_unit_cost_after == Decimal("8.500000")


def test_negative_stock_reset_and_exact_late_reversal() -> None:
    calculator = WeightedAverageCostCalculator()

    negative = calculator.calculate(Decimal(0), Decimal(8), Decimal(-10))
    assert negative.quantity_after == Decimal("-10")
    assert negative.average_unit_cost_after == Decimal("8.000000")

    replenished = calculator.calculate(
        negative.quantity_after,
        negative.average_unit_cost_after,
        Decimal(1000),
        incoming_total_cost=Decimal(9000),
    )
    assert replenished.quantity_after == Decimal("990")
    assert replenished.average_unit_cost_after == Decimal("9.000000")

    reversed_first_purchase = calculator.calculate(
        Decimal(2000),
        Decimal("8.5"),
        Decimal(-1000),
        reversal_unit_cost=Decimal(8),
        reversal_total_cost=Decimal(-8000),
    )
    assert reversed_first_purchase.quantity_after == Decimal("1000")
    assert reversed_first_purchase.total_cost_amount == Decimal("-8000.000000")
    assert reversed_first_purchase.average_unit_cost_after == Decimal("9.000000")

    rounded = calculator.calculate(
        Decimal(3000),
        Decimal("33.333333"),
        Decimal(-1000),
        reversal_unit_cost=Decimal(100),
        reversal_total_cost=Decimal(-100000),
    )
    assert rounded.quantity_after == Decimal("2000")
    assert rounded.average_unit_cost_after == Decimal(0)

    with pytest.raises(ValueError, match="negative average unit cost"):
        calculator.calculate(
            Decimal(2000),
            Decimal(1),
            Decimal(-1000),
            reversal_unit_cost=Decimal(100),
            reversal_total_cost=Decimal(-100000),
        )


def test_costing_uses_decimal_round_half_up_and_rejects_invalid_values() -> None:
    calculator = WeightedAverageCostCalculator()
    precise = calculator.calculate(
        Decimal("0.100001"),
        Decimal("1.000001"),
        Decimal("0.200002"),
        incoming_total_cost=Decimal("0.400004"),
    )
    assert precise.quantity_after == Decimal("0.300003")
    assert precise.average_unit_cost_after == Decimal("1.666667")

    with pytest.raises(ValueError, match="outside NUMERIC"):
        calculator.calculate(
            Decimal(0),
            Decimal(0),
            Decimal(1),
            incoming_unit_cost=Decimal("NaN"),
        )
    with pytest.raises(ValueError, match="Provide unit cost or total cost"):
        calculator.calculate(
            Decimal(0),
            Decimal(0),
            Decimal(1),
            incoming_unit_cost=Decimal(1),
            incoming_total_cost=Decimal(1),
        )


def test_three_receipt_weighted_average_example() -> None:
    calculator = WeightedAverageCostCalculator()
    state = calculator.calculate(
        Decimal(0),
        Decimal(0),
        Decimal(10000),
        incoming_total_cost=Decimal(80000),
    )
    state = calculator.calculate(
        state.quantity_after,
        state.average_unit_cost_after,
        Decimal(5000),
        incoming_total_cost=Decimal(50000),
    )
    state = calculator.calculate(
        state.quantity_after,
        state.average_unit_cost_after,
        Decimal(3000),
        incoming_total_cost=Decimal(21000),
    )
    assert state.quantity_after == Decimal("18000")
    assert state.average_unit_cost_after == Decimal("8.388889")
