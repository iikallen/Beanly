from decimal import ROUND_HALF_UP, Decimal

MAX_VAT_RATE = Decimal("999.9999")
VAT_RATE_QUANTUM = Decimal("0.0001")


def normalize_vat_rate(value: Decimal | int | None) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (Decimal, int)):
        raise ValueError("VAT rate must be an exact decimal value")
    value = Decimal(value)
    if not value.is_finite() or value < 0 or value > MAX_VAT_RATE:
        raise ValueError("VAT rate is outside NUMERIC(7,4)")
    return value.quantize(VAT_RATE_QUANTUM, rounding=ROUND_HALF_UP)


def vat_minor(total_minor: int, rate: Decimal | int | None) -> int:
    """Return VAT embedded in a VAT-inclusive minor-unit amount."""
    rate = normalize_vat_rate(rate)
    if rate is None or rate == 0:
        return 0
    net = (Decimal(total_minor) / (Decimal(1) + rate / Decimal(100))).quantize(
        Decimal(1), rounding=ROUND_HALF_UP
    )
    return total_minor - int(net)
