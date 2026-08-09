from decimal import Decimal, InvalidOperation
from enum import StrEnum


class UnitCode(StrEnum):
    G = "g"
    KG = "kg"
    ML = "ml"
    L = "l"
    PCS = "pcs"

    @property
    def base_unit(self) -> "UnitCode":
        return {
            UnitCode.G: UnitCode.G,
            UnitCode.KG: UnitCode.G,
            UnitCode.ML: UnitCode.ML,
            UnitCode.L: UnitCode.ML,
            UnitCode.PCS: UnitCode.PCS,
        }[self]

    @property
    def base_factor(self) -> Decimal:
        return {
            UnitCode.G: Decimal(1),
            UnitCode.KG: Decimal(1000),
            UnitCode.ML: Decimal(1),
            UnitCode.L: Decimal(1000),
            UnitCode.PCS: Decimal(1),
        }[self]


BASE_UNITS = frozenset({UnitCode.G, UnitCode.ML, UnitCode.PCS})


def to_base_quantity(value: Decimal, unit: UnitCode, base_unit: UnitCode) -> Decimal:
    if base_unit not in BASE_UNITS or unit.base_unit != base_unit:
        raise ValueError("Unit is incompatible with the inventory item")
    try:
        result = value * unit.base_factor
    except InvalidOperation as exc:
        raise ValueError("Invalid quantity") from exc
    if not result.is_finite() or result == 0 or result.adjusted() > 13:
        raise ValueError("Quantity is outside NUMERIC(20, 6)")
    if result.as_tuple().exponent < -6:
        raise ValueError("Quantity supports at most 6 decimal places in base units")
    return result


def decimal_string(value: Decimal) -> str:
    rendered = format(value, "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered
