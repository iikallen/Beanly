from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field

from beanly.core.money import MAX_BIGINT, MAX_NUMERIC_20_6_MINOR
from beanly.modules.payments.domain.entities import Payment, ShiftPaymentSummary
from beanly.modules.payments.domain.enums import PaymentMethod


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
