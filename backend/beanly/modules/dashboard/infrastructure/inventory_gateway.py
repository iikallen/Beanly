from uuid import UUID

from beanly.modules.dashboard.application.dto import (
    ActiveInventoryCount,
    InventoryHealth,
    NegativeStockItem,
)
from beanly.modules.inventory.application.reporting_service import (
    InventoryReportingService,
)


class InventoryDashboardGateway:
    def __init__(self, reporting: InventoryReportingService) -> None:
        self.reporting = reporting

    async def health(
        self, organization_id: UUID, location_ids: tuple[UUID, ...]
    ) -> InventoryHealth:
        value = await self.reporting.inventory_health(organization_id, location_ids)
        return InventoryHealth(
            value.total_value, value.negative_stock_count, value.active_count_count
        )

    async def negative_items(
        self, organization_id: UUID, location_ids: tuple[UUID, ...], limit: int
    ) -> tuple[NegativeStockItem, ...]:
        return tuple(
            NegativeStockItem(
                value.item_id,
                value.location_id,
                value.name,
                value.quantity,
                value.unit_code,
            )
            for value in await self.reporting.negative_stock_items(
                organization_id, location_ids, limit
            )
        )

    async def active_counts(
        self, organization_id: UUID, location_ids: tuple[UUID, ...]
    ) -> tuple[ActiveInventoryCount, ...]:
        return tuple(
            ActiveInventoryCount(value.id, value.location_id, value.number)
            for value in await self.reporting.inventory_count_status(
                organization_id, location_ids
            )
        )
