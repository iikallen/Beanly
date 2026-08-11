from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field

from beanly.core.money import MAX_BIGINT, MAX_NUMERIC_20_6_MINOR
from beanly.modules.payments.domain.entities import (
    ExternalPaymentAttempt,
    Payment,
    ShiftPaymentSummary,
    TerminalBinding,
)
from beanly.modules.payments.domain.enums import ExternalPaymentMethod, PaymentMethod


class PaymentLineRequest(BaseModel):
    method: PaymentMethod
    amount_minor: Annotated[int, Field(ge=0, le=MAX_NUMERIC_20_6_MINOR)]
    cash_received_minor: Annotated[
        int | None, Field(ge=0, le=MAX_BIGINT)
    ] = None
    reference: Annotated[str | None, Field(max_length=200)] = None


class PaymentCompleteRequest(BaseModel):
    client_payment_id: UUID
    lines: Annotated[list[PaymentLineRequest], Field(max_length=100)]


class TerminalBindingCreateRequest(BaseModel):
    connection_id: UUID
    location_id: UUID
    register_id: UUID
    provider_code: Annotated[str, Field(min_length=1, max_length=80)]
    external_terminal_id: Annotated[str | None, Field(max_length=255)] = None
    is_active: bool = True


class TerminalBindingPatchRequest(BaseModel):
    external_terminal_id: Annotated[str | None, Field(max_length=255)] = None
    transport_config: dict[str, object] | None = None
    is_active: bool | None = None


class TerminalBindingResponse(BaseModel):
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

    @classmethod
    def from_entity(cls, value: TerminalBinding) -> "TerminalBindingResponse":
        return cls.model_validate(value, from_attributes=True)


class ExternalPaymentAttemptCreateRequest(BaseModel):
    client_attempt_id: UUID
    order_id: UUID
    register_id: UUID
    pos_device_id: UUID | None = None
    connection_id: UUID
    provider_code: Annotated[str, Field(min_length=1, max_length=80)]
    method: ExternalPaymentMethod
    amount_minor: Annotated[int, Field(gt=0, le=MAX_NUMERIC_20_6_MINOR)]
    currency_code: Annotated[str, Field(min_length=3, max_length=3)]


class ExternalPaymentAttemptResponse(BaseModel):
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
    amount_minor: str
    currency_code: str
    status: str
    provider_operation_id: str | None
    provider_reference: str | None
    created_by_user_id: UUID
    payment_id: UUID | None
    created_at: datetime
    approved_at: datetime | None
    failed_at: datetime | None
    failure_code: str | None

    @classmethod
    def from_entity(cls, value: ExternalPaymentAttempt) -> "ExternalPaymentAttemptResponse":
        return cls(
            id=value.id,
            organization_id=value.organization_id,
            location_id=value.location_id,
            order_id=value.order_id,
            register_id=value.register_id,
            pos_device_id=value.pos_device_id,
            connection_id=value.connection_id,
            client_attempt_id=value.client_attempt_id,
            provider_code=value.provider_code,
            method=value.method,
            amount_minor=str(value.amount_minor),
            currency_code=value.currency_code,
            status=value.status.value,
            provider_operation_id=value.provider_operation_id,
            provider_reference=value.provider_reference,
            created_by_user_id=value.created_by_user_id,
            payment_id=value.payment_id,
            created_at=_utc(value.created_at),
            approved_at=_utc(value.approved_at) if value.approved_at else None,
            failed_at=_utc(value.failed_at) if value.failed_at else None,
            failure_code=value.failure_code,
        )


class PaymentLineResponse(BaseModel):
    id: UUID
    payment_id: UUID
    method: PaymentMethod
    amount_minor: str
    cash_received_minor: str | None
    change_minor: str
    reference: str | None
    sort_order: int
    created_at: datetime
    external_payment_attempt_id: UUID | None
    provider_code: str | None
    provider_transaction_id: str | None


class PaymentResponse(BaseModel):
    id: UUID
    organization_id: UUID
    location_id: UUID
    order_id: UUID
    shift_id: UUID
    client_payment_id: UUID
    currency_code: str
    amount_minor: str
    created_by_user_id: UUID
    completed_at: datetime
    created_at: datetime
    updated_at: datetime
    lines: list[PaymentLineResponse]

    @classmethod
    def from_entity(cls, value: Payment) -> "PaymentResponse":
        return cls(
            id=value.id,
            organization_id=value.organization_id,
            location_id=value.location_id,
            order_id=value.order_id,
            shift_id=value.shift_id,
            client_payment_id=value.client_payment_id,
            currency_code=value.currency_code,
            amount_minor=str(value.amount_minor),
            created_by_user_id=value.created_by_user_id,
            completed_at=_utc(value.completed_at),
            created_at=_utc(value.created_at),
            updated_at=_utc(value.updated_at),
            lines=[
                PaymentLineResponse(
                    id=line.id,
                    payment_id=line.payment_id,
                    method=line.method,
                    amount_minor=str(line.amount_minor),
                    cash_received_minor=(
                        str(line.cash_received_minor)
                        if line.cash_received_minor is not None
                        else None
                    ),
                    change_minor=str(line.change_minor),
                    reference=line.reference,
                    sort_order=line.sort_order,
                    created_at=_utc(line.created_at),
                    external_payment_attempt_id=line.external_payment_attempt_id,
                    provider_code=line.provider_code,
                    provider_transaction_id=line.provider_transaction_id,
                )
                for line in value.lines
            ],
        )


def _utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.utcoffset() is not None else value.replace(tzinfo=UTC)


class PaymentMethodResponse(BaseModel):
    code: PaymentMethod
    name: str


class ShiftMethodSummaryResponse(BaseModel):
    method: PaymentMethod
    amount_minor: str


class ShiftPaymentSummaryResponse(BaseModel):
    orders_paid: int
    gross_amount_minor: str
    methods: list[ShiftMethodSummaryResponse]

    @classmethod
    def from_entity(cls, value: ShiftPaymentSummary) -> "ShiftPaymentSummaryResponse":
        return cls(
            orders_paid=value.orders_paid,
            gross_amount_minor=str(value.gross_amount_minor),
            methods=[
                ShiftMethodSummaryResponse(
                    method=item.method,
                    amount_minor=str(item.amount_minor),
                )
                for item in value.methods
            ],
        )
