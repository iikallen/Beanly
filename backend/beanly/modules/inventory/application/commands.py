from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from beanly.modules.inventory.domain.enums import InventoryTransactionType
from beanly.modules.inventory.domain.value_objects import UnitCode


@dataclass(frozen=True, slots=True)
class CreateWarehouseCommand:
    organization_id: UUID
    user_id: UUID
    location_id: UUID
    name: str


@dataclass(frozen=True, slots=True)
class CreateInventoryItemCommand:
    organization_id: UUID
    name: str
    sku: str | None
    base_unit: UnitCode


@dataclass(frozen=True, slots=True)
class QuantityInput:
    inventory_item_id: UUID
    quantity: Decimal
    unit_code: UnitCode
    unit_cost_amount: Decimal | None = None
    total_cost_amount: Decimal | None = None


@dataclass(frozen=True, slots=True)
class CreateAndPostCommand:
    organization_id: UUID
    user_id: UUID
    warehouse_id: UUID
    type: InventoryTransactionType
    note: str | None
    lines: tuple[QuantityInput, ...]
    idempotency_key: str | None = None
    reference_type: str | None = None
    reference_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class CreateDraftCommand(CreateAndPostCommand):
    pass
