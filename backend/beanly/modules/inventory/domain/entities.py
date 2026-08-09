from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from beanly.modules.inventory.domain.enums import (
    InventoryTransactionStatus,
    InventoryTransactionType,
)
from beanly.modules.inventory.domain.value_objects import UnitCode


@dataclass(frozen=True, slots=True)
class Warehouse:
    id: UUID
    organization_id: UUID
    location_id: UUID
    name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class InventoryItem:
    id: UUID
    organization_id: UUID
    name: str
    sku: str | None
    base_unit: UnitCode
    is_active: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class StockRow:
    warehouse_id: UUID
    inventory_item_id: UUID
    item_name: str
    sku: str | None
    quantity: Decimal
    base_unit: UnitCode
    average_unit_cost: Decimal | None
    inventory_value: Decimal | None
    updated_at: datetime | None


@dataclass(frozen=True, slots=True)
class StockBalance:
    id: UUID
    organization_id: UUID
    location_id: UUID
    warehouse_id: UUID
    inventory_item_id: UUID
    quantity: Decimal
    average_unit_cost: Decimal
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class InventoryTransaction:
    id: UUID
    organization_id: UUID
    location_id: UUID
    warehouse_id: UUID
    type: InventoryTransactionType
    status: InventoryTransactionStatus
    reference_type: str | None
    reference_id: UUID | None
    idempotency_key: str | None
    note: str | None
    created_by: UUID
    created_at: datetime
    posted_at: datetime | None
    reversal_of_id: UUID | None


@dataclass(frozen=True, slots=True)
class InventoryTransactionLine:
    id: UUID
    transaction_id: UUID
    inventory_item_id: UUID
    quantity_delta: Decimal
    requested_unit_cost_amount: Decimal | None
    requested_total_cost_amount: Decimal | None
    unit_cost_amount: Decimal | None
    total_cost_amount: Decimal | None
    quantity_after: Decimal | None
    average_unit_cost_after: Decimal | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class TransactionDetail:
    transaction: InventoryTransaction
    lines: tuple[InventoryTransactionLine, ...]


@dataclass(frozen=True, slots=True)
class MovementRow:
    transaction_id: UUID
    type: InventoryTransactionType
    status: InventoryTransactionStatus
    quantity_delta: Decimal
    unit_cost_amount: Decimal | None
    total_cost_amount: Decimal | None
    quantity_after: Decimal | None
    average_unit_cost_after: Decimal | None
    reference_type: str | None
    reference_id: UUID | None
    note: str | None
    posted_at: datetime | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class InventoryValuation:
    currency_code: str
    total_inventory_value: Decimal
    items: tuple[StockRow, ...]
