from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class AnalyticsSaleComponentSnapshot:
    inventory_item_id: UUID
    quantity_per_unit: Decimal
    actual_unit_cost: Decimal | None


@dataclass(frozen=True, slots=True)
class AnalyticsSaleItemSnapshot:
    order_item_id: UUID
    product_id: UUID
    product_variant_id: UUID
    product_name: str
    variant_name: str
    quantity: int
    revenue_amount: Decimal
    components: tuple[AnalyticsSaleComponentSnapshot, ...]


@dataclass(frozen=True, slots=True)
class AnalyticsSaleSnapshot:
    payment_id: UUID
    order_id: UUID
    organization_id: UUID
    location_id: UUID
    paid_at: datetime
    timezone: str
    currency_code: str
    order_type: str
    order_total: Decimal
    order_cogs: Decimal
    cogs_status: str
    items: tuple[AnalyticsSaleItemSnapshot, ...]
    actual_inventory_cogs: Decimal | None = None


@dataclass(frozen=True, slots=True)
class AnalyticsRefundItemSnapshot:
    product_id: UUID
    product_variant_id: UUID
    product_name: str
    variant_name: str
    quantity: int
    amount: Decimal


@dataclass(frozen=True, slots=True)
class AnalyticsRefundSnapshot:
    refund_id: UUID
    organization_id: UUID
    location_id: UUID
    completed_at: datetime
    timezone: str
    currency_code: str
    amount: Decimal
    items: tuple[AnalyticsRefundItemSnapshot, ...]


@dataclass(frozen=True, slots=True)
class AnalyticsInventoryLineSnapshot:
    inventory_item_id: UUID
    inventory_item_name: str
    base_unit: str
    quantity_delta: Decimal
    total_cost_amount: Decimal


@dataclass(frozen=True, slots=True)
class AnalyticsInventorySnapshot:
    transaction_id: UUID
    organization_id: UUID
    location_id: UUID
    warehouse_id: UUID
    transaction_type: str
    posted_at: datetime
    timezone: str
    lines: tuple[AnalyticsInventoryLineSnapshot, ...]


@dataclass(frozen=True, slots=True)
class AnalyticsExpenseSnapshot:
    expense_id: UUID
    organization_id: UUID
    location_id: UUID | None
    amount: Decimal
    occurred_at: datetime
    reversed_at: datetime | None
    timezone: str | None
    status: str


@dataclass(frozen=True, slots=True)
class AnalyticsBackfillSource:
    organization_id: UUID
    source_id: UUID
    occurred_at: datetime


class AnalyticsSourceReader(Protocol):
    async def sale(self, organization_id: UUID, payment_id: UUID) -> AnalyticsSaleSnapshot: ...

    async def refund(self, organization_id: UUID, refund_id: UUID) -> AnalyticsRefundSnapshot: ...

    async def inventory_transaction(
        self, organization_id: UUID, transaction_id: UUID
    ) -> AnalyticsInventorySnapshot: ...

    async def expense(
        self, organization_id: UUID, expense_id: UUID
    ) -> AnalyticsExpenseSnapshot: ...

    async def paid_payments(
        self,
        organization_id: UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        *,
        limit: int | None = None,
        after: tuple[datetime, UUID] | None = None,
    ) -> tuple[AnalyticsBackfillSource, ...]: ...

    async def posted_inventory_transactions(
        self,
        organization_id: UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        *,
        limit: int | None = None,
        after: tuple[datetime, UUID] | None = None,
    ) -> tuple[AnalyticsBackfillSource, ...]: ...

    async def posted_expenses(
        self,
        organization_id: UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        *,
        limit: int | None = None,
        after: tuple[datetime, UUID] | None = None,
    ) -> tuple[AnalyticsBackfillSource, ...]: ...
