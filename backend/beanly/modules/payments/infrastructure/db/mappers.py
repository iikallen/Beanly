from datetime import UTC, datetime

from beanly.modules.payments.domain.entities import Payment, PaymentLine
from beanly.modules.payments.domain.enums import PaymentMethod
from beanly.modules.payments.infrastructure.db.models import (
    PaymentLineModel,
    PaymentModel,
)


def to_line(model: PaymentLineModel) -> PaymentLine:
    return PaymentLine(
        model.id,
        model.payment_id,
        PaymentMethod(model.method),
        model.amount_minor,
        model.cash_received_minor,
        model.change_minor,
        model.reference,
        model.sort_order,
        _utc(model.created_at),
    )


def to_payment(model: PaymentModel) -> Payment:
    return Payment(
        model.id,
        model.organization_id,
        model.location_id,
        model.order_id,
        model.shift_id,
        model.client_payment_id,
        model.currency_code,
        model.amount_minor,
        model.created_by_user_id,
        _utc(model.completed_at),
        _utc(model.created_at),
        _utc(model.updated_at),
        tuple(
            to_line(line)
            for line in sorted(
                model.__dict__.get("lines", ()), key=lambda value: value.sort_order
            )
        ),
        model.offline_session_id,
    )


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
