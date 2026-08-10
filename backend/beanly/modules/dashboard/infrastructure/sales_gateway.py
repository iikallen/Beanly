from datetime import datetime
from uuid import UUID

from beanly.modules.dashboard.application.dto import (
    LocationSalesRow,
    SalesAggregate,
    TrendPoint,
)
from beanly.modules.payments.application.reporting_service import (
    PaymentsReportingService,
)
from beanly.modules.sales.application.reporting_service import SalesReportingService


class SalesDashboardGateway:
    def __init__(
        self,
        payments: PaymentsReportingService,
        sales: SalesReportingService,
    ) -> None:
        self.payments = payments
        self.sales = sales

    async def summary(
        self,
        organization_id: UUID,
        location_ids: tuple[UUID, ...],
        date_from: datetime,
        date_to: datetime,
    ) -> SalesAggregate:
        value = await self.payments.sales_summary(
            organization_id, location_ids, date_from, date_to
        )
        return SalesAggregate(value.revenue, value.paid_orders)

    async def operations(
        self, organization_id: UUID, location_ids: tuple[UUID, ...]
    ) -> tuple[int, int]:
        value = await self.sales.operations(organization_id, location_ids)
        return value.open_orders, value.open_shifts

    async def trend(
        self,
        organization_id: UUID,
        location_ids: tuple[UUID, ...],
        buckets: tuple[tuple[datetime, datetime], ...],
    ) -> tuple[TrendPoint, ...]:
        values = await self.payments.sales_trend(
            organization_id, location_ids, buckets
        )
        return tuple(
            TrendPoint(bucket[0], value.revenue, value.orders)
            for bucket, value in zip(buckets, values, strict=True)
        )

    async def locations(
        self,
        organization_id: UUID,
        location_ids: tuple[UUID, ...],
        date_from: datetime,
        date_to: datetime,
    ) -> tuple[LocationSalesRow, ...]:
        values = await self.payments.location_sales_summary(
            organization_id, location_ids, date_from, date_to
        )
        return tuple(
            LocationSalesRow(value.location_id, value.revenue, value.paid_orders)
            for value in values
        )
