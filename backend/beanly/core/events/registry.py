from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from beanly.core.events.envelope import EventEnvelope
from beanly.core.events.serializer import serialize_event_payload
from beanly.modules.inventory.domain.events import (
    InventoryCostUpdated,
    InventoryCountCancelled,
    InventoryCountPosted,
    InventoryTransactionPosted,
    InventoryTransactionReversed,
    InventoryTransferPosted,
    InventoryTransferReversed,
    InventoryValuationChanged,
    InventoryWriteOffPosted,
    InventoryWriteOffReversed,
    StockAdjusted,
    StockWentNegative,
)
from beanly.modules.payments.domain.events import PaymentCompleted
from beanly.modules.purchasing.domain.events import (
    GoodsReceiptCreated,
    GoodsReceiptPosted,
    GoodsReceiptReversed,
    PurchaseOrderCreated,
    PurchaseOrderPartiallyReceived,
    PurchaseOrderReceived,
    PurchaseOrderSubmitted,
    SupplierCreated,
    SupplierReturnCreated,
    SupplierReturnPosted,
    SupplierReturnReversed,
)


@dataclass(frozen=True, slots=True)
class EventSpec:
    name: str
    version: int
    aggregate_type: str | None
    aggregate_id_field: str | None


EVENT_REGISTRY: dict[type[object], EventSpec] = {
    PaymentCompleted: EventSpec("payment.completed", 1, "payment", "payment_id"),
    InventoryTransactionPosted: EventSpec(
        "inventory.transaction_posted", 1, "inventory_transaction", "transaction_id"
    ),
    InventoryTransactionReversed: EventSpec(
        "inventory.transaction_reversed", 1, "inventory_transaction", "transaction_id"
    ),
    StockWentNegative: EventSpec(
        "inventory.stock_went_negative", 1, "inventory_item", "inventory_item_id"
    ),
    StockAdjusted: EventSpec(
        "inventory.stock_adjusted", 1, "inventory_transaction", "transaction_id"
    ),
    InventoryCostUpdated: EventSpec(
        "inventory.cost_updated", 1, "inventory_item", "inventory_item_id"
    ),
    InventoryValuationChanged: EventSpec(
        "inventory.valuation_changed", 1, "inventory_transaction", "transaction_id"
    ),
    InventoryWriteOffPosted: EventSpec(
        "inventory.writeoff_posted", 1, "inventory_writeoff", "writeoff_id"
    ),
    InventoryWriteOffReversed: EventSpec(
        "inventory.writeoff_reversed", 1, "inventory_writeoff", "writeoff_id"
    ),
    InventoryCountPosted: EventSpec(
        "inventory.count_posted", 1, "inventory_count", "inventory_count_id"
    ),
    InventoryCountCancelled: EventSpec(
        "inventory.count_cancelled", 1, "inventory_count", "inventory_count_id"
    ),
    InventoryTransferPosted: EventSpec(
        "inventory.transfer_posted", 1, "inventory_transfer", "transfer_id"
    ),
    InventoryTransferReversed: EventSpec(
        "inventory.transfer_reversed", 1, "inventory_transfer", "transfer_id"
    ),
    SupplierCreated: EventSpec("purchasing.supplier_created", 1, "supplier", "supplier_id"),
    SupplierReturnCreated: EventSpec(
        "purchasing.supplier_return_created", 1, "supplier_return", "supplier_return_id"
    ),
    SupplierReturnPosted: EventSpec(
        "purchasing.supplier_return_posted", 1, "supplier_return", "supplier_return_id"
    ),
    SupplierReturnReversed: EventSpec(
        "purchasing.supplier_return_reversed", 1, "supplier_return", "supplier_return_id"
    ),
    PurchaseOrderCreated: EventSpec(
        "purchasing.order_created", 1, "purchase_order", "purchase_order_id"
    ),
    PurchaseOrderSubmitted: EventSpec(
        "purchasing.order_submitted", 1, "purchase_order", "purchase_order_id"
    ),
    GoodsReceiptCreated: EventSpec(
        "purchasing.goods_receipt_created", 1, "goods_receipt", "goods_receipt_id"
    ),
    GoodsReceiptPosted: EventSpec(
        "purchasing.goods_receipt_posted", 1, "goods_receipt", "goods_receipt_id"
    ),
    GoodsReceiptReversed: EventSpec(
        "purchasing.goods_receipt_reversed", 1, "goods_receipt", "goods_receipt_id"
    ),
    PurchaseOrderPartiallyReceived: EventSpec(
        "purchasing.order_partially_received",
        1,
        "purchase_order",
        "purchase_order_id",
    ),
    PurchaseOrderReceived: EventSpec(
        "purchasing.order_received", 1, "purchase_order", "purchase_order_id"
    ),
}


class UnknownDomainEvent(ValueError):
    pass


def to_envelope(
    event: object,
    *,
    event_id: UUID | None = None,
    occurred_at: datetime | None = None,
) -> EventEnvelope:
    spec = EVENT_REGISTRY.get(type(event))
    if spec is None:
        raise UnknownDomainEvent(f"Unregistered domain event: {type(event).__name__}")
    timestamp = occurred_at or datetime.now(UTC)
    if timestamp.utcoffset() is None:
        raise ValueError("occurred_at must include a timezone")
    organization_id = getattr(event, "organization_id", None)
    aggregate_id = (
        getattr(event, spec.aggregate_id_field) if spec.aggregate_id_field else None
    )
    return EventEnvelope(
        event_id or uuid4(),
        organization_id,
        spec.name,
        spec.version,
        spec.aggregate_type,
        aggregate_id,
        serialize_event_payload(event),
        timestamp.astimezone(UTC),
    )
