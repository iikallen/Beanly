from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from beanly.modules.inventory.domain.value_objects import UnitCode


@dataclass(frozen=True, slots=True)
class InventoryItemReference:
    id: UUID
    name: str
    base_unit: UnitCode


@dataclass(frozen=True, slots=True)
class WarehouseCostContext:
    warehouse_id: UUID
    location_id: UUID


class InventoryCostPort(Protocol):
    async def get_items(
        self, organization_id: UUID, item_ids: tuple[UUID, ...]
    ) -> dict[UUID, InventoryItemReference]: ...

    async def get_current_costs(
        self, organization_id: UUID, warehouse_id: UUID, item_ids: tuple[UUID, ...]
    ) -> dict[UUID, Decimal]: ...

    async def get_warehouse_context(
        self, organization_id: UUID, warehouse_id: UUID
    ) -> WarehouseCostContext | None: ...


class MenuEventPublisher(Protocol):
    async def publish(self, event: object) -> None: ...


class NullMenuEventPublisher:
    async def publish(self, event: object) -> None:
        pass
