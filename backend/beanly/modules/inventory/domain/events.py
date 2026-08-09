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
