from datetime import UTC, datetime

from beanly.modules.payments.domain.entities import (
    ExternalPaymentAttempt,
    Payment,
    PaymentLine,
    TerminalBinding,
)
from beanly.modules.payments.domain.enums import (
    ExternalPaymentAttemptStatus,
    ExternalPaymentMethod,
    PaymentMethod,
)
from beanly.modules.payments.infrastructure.db.models import (
    ExternalPaymentAttemptModel,
    PaymentLineModel,
    PaymentModel,
    TerminalBindingModel,
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
        model.external_payment_attempt_id,
        model.provider_code,
        model.provider_transaction_id,
    )


def to_terminal_binding(model: TerminalBindingModel) -> TerminalBinding:
    return TerminalBinding(
        model.id,
        model.organization_id,
        model.connection_id,
        model.location_id,
        model.register_id,
        model.provider_code,
        model.external_terminal_id,
        model.transport_config,
        model.is_active,
        _utc(model.created_at),
        _utc(model.updated_at),
    )


def to_external_attempt(model: ExternalPaymentAttemptModel) -> ExternalPaymentAttempt:
    return ExternalPaymentAttempt(
        model.id,
        model.organization_id,
        model.location_id,
        model.order_id,
        model.register_id,
        model.pos_device_id,
        model.connection_id,
        model.client_attempt_id,
        model.provider_code,
        ExternalPaymentMethod(model.method),
        model.amount_minor,
        model.currency_code,
        ExternalPaymentAttemptStatus(model.status),
        model.provider_operation_id,
        model.provider_reference,
        model.request_hash,
        model.created_by_user_id,
        model.payment_id,
        _utc(model.created_at),
        _utc(model.approved_at) if model.approved_at else None,
        _utc(model.failed_at) if model.failed_at else None,
        model.failure_code,
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
