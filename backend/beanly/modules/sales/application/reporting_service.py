from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from beanly.modules.sales.domain.repositories import SalesRepository


@dataclass(frozen=True, slots=True)
class OpenOperationsSummary:
    open_orders: int
    open_shifts: int


@dataclass(frozen=True, slots=True)
class PricingSummary:
    gross_minor: int
    discount_minor: int
    paid_orders: int


@dataclass(frozen=True, slots=True)
class LocationPricingSummary(PricingSummary):
    location_id: UUID


class SalesReportingService:
    def __init__(self, repository: SalesRepository) -> None:
        self.repository = repository

    async def open_orders_summary(
        self, organization_id: UUID, location_ids: tuple[UUID, ...]
    ) -> int:
        return (await self.operations(organization_id, location_ids)).open_orders

    async def open_shifts_summary(
        self, organization_id: UUID, location_ids: tuple[UUID, ...]
    ) -> int:
        return (await self.operations(organization_id, location_ids)).open_shifts

    async def operations(
        self, organization_id: UUID, location_ids: tuple[UUID, ...]
    ) -> OpenOperationsSummary:
        open_orders, open_shifts = await self.repository.dashboard_open_counts(
            organization_id, location_ids
        )
        return OpenOperationsSummary(open_orders, open_shifts)

    async def pricing_summary(
        self,
        organization_id: UUID,
        location_ids: tuple[UUID, ...],
        date_from: datetime,
        date_to: datetime,
    ) -> PricingSummary:
        return PricingSummary(
            *await self.repository.dashboard_pricing_summary(
                organization_id, location_ids, date_from, date_to
            )
        )

    async def pricing_trend(
        self,
        organization_id: UUID,
        location_ids: tuple[UUID, ...],
        buckets: tuple[tuple[datetime, datetime], ...],
    ) -> tuple[PricingSummary, ...]:
        return tuple(
            PricingSummary(*row)
            for row in await self.repository.dashboard_pricing_trend(
                organization_id, location_ids, buckets
            )
        )

    async def pricing_locations(
        self,
        organization_id: UUID,
        location_ids: tuple[UUID, ...],
        date_from: datetime,
        date_to: datetime,
    ) -> tuple[LocationPricingSummary, ...]:
        return tuple(
            LocationPricingSummary(gross, discount, orders, location_id)
            for location_id, gross, discount, orders in (
                await self.repository.dashboard_pricing_locations(
                    organization_id, location_ids, date_from, date_to
                )
            )
        )
