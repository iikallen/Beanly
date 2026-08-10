from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from beanly.modules.analytics.application.dto import (
    HourlySalesDelta,
    InventoryConsumptionDailyDelta,
    LocationMetricsDailyDelta,
    ProductSalesDailyDelta,
    SalesDailyDelta,
)
from beanly.modules.analytics.domain.enums import ProductGroupBy, ProductSort


@dataclass(frozen=True, slots=True)
class OverviewAggregate:
    revenue: Decimal
    paid_orders: int
    items_sold: int
    cogs: Decimal
    inventory_losses: Decimal
    incomplete_cogs_orders: int


@dataclass(frozen=True, slots=True)
class ProductAggregate:
    product_id: UUID
    product_variant_id: UUID | None
    name: str
    variant_name: str | None
    quantity_sold: int
    revenue: Decimal
    orders: int
    cogs: Decimal
    incomplete_cogs_orders: int


@dataclass(frozen=True, slots=True)
class HourAggregate:
    local_date: date
    local_hour: int
    revenue: Decimal
    paid_orders: int
    items_sold: int


@dataclass(frozen=True, slots=True)
class ConsumptionAggregate:
    inventory_item_id: UUID
    name: str
    base_unit: str
    sale_quantity: Decimal
    sale_cost_amount: Decimal
    writeoff_quantity: Decimal
    writeoff_cost_amount: Decimal
    adjustment_quantity: Decimal


@dataclass(frozen=True, slots=True)
class LocationAggregate:
    location_id: UUID
    location_name: str
    revenue: Decimal
    paid_orders: int
    items_sold: int
    cogs: Decimal
    operating_expenses: Decimal
    inventory_losses: Decimal
    inventory_gains: Decimal


class AnalyticsRepository(Protocol):
    async def add_receipt(
        self,
        projection_name: str,
        source_type: str,
        source_id: UUID,
        organization_id: UUID,
        source_event_id: UUID | None,
        source_occurred_at: datetime,
    ) -> bool: ...

    async def upsert_sales(self, delta: SalesDailyDelta) -> None: ...

    async def upsert_product(self, delta: ProductSalesDailyDelta) -> None: ...

    async def upsert_hour(self, delta: HourlySalesDelta) -> None: ...

    async def upsert_location(self, delta: LocationMetricsDailyDelta) -> None: ...

    async def upsert_consumption(
        self, delta: InventoryConsumptionDailyDelta
    ) -> None: ...

    async def organization_currency(self, organization_id: UUID) -> str: ...

    async def overview(
        self,
        organization_id: UUID,
        date_from: date,
        date_to: date,
        location_ids: set[UUID] | None,
    ) -> OverviewAggregate: ...

    async def products(
        self,
        organization_id: UUID,
        date_from: date,
        date_to: date,
        location_ids: set[UUID] | None,
        group_by: ProductGroupBy,
        sort_by: ProductSort,
        limit: int | None,
    ) -> tuple[ProductAggregate, ...]: ...

    async def hours(
        self,
        organization_id: UUID,
        date_from: date,
        date_to: date,
        location_ids: set[UUID] | None,
    ) -> tuple[HourAggregate, ...]: ...

    async def consumption(
        self,
        organization_id: UUID,
        date_from: date,
        date_to: date,
        location_ids: set[UUID] | None,
        warehouse_id: UUID | None,
        inventory_item_id: UUID | None,
    ) -> tuple[ConsumptionAggregate, ...]: ...

    async def locations(
        self,
        organization_id: UUID,
        date_from: date,
        date_to: date,
        location_ids: set[UUID] | None,
    ) -> tuple[LocationAggregate, ...]: ...

    async def data_as_of(self, organization_id: UUID) -> datetime | None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
