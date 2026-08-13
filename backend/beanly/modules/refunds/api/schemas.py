from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from beanly.core.money import MAX_BIGINT
from beanly.modules.refunds.domain.entities import Refund
from beanly.modules.refunds.domain.enums import RefundReason, RefundStatus


class RefundLineRequest(BaseModel):
    order_item_id: UUID
    quantity: int = Field(gt=0)
    restock_quantity: int = Field(ge=0)


class RefundPaymentLineRequest(BaseModel):
    original_payment_line_id: UUID
    amount_minor: int = Field(gt=0, le=MAX_BIGINT)
    external_refund_confirmed: bool = False
    reference: str | None = Field(default=None, max_length=200)


class RefundPreviewRequest(BaseModel):
    payment_id: UUID
    reason: RefundReason
    note: str | None = Field(default=None, max_length=2000)
    lines: list[RefundLineRequest] = Field(min_length=1, max_length=100)
    payment_lines: list[RefundPaymentLineRequest] = Field(min_length=1, max_length=100)


class RefundCreateRequest(RefundPreviewRequest):
    client_refund_id: UUID


class RefundPreviewLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, coerce_numbers_to_str=True)
    order_item_id: UUID
    product_name: str
    variant_name: str
    original_quantity: int
    already_refunded_quantity: int
    available_quantity: int
    quantity: int
    restock_quantity: int
    unit_refund_minor: str
    total_refund_minor: str


class RefundPreviewPaymentLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, coerce_numbers_to_str=True)
    original_payment_line_id: UUID
    method: str
    original_amount_minor: str
    already_refunded_minor: str
    available_amount_minor: str
    amount_minor: str


class RefundPreviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, coerce_numbers_to_str=True)
    payment_id: UUID
    order_id: UUID
    currency_code: str
    total_amount_minor: str
    lines: list[RefundPreviewLineResponse]
    payment_lines: list[RefundPreviewPaymentLineResponse]


class RefundLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, coerce_numbers_to_str=True)
    id: UUID
    order_item_id: UUID
    quantity: int
    restock_quantity: int
    unit_refund_minor: str
    total_refund_minor: str
    gross_refund_minor: str
    discount_refund_minor: str
    net_refund_minor: str


class RefundPaymentLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, coerce_numbers_to_str=True)
    id: UUID
    original_payment_line_id: UUID
    method: str
    amount_minor: str
    external_refund_confirmed: bool
    reference: str | None


class RefundResponse(BaseModel):
    id: UUID
    organization_id: UUID
    location_id: UUID
    order_id: UUID
    payment_id: UUID
    client_refund_id: UUID
    status: RefundStatus
    reason: RefundReason
    note: str | None
    currency_code: str
    total_amount_minor: str
    inventory_transaction_id: UUID | None
    cogs_reversal_amount: str
    cogs_quality_status: str | None
    created_by_user_id: UUID
    created_at: datetime
    completed_by_user_id: UUID | None
    completed_at: datetime | None
    failure_code: str | None
    fiscal_status: str = "NOT_CONFIGURED"
    fiscal_external_number: str | None = None
    fiscal_external_url: str | None = None
    lines: list[RefundLineResponse]
    payment_lines: list[RefundPaymentLineResponse]

    @classmethod
    def from_entity(
        cls, value: Refund, *, fiscal: tuple[str, str | None, str | None] | None = None
    ):
        fiscal = fiscal or ("NOT_CONFIGURED", None, None)
        return cls(
            **{
                name: getattr(value, name)
                for name in (
                    "id",
                    "organization_id",
                    "location_id",
                    "order_id",
                    "payment_id",
                    "client_refund_id",
                    "status",
                    "reason",
                    "note",
                    "currency_code",
                    "inventory_transaction_id",
                    "cogs_quality_status",
                    "created_by_user_id",
                    "created_at",
                    "completed_by_user_id",
                    "completed_at",
                    "failure_code",
                )
            },
            total_amount_minor=str(value.total_amount_minor),
            cogs_reversal_amount=str(value.cogs_reversal_amount),
            fiscal_status=fiscal[0],
            fiscal_external_number=fiscal[1],
            fiscal_external_url=fiscal[2],
            lines=[RefundLineResponse.model_validate(line) for line in value.lines],
            payment_lines=[
                RefundPaymentLineResponse.model_validate(line) for line in value.payment_lines
            ],
        )
