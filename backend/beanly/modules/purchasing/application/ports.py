from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from beanly.modules.organizations.domain.entities import TenantContext


@dataclass(frozen=True, slots=True)
class InventoryItemSnapshot:
    id: UUID
    base_unit: str


@dataclass(frozen=True, slots=True)
class InventoryResources:
    warehouse_id: UUID
    location_id: UUID
    items: dict[UUID, InventoryItemSnapshot]


@dataclass(frozen=True, slots=True)
class PurchaseStockLine:
    inventory_item_id: UUID
    base_quantity: Decimal
    base_unit: str
    total_cost_amount: Decimal


@dataclass(frozen=True, slots=True)
class StagedInventoryResult:
    transaction_id: UUID
    events: tuple[object, ...]


class InventoryGateway(Protocol):
    async def validate_resources(
        self,
        context: TenantContext,
        warehouse_id: UUID,
        item_ids: tuple[UUID, ...],
    ) -> InventoryResources: ...

    async def receive_purchase(
        self,
        context: TenantContext,
        receipt_id: UUID,
        warehouse_id: UUID,
        note: str,
        lines: tuple[PurchaseStockLine, ...],
    ) -> StagedInventoryResult: ...

    async def reverse_purchase(
        self,
        context: TenantContext,
        transaction_id: UUID,
        receipt_id: UUID,
    ) -> StagedInventoryResult: ...

    async def publish(self, events: tuple[object, ...]) -> None: ...


class EventPublisher(Protocol):
    async def publish(self, event: object) -> None: ...


class NullEventPublisher:
    async def publish(self, event: object) -> None:
        del event
