from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True, slots=True)
class InventoryTransactionPosted:
    organization_id: UUID
    transaction_id: UUID


@dataclass(frozen=True, slots=True)
class InventoryTransactionReversed:
    organization_id: UUID
    transaction_id: UUID
    reversal_transaction_id: UUID


@dataclass(frozen=True, slots=True)
class StockWentNegative:
    organization_id: UUID
    warehouse_id: UUID
    inventory_item_id: UUID
    quantity: Decimal


@dataclass(frozen=True, slots=True)
class StockAdjusted:
    organization_id: UUID
    transaction_id: UUID


@dataclass(frozen=True, slots=True)
class InventoryCostUpdated:
    organization_id: UUID
    warehouse_id: UUID
    inventory_item_id: UUID
    average_unit_cost: Decimal


@dataclass(frozen=True, slots=True)
class InventoryValuationChanged:
    organization_id: UUID
    warehouse_id: UUID
    transaction_id: UUID


@dataclass(frozen=True, slots=True)
class InventoryWriteOffPosted:
    organization_id: UUID
    writeoff_id: UUID
    inventory_transaction_id: UUID
    reason_id: UUID
    total_cost_amount: Decimal


@dataclass(frozen=True, slots=True)
class InventoryWriteOffReversed:
    organization_id: UUID
    writeoff_id: UUID
    inventory_transaction_id: UUID
    reversal_transaction_id: UUID


@dataclass(frozen=True, slots=True)
class InventoryCountPosted:
    organization_id: UUID
    inventory_count_id: UUID
    inventory_transaction_id: UUID | None


@dataclass(frozen=True, slots=True)
class InventoryCountCancelled:
    organization_id: UUID
    inventory_count_id: UUID


@dataclass(frozen=True, slots=True)
class InventoryTransferPosted:
    organization_id: UUID
    transfer_id: UUID
    out_transaction_id: UUID
    in_transaction_id: UUID


@dataclass(frozen=True, slots=True)
class InventoryTransferReversed:
    organization_id: UUID
    transfer_id: UUID
    out_reversal_transaction_id: UUID
    in_reversal_transaction_id: UUID
