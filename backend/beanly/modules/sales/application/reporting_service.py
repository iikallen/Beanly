from dataclasses import dataclass
from uuid import UUID

from beanly.modules.sales.domain.repositories import SalesRepository


@dataclass(frozen=True, slots=True)
class OpenOperationsSummary:
    open_orders: int
    open_shifts: int


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
