from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from beanly.modules.inventory.application.ports import InventoryRepository


@dataclass(frozen=True, slots=True)
class InventoryHealth:
    total_value: Decimal
    negative_stock_count: int
    active_count_count: int


@dataclass(frozen=True, slots=True)
class NegativeStock:
    item_id: UUID
    location_id: UUID
    name: str
    quantity: Decimal
    unit_code: str


@dataclass(frozen=True, slots=True)
class ActiveCount:
    id: UUID
    location_id: UUID
    number: str


class InventoryReportingService:
    def __init__(self, repository: InventoryRepository) -> None:
        self.repository = repository

    async def inventory_health(
        self, organization_id: UUID, location_ids: tuple[UUID, ...]
    ) -> InventoryHealth:
        total, negative, active_counts = await self.repository.dashboard_inventory_health(
            organization_id, location_ids
        )
        return InventoryHealth(total, negative, active_counts)

    async def negative_stock_items(
        self, organization_id: UUID, location_ids: tuple[UUID, ...], limit: int = 5
    ) -> tuple[NegativeStock, ...]:
        return tuple(
            NegativeStock(*row)
            for row in await self.repository.dashboard_negative_items(
                organization_id, location_ids, limit
            )
        )

    async def inventory_count_status(
        self, organization_id: UUID, location_ids: tuple[UUID, ...]
    ) -> tuple[ActiveCount, ...]:
        return tuple(
            ActiveCount(*row)
            for row in await self.repository.dashboard_active_counts(
                organization_id, location_ids
            )
        )
