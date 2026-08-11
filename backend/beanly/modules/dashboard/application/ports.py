from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from beanly.modules.dashboard.application.dto import (
    ActiveInventoryCount,
    FinanceSnapshot,
    InventoryHealth,
    LocationFinanceRow,
    LocationSalesRow,
    NegativeStockItem,
    PaymentMixRow,
    RefundAggregate,
    RefundLocationRow,
    RefundTrendRow,
    SalesAggregate,
    ScopeLocation,
    TrendPoint,
)
from beanly.modules.organizations.domain.entities import TenantContext


class OrganizationDashboardPort(Protocol):
    async def locations(self, context: TenantContext) -> tuple[ScopeLocation, ...]: ...
    async def reporting_timezone(self, context: TenantContext) -> str: ...


class SalesDashboardPort(Protocol):
    async def summary(
        self,
        organization_id: UUID,
        location_ids: tuple[UUID, ...],
        date_from: datetime,
        date_to: datetime,
    ) -> SalesAggregate: ...

    async def operations(
        self, organization_id: UUID, location_ids: tuple[UUID, ...]
    ) -> tuple[int, int]: ...

    async def trend(
        self,
        organization_id: UUID,
        location_ids: tuple[UUID, ...],
        buckets: tuple[tuple[datetime, datetime], ...],
    ) -> tuple[TrendPoint, ...]: ...

    async def locations(
        self,
        organization_id: UUID,
        location_ids: tuple[UUID, ...],
        date_from: datetime,
        date_to: datetime,
    ) -> tuple[LocationSalesRow, ...]: ...


class PaymentsDashboardPort(Protocol):
    async def mix(
        self,
        organization_id: UUID,
        location_ids: tuple[UUID, ...],
        date_from: datetime,
        date_to: datetime,
    ) -> tuple[PaymentMixRow, ...]: ...


class RefundsDashboardPort(Protocol):
    async def summary(
        self,
        organization_id: UUID,
        location_ids: tuple[UUID, ...],
        date_from: datetime,
        date_to: datetime,
    ) -> RefundAggregate: ...

    async def trend(
        self,
        organization_id: UUID,
        location_ids: tuple[UUID, ...],
        buckets: tuple[tuple[datetime, datetime], ...],
    ) -> tuple[RefundTrendRow, ...]: ...

    async def locations(
        self,
        organization_id: UUID,
        location_ids: tuple[UUID, ...],
        date_from: datetime,
        date_to: datetime,
    ) -> tuple[RefundLocationRow, ...]: ...


class InventoryDashboardPort(Protocol):
    async def health(
        self, organization_id: UUID, location_ids: tuple[UUID, ...]
    ) -> InventoryHealth: ...

    async def negative_items(
        self, organization_id: UUID, location_ids: tuple[UUID, ...], limit: int
    ) -> tuple[NegativeStockItem, ...]: ...

    async def active_counts(
        self, organization_id: UUID, location_ids: tuple[UUID, ...]
    ) -> tuple[ActiveInventoryCount, ...]: ...


class FinanceDashboardPort(Protocol):
    async def snapshot(
        self,
        context: TenantContext,
        date_from: datetime,
        date_to: datetime,
        location_id: UUID | None,
    ) -> FinanceSnapshot: ...

    async def operating_profit(
        self,
        context: TenantContext,
        date_from: datetime,
        date_to: datetime,
        location_id: UUID | None,
    ) -> Decimal: ...

    async def locations(
        self, context: TenantContext, date_from: datetime, date_to: datetime
    ) -> tuple[LocationFinanceRow, ...]: ...
