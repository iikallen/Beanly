from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RefundLocationSummary:
    location_id: UUID
    amount_minor: int


class RefundReportingRepository(Protocol):
    async def dashboard_summary(
        self,
        organization_id: UUID,
        location_ids: tuple[UUID, ...],
        date_from: datetime,
        date_to: datetime,
    ) -> int: ...

    async def dashboard_trend(
        self,
        organization_id: UUID,
        location_ids: tuple[UUID, ...],
        buckets: tuple[tuple[datetime, datetime], ...],
    ) -> tuple[int, ...]: ...

    async def dashboard_locations(
        self,
        organization_id: UUID,
        location_ids: tuple[UUID, ...],
        date_from: datetime,
        date_to: datetime,
    ) -> tuple[tuple[UUID, int], ...]: ...


class RefundReportingService:
    def __init__(self, repository: RefundReportingRepository) -> None:
        self.repository = repository

    async def summary(
        self,
        organization_id: UUID,
        location_ids: tuple[UUID, ...],
        date_from: datetime,
        date_to: datetime,
    ) -> int:
        return await self.repository.dashboard_summary(
            organization_id, location_ids, date_from, date_to
        )

    async def trend(
        self,
        organization_id: UUID,
        location_ids: tuple[UUID, ...],
        buckets: tuple[tuple[datetime, datetime], ...],
    ) -> tuple[int, ...]:
        return await self.repository.dashboard_trend(organization_id, location_ids, buckets)

    async def locations(
        self,
        organization_id: UUID,
        location_ids: tuple[UUID, ...],
        date_from: datetime,
        date_to: datetime,
    ) -> tuple[RefundLocationSummary, ...]:
        values = await self.repository.dashboard_locations(
            organization_id, location_ids, date_from, date_to
        )
        return tuple(RefundLocationSummary(*value) for value in values)
