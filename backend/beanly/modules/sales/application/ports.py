from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from beanly.modules.inventory.domain.value_objects import UnitCode
from beanly.modules.organizations.domain.entities import TenantContext


@dataclass(frozen=True, slots=True)
class SellableModifierSnapshot:
    group_id: UUID
    group_name: str
    option_id: UUID
    option_name: str
    price_delta_minor: int
    sort_order: int


@dataclass(frozen=True, slots=True)
class SellableComponentSnapshot:
    inventory_item_id: UUID
    inventory_item_name: str
    base_unit: UnitCode
    quantity_per_unit: Decimal


@dataclass(frozen=True, slots=True)
class SellableItemSnapshot:
    product_id: UUID
    product_name: str
    variant_id: UUID
    variant_name: str
    base_price_minor: int
    modifier_price_minor: int
    unit_price_minor: int
    modifiers: tuple[SellableModifierSnapshot, ...]
    components: tuple[SellableComponentSnapshot, ...]


@dataclass(frozen=True, slots=True)
class SalesWarehouse:
    id: UUID
    location_id: UUID
    name: str


class MenuSalesPort(Protocol):
    async def resolve_order_item(
        self,
        context: TenantContext,
        *,
        variant_id: UUID,
        warehouse_id: UUID,
        location_id: UUID,
        selected_option_ids: tuple[UUID, ...],
    ) -> SellableItemSnapshot: ...


class SalesWarehousePort(Protocol):
    async def get_warehouse(
        self, organization_id: UUID, warehouse_id: UUID
    ) -> SalesWarehouse | None: ...

    async def list_warehouses(self, organization_id: UUID) -> tuple[SalesWarehouse, ...]: ...


class SalesEventPublisher(Protocol):
    async def publish(self, event: object) -> None: ...


class NullSalesEventPublisher:
    async def publish(self, event: object) -> None:
        pass
