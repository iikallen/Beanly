from datetime import datetime
from uuid import UUID

from beanly.modules.dashboard.application.dto import (
    RefundAggregate,
    RefundLocationRow,
    RefundTrendRow,
)
from beanly.modules.refunds.application.reporting_service import (
    RefundReportingService,
)


class RefundsDashboardGateway:
    def __init__(self, refunds: RefundReportingService) -> None:
        self.refunds = refunds

    async def summary(
        self,
        organization_id: UUID,
        location_ids: tuple[UUID, ...],
        date_from: datetime,
        date_to: datetime,
    ) -> RefundAggregate:
        value = await self.refunds.summary(organization_id, location_ids, date_from, date_to)
        return RefundAggregate(value)

    async def trend(
        self,
        organization_id: UUID,
        location_ids: tuple[UUID, ...],
        buckets: tuple[tuple[datetime, datetime], ...],
    ) -> tuple[RefundTrendRow, ...]:
        values = await self.refunds.trend(organization_id, location_ids, buckets)
        return tuple(RefundTrendRow(value) for value in values)

    async def locations(
        self,
        organization_id: UUID,
        location_ids: tuple[UUID, ...],
        date_from: datetime,
        date_to: datetime,
    ) -> tuple[RefundLocationRow, ...]:
        values = await self.refunds.locations(organization_id, location_ids, date_from, date_to)
        return tuple(RefundLocationRow(value.location_id, value.amount_minor) for value in values)
