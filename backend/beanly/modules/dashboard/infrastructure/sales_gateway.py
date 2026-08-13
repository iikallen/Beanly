from datetime import datetime
from decimal import Decimal
from uuid import UUID

from beanly.modules.dashboard.application.dto import (
    LocationSalesRow,
    SalesAggregate,
    TrendPoint,
)
from beanly.modules.sales.application.reporting_service import SalesReportingService


class SalesDashboardGateway:
    def __init__(
        self,
        sales: SalesReportingService,
    ) -> None:
        self.sales = sales

    async def summary(
        self,
        organization_id: UUID,
        location_ids: tuple[UUID, ...],
        date_from: datetime,
        date_to: datetime,
    ) -> SalesAggregate:
        value = await self.sales.pricing_summary(
            organization_id, location_ids, date_from, date_to
        )
        return SalesAggregate(
            Decimal(value.gross_minor) / 100,
            value.paid_orders,
            Decimal(value.discount_minor) / 100,
        )

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
        values = await self.sales.pricing_trend(
            organization_id, location_ids, buckets
        )
        return tuple(
            TrendPoint(
                bucket[0],
                Decimal(value.gross_minor - value.discount_minor) / 100,
                value.paid_orders,
                str(value.gross_minor),
                str(value.discount_minor),
            )
            for bucket, value in zip(buckets, values, strict=True)
        )

    async def locations(
        self,
        organization_id: UUID,
        location_ids: tuple[UUID, ...],
        date_from: datetime,
        date_to: datetime,
    ) -> tuple[LocationSalesRow, ...]:
        values = await self.sales.pricing_locations(
            organization_id, location_ids, date_from, date_to
        )
        return tuple(
            LocationSalesRow(
                value.location_id,
                Decimal(value.gross_minor - value.discount_minor) / 100,
                value.paid_orders,
                Decimal(value.discount_minor) / 100,
            )
            for value in values
        )
