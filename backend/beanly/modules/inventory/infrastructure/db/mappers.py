from beanly.modules.inventory.domain.entities import (
    InventoryItem,
    InventoryTransaction,
    InventoryTransactionLine,
    Warehouse,
)
from beanly.modules.inventory.domain.enums import (
    InventoryTransactionStatus,
    InventoryTransactionType,
)
from beanly.modules.inventory.domain.value_objects import UnitCode
from beanly.modules.inventory.infrastructure.db.models import (
    InventoryItemModel,
    InventoryTransactionLineModel,
    InventoryTransactionModel,
    WarehouseModel,
)


def to_warehouse(model: WarehouseModel) -> Warehouse:
    return Warehouse(
        model.id,
        model.organization_id,
        model.location_id,
        model.name,
        model.is_active,
        model.created_at,
        model.updated_at,
    )


def to_item(model: InventoryItemModel) -> InventoryItem:
    return InventoryItem(
        model.id,
        model.organization_id,
        model.name,
        model.sku,
        UnitCode(model.base_unit),
        model.is_active,
        model.created_at,
        model.updated_at,
    )


def to_transaction(model: InventoryTransactionModel) -> InventoryTransaction:
    return InventoryTransaction(
        model.id,
        model.organization_id,
        model.location_id,
        model.warehouse_id,
        InventoryTransactionType(model.type),
        InventoryTransactionStatus(model.status),
        model.reference_type,
        model.reference_id,
        model.idempotency_key,
        model.note,
        model.created_by,
        model.created_at,
        model.posted_at,
        model.reversal_of_id,
    )


def to_line(model: InventoryTransactionLineModel) -> InventoryTransactionLine:
    return InventoryTransactionLine(
        model.id,
        model.transaction_id,
        model.inventory_item_id,
        model.quantity_delta,
        model.requested_unit_cost_amount,
        model.requested_total_cost_amount,
        model.unit_cost_amount,
        model.total_cost_amount,
        model.quantity_after,
        model.average_unit_cost_after,
        model.created_at,
    )
