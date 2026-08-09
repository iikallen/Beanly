from uuid import UUID

from beanly.modules.inventory.application.ports import InventoryRepository
from beanly.modules.sales.application.ports import SalesWarehouse


class InventorySalesGateway:
    def __init__(self, repository: InventoryRepository) -> None:
        self.repository = repository

    async def get_warehouse(
        self, organization_id: UUID, warehouse_id: UUID
    ) -> SalesWarehouse | None:
        value = await self.repository.get_warehouse(organization_id, warehouse_id)
        return SalesWarehouse(value.id, value.location_id, value.name) if value else None

    async def list_warehouses(self, organization_id: UUID) -> tuple[SalesWarehouse, ...]:
        values = await self.repository.list_warehouses(organization_id)
        return tuple(
            SalesWarehouse(value.id, value.location_id, value.name)
            for value in values
            if value.is_active
        )
