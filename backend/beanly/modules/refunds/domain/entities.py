from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from beanly.modules.refunds.domain.enums import RefundReason, RefundStatus


@dataclass(frozen=True, slots=True)
class RefundLine:
    id: UUID
    refund_id: UUID
    order_item_id: UUID
    quantity: int
    restock_quantity: int
    unit_refund_minor: int
    total_refund_minor: int
    created_at: datetime
    gross_refund_minor: int = 0
    discount_refund_minor: int = 0
    net_refund_minor: int = 0


@dataclass(frozen=True, slots=True)
class RefundPaymentLine:
    id: UUID
    refund_id: UUID
    original_payment_line_id: UUID
    method: str
    amount_minor: int
    external_refund_confirmed: bool
    reference: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Refund:
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
    total_amount_minor: int
    inventory_transaction_id: UUID | None
    cogs_reversal_amount: Decimal
    cogs_quality_status: str | None
    created_by_user_id: UUID
    created_at: datetime
    completed_by_user_id: UUID | None
    completed_at: datetime | None
    failed_at: datetime | None
    failure_code: str | None
    lines: tuple[RefundLine, ...]
    payment_lines: tuple[RefundPaymentLine, ...]
    fulfillment_fee_minor: int = 0
