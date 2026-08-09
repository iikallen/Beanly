from decimal import Decimal
from uuid import UUID

from beanly.modules.inventory.application.ports import InventoryRepository
from beanly.modules.menu.application.ports import (
    InventoryItemReference,
    WarehouseCostContext,
)


class InventoryApplicationGateway:
    def __init__(self, repository: InventoryRepository) -> None:
        self.repository = repository

    async def get_items(
        self, organization_id: UUID, item_ids: tuple[UUID, ...]
    ) -> dict[UUID, InventoryItemReference]:
        values = await self.repository.get_items_by_ids(organization_id, item_ids)
        return {
            value.id: InventoryItemReference(value.id, value.name, value.base_unit)
            for value in values
        }

    async def get_current_costs(
        self, organization_id: UUID, warehouse_id: UUID, item_ids: tuple[UUID, ...]
    ) -> dict[UUID, Decimal]:
        return await self.repository.get_current_costs(organization_id, warehouse_id, item_ids)

    async def get_warehouse_context(
        self, organization_id: UUID, warehouse_id: UUID
    ) -> WarehouseCostContext | None:
        warehouse = await self.repository.get_warehouse(organization_id, warehouse_id)
        if warehouse is None:
            return None
        return WarehouseCostContext(warehouse.id, warehouse.location_id)
