from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from beanly.modules.payments.domain.enums import (
    ExternalPaymentAttemptStatus,
    ExternalPaymentMethod,
    PaymentMethod,
)


@dataclass(frozen=True, slots=True)
class PaymentLine:
    id: UUID
    payment_id: UUID
    method: PaymentMethod
    amount_minor: int
    cash_received_minor: int | None
    change_minor: int
    reference: str | None
    sort_order: int
    created_at: datetime
    external_payment_attempt_id: UUID | None = None
    provider_code: str | None = None
    provider_transaction_id: str | None = None


@dataclass(frozen=True, slots=True)
class Payment:
    id: UUID
    organization_id: UUID
    location_id: UUID
    order_id: UUID
    shift_id: UUID
    client_payment_id: UUID
    currency_code: str
    amount_minor: int
    created_by_user_id: UUID
    completed_at: datetime
    created_at: datetime
    updated_at: datetime
    lines: tuple[PaymentLine, ...] = ()
    offline_session_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class PaymentMethodTotal:
    method: PaymentMethod
    amount_minor: int


@dataclass(frozen=True, slots=True)
class ShiftPaymentSummary:
    orders_paid: int
    gross_amount_minor: int
    methods: tuple[PaymentMethodTotal, ...]


@dataclass(frozen=True, slots=True)
class TerminalBinding:
    id: UUID
    organization_id: UUID
    connection_id: UUID
    location_id: UUID
    register_id: UUID
    provider_code: str
    external_terminal_id: str | None
    transport_config: dict[str, object]
    is_active: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ExternalPaymentAttempt:
    id: UUID
    organization_id: UUID
    location_id: UUID
    order_id: UUID
    register_id: UUID
    pos_device_id: UUID | None
    connection_id: UUID
    client_attempt_id: UUID
    provider_code: str
    method: ExternalPaymentMethod
    amount_minor: int
    currency_code: str
    status: ExternalPaymentAttemptStatus
    provider_operation_id: str | None
    provider_reference: str | None
    request_hash: str
    created_by_user_id: UUID
    payment_id: UUID | None
    created_at: datetime
    approved_at: datetime | None
    failed_at: datetime | None
    failure_code: str | None
    order_pricing_revision: int | None = None
