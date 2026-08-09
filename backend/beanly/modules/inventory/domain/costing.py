from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

_SIX_PLACES = Decimal("0.000001")


@dataclass(frozen=True, slots=True)
class CostingResult:
    unit_cost_amount: Decimal
    total_cost_amount: Decimal
    quantity_after: Decimal
    average_unit_cost_after: Decimal


class WeightedAverageCostCalculator:
    def calculate(
        self,
        old_quantity: Decimal,
        old_average_unit_cost: Decimal,
        quantity_delta: Decimal,
        incoming_unit_cost: Decimal | None = None,
        incoming_total_cost: Decimal | None = None,
        *,
        reversal_unit_cost: Decimal | None = None,
        reversal_total_cost: Decimal | None = None,
    ) -> CostingResult:
        if quantity_delta == 0:
            raise ValueError("Costing quantity cannot be zero")
        if old_average_unit_cost < 0:
            raise ValueError("Average unit cost cannot be negative")
        quantity_after = old_quantity + quantity_delta

        if reversal_unit_cost is not None:
            if reversal_total_cost is None:
                raise ValueError("Reversal total cost is required")
            unit_cost = _cost(reversal_unit_cost)
            total_cost = _cost(reversal_total_cost, signed=True)
            average_after = self._reversal_average(
                old_quantity,
                old_average_unit_cost,
                quantity_after,
                total_cost,
                unit_cost,
            )
        elif quantity_delta < 0:
            unit_cost = _cost(old_average_unit_cost)
            total_cost = _cost(quantity_delta * unit_cost, signed=True)
            average_after = _cost(old_average_unit_cost)
        else:
            if incoming_unit_cost is not None and incoming_total_cost is not None:
                raise ValueError("Provide unit cost or total cost, not both")
            if incoming_unit_cost is None and incoming_total_cost is None:
                raise ValueError("Incoming unit cost is required")
            if incoming_total_cost is not None:
                total_cost = _cost(incoming_total_cost)
                unit_cost = _cost(total_cost / quantity_delta)
            else:
                unit_cost = _cost(incoming_unit_cost)
                total_cost = _cost(quantity_delta * unit_cost, signed=True)
            if old_quantity <= 0:
                average_after = unit_cost
            else:
                average_after = _cost(
                    (old_quantity * old_average_unit_cost + total_cost) / quantity_after
                )

        return CostingResult(
            unit_cost,
            total_cost,
            quantity_after,
            average_after,
        )

    @staticmethod
    def _reversal_average(
        old_quantity: Decimal,
        old_average: Decimal,
        quantity_after: Decimal,
        total_cost: Decimal,
        unit_cost: Decimal,
    ) -> Decimal:
        if old_quantity <= 0 and total_cost > 0:
            return unit_cost
        if quantity_after <= 0:
            return _cost(old_average)
        remaining_value = old_quantity * old_average + total_cost
        # The balance stores WAC at six decimal places. Removing an exact historical
        # cost can therefore expose a negative rounding residue even when the true
        # remaining value is zero. Clamp only a bounded half-ULP residue; a larger
        # negative amount is a real variance and must be resolved explicitly.
        rounding_tolerance = abs(old_quantity) * (_SIX_PLACES / 2) + _SIX_PLACES / 2
        if remaining_value < 0:
            if abs(remaining_value) <= rounding_tolerance:
                return Decimal(0)
            raise ValueError("Reversal would produce a negative average unit cost")
        return _cost(remaining_value / quantity_after)


def inventory_value(quantity: Decimal, average_unit_cost: Decimal) -> Decimal:
    return _cost(quantity * average_unit_cost, signed=True)


def _cost(value: Decimal, *, signed: bool = False) -> Decimal:
    try:
        result = value.quantize(_SIX_PLACES, rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise ValueError("Cost is outside NUMERIC(20, 6)") from exc
    if not result.is_finite() or result.adjusted() > 13 or (not signed and result < 0):
        raise ValueError("Cost is outside NUMERIC(20, 6)")
    return result
