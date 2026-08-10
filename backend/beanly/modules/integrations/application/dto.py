from dataclasses import dataclass
from datetime import datetime
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
    name: str
    quantity: int
    unit_price_minor: int
    total_minor: int


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


@dataclass(frozen=True, slots=True)
class FiscalReceiptResult:
    external_receipt_id: str
    receipt_number: str
    receipt_url: str | None
    provider_request_id: str | None


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
