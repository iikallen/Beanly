from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from beanly.modules.integrations.domain.enums import (
    IntegrationAuthType,
    IntegrationCapability,
)


@dataclass(frozen=True, slots=True)
class ProviderDescriptor:
    code: str
    name: str
    capabilities: frozenset[IntegrationCapability]
    auth_type: IntegrationAuthType
    supports_webhooks: bool = False
    supports_health_check: bool = False
    location_scoped: bool = False


@dataclass(frozen=True, slots=True)
class FiscalItem:
    fiscal_name: str
    quantity: int
    unit_price_minor: int
    total_minor: int
    gross_total_minor: int | None = None
    discount_minor: int = 0
    nkt_code: str | None = None
    nkt_code_type: str | None = None
    unit_code: str = "pcs"
    vat_rate: Decimal | None = None
    vat_amount_minor: int = 0
    marking_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        gross = (
            self.total_minor + self.discount_minor
            if self.gross_total_minor is None
            else self.gross_total_minor
        )
        if gross - self.discount_minor != self.total_minor:
            raise ValueError("Fiscal item gross - discount must equal total")
        object.__setattr__(self, "gross_total_minor", gross)

    @property
    def name(self) -> str:
        return self.fiscal_name


@dataclass(frozen=True, slots=True)
class FiscalPaymentLine:
    method: str
    amount_minor: int


@dataclass(frozen=True, slots=True)
class FiscalSaleCommand:
    payment_id: UUID
    order_number: int
    occurred_at: datetime
    currency: str
    items: tuple[FiscalItem, ...]
    payment_lines: tuple[FiscalPaymentLine, ...]
    total_minor: int
    discount_total_minor: int = 0

    def __post_init__(self) -> None:
        if sum(item.total_minor for item in self.items) != self.total_minor:
            raise ValueError("Fiscal sale item totals must reconcile")
        if sum(item.discount_minor for item in self.items) != self.discount_total_minor:
            raise ValueError("Fiscal sale discounts must reconcile")


@dataclass(frozen=True, slots=True)
class FiscalRefundCommand:
    refund_id: UUID
    original_payment_id: UUID
    original_external_receipt_id: str
    occurred_at: datetime
    currency: str
    items: tuple[FiscalItem, ...]
    payment_lines: tuple[FiscalPaymentLine, ...]
    total_minor: int
    reason: str
    gross_total_minor: int | None = None
    discount_total_minor: int = 0

    def __post_init__(self) -> None:
        gross = (
            self.total_minor + self.discount_total_minor
            if self.gross_total_minor is None
            else self.gross_total_minor
        )
        if gross - self.discount_total_minor != self.total_minor:
            raise ValueError("Fiscal refund gross - discount must equal total")
        object.__setattr__(self, "gross_total_minor", gross)


@dataclass(frozen=True, slots=True)
class FiscalReceiptResult:
    external_receipt_id: str
    receipt_number: str
    receipt_url: str | None
    provider_request_id: str | None


@dataclass(frozen=True, slots=True)
class FiscalShiftCommand:
    shift_id: UUID


@dataclass(frozen=True, slots=True)
class NormalizedWebhookEvent:
    external_event_id: str
    event_type: str
    payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class OAuthSession:
    id: UUID
    organization_id: UUID
    user_id: UUID
    code_verifier_ciphertext: str
    redirect_uri: str
