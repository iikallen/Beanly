from dataclasses import dataclass
from uuid import UUID

from beanly.modules.refunds.domain.enums import RefundReason


@dataclass(frozen=True, slots=True)
class RefundLineInput:
    order_item_id: UUID
    quantity: int
    restock_quantity: int


@dataclass(frozen=True, slots=True)
class RefundPaymentLineInput:
    original_payment_line_id: UUID
    amount_minor: int
    external_refund_confirmed: bool = False
    reference: str | None = None


@dataclass(frozen=True, slots=True)
class RefundInput:
    payment_id: UUID
    reason: RefundReason
    note: str | None
    lines: tuple[RefundLineInput, ...]
    payment_lines: tuple[RefundPaymentLineInput, ...]
    client_refund_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class PreviewLine:
    order_item_id: UUID
    product_name: str
    variant_name: str
    original_quantity: int
    already_refunded_quantity: int
    available_quantity: int
    quantity: int
    restock_quantity: int
    unit_refund_minor: int
    total_refund_minor: int


@dataclass(frozen=True, slots=True)
class PreviewPaymentLine:
    original_payment_line_id: UUID
    method: str
    original_amount_minor: int
    already_refunded_minor: int
    available_amount_minor: int
    amount_minor: int


@dataclass(frozen=True, slots=True)
class RefundPreview:
    payment_id: UUID
    order_id: UUID
    currency_code: str
    total_amount_minor: int
    lines: tuple[PreviewLine, ...]
    payment_lines: tuple[PreviewPaymentLine, ...]
