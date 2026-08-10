from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from beanly.modules.inventory.domain.enums import (
    InventoryCountStatus,
    InventoryCountType,
    InventoryTransactionStatus,
    InventoryTransactionType,
    InventoryTransferStatus,
    WriteOffStatus,
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


@dataclass(frozen=True, slots=True)
class WriteOffReason:
    id: UUID
    organization_id: UUID
    name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class WriteOffLine:
    id: UUID
    writeoff_id: UUID
    inventory_item_id: UUID
    quantity: Decimal
    unit_code: UnitCode
    base_quantity: Decimal
    note: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class WriteOff:
    id: UUID
    organization_id: UUID
    location_id: UUID
    warehouse_id: UUID
    number: str
    reason_id: UUID
    status: WriteOffStatus
    occurred_at: datetime
    note: str | None
    created_by: UUID
    posted_by: UUID | None
    posted_at: datetime | None
    reversed_by: UUID | None
    reversed_at: datetime | None
    inventory_transaction_id: UUID | None
    total_cost_amount: Decimal | None
    created_at: datetime
    updated_at: datetime
    lines: tuple[WriteOffLine, ...] = ()


@dataclass(frozen=True, slots=True)
class InventoryCountLine:
    id: UUID
    inventory_count_id: UUID
    inventory_item_id: UUID
    expected_quantity: Decimal
    counted_quantity: Decimal | None
    current_quantity_before_post: Decimal | None
    difference_quantity: Decimal | None
    difference_cost_amount: Decimal | None
    unit_cost_amount: Decimal | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class InventoryCount:
    id: UUID
    organization_id: UUID
    location_id: UUID
    warehouse_id: UUID
    number: str
    type: InventoryCountType
    status: InventoryCountStatus
    snapshot_at: datetime
    started_by: UUID
    posted_by: UUID | None
    posted_at: datetime | None
    cancelled_by: UUID | None
    cancelled_at: datetime | None
    inventory_transaction_id: UUID | None
    note: str | None
    created_at: datetime
    updated_at: datetime
    lines: tuple[InventoryCountLine, ...] = ()


@dataclass(frozen=True, slots=True)
class InventoryTransferLine:
    id: UUID
    transfer_id: UUID
    inventory_item_id: UUID
    quantity: Decimal
    unit_code: UnitCode
    base_quantity: Decimal
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class InventoryTransfer:
    id: UUID
    organization_id: UUID
    number: str
    source_location_id: UUID
    source_warehouse_id: UUID
    destination_location_id: UUID
    destination_warehouse_id: UUID
    status: InventoryTransferStatus
    occurred_at: datetime
    note: str | None
    created_by: UUID
    posted_by: UUID | None
    posted_at: datetime | None
    reversed_by: UUID | None
    reversed_at: datetime | None
    out_transaction_id: UUID | None
    in_transaction_id: UUID | None
    created_at: datetime
    updated_at: datetime
    lines: tuple[InventoryTransferLine, ...] = ()


@dataclass(frozen=True, slots=True)
class GlobalMovementRow:
    transaction_id: UUID
    warehouse_id: UUID
    location_id: UUID
    inventory_item_id: UUID
    item_name: str
    type: InventoryTransactionType
    quantity_delta: Decimal
    unit_code: UnitCode
    unit_cost_amount: Decimal | None
    total_cost_amount: Decimal | None
    reference_type: str | None
    reference_id: UUID | None
    note: str | None
    posted_at: datetime
