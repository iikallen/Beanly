from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from beanly.core.events.envelope import EventEnvelope
from beanly.core.events.serializer import serialize_event_payload
from beanly.modules.cash_management.domain.events import CashDrawerClosed
from beanly.modules.finance.domain.events import (
    CashMovementPosted,
    CashMovementReversed,
    ExpenseCreated,
    ExpensePosted,
    ExpenseReversed,
)
from beanly.modules.integrations.domain.events import (
    IntegrationConnectionActivated,
    IntegrationConnectionCreated,
    IntegrationConnectionDegraded,
    IntegrationConnectionRevoked,
    IntegrationJobDeadLettered,
    IntegrationJobSucceeded,
    IntegrationWebhookProcessed,
)
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
from beanly.modules.kitchen.domain.events import (
    KitchenTicketCompleted,
    KitchenTicketCreated,
    KitchenTicketReady,
    KitchenTicketRecalled,
    KitchenWorkReady,
    KitchenWorkStarted,
)
from beanly.modules.offline_pos.domain.events import (
    OfflineOrderSynced,
    OfflineSessionClosed,
    OfflineSessionStarted,
    OfflineSyncConflict,
    PosDevicePaired,
    PosDeviceRevoked,
)
from beanly.modules.online_ordering.domain.events import (
    OnlineOrderAccepted,
    OnlineOrderCancelled,
    OnlineOrderRejected,
    OnlineOrderSubmitted,
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
from beanly.modules.refunds.domain.events import RefundCompleted


@dataclass(frozen=True, slots=True)
class EventSpec:
    name: str
    version: int
    aggregate_type: str | None
    aggregate_id_field: str | None


EVENT_REGISTRY: dict[type[object], EventSpec] = {
    OnlineOrderSubmitted: EventSpec(
        "online.order_submitted", 1, "online_order", "online_order_id"
    ),
    OnlineOrderAccepted: EventSpec(
        "online.order_accepted", 1, "online_order", "online_order_id"
    ),
    OnlineOrderRejected: EventSpec(
        "online.order_rejected", 1, "online_order", "online_order_id"
    ),
    OnlineOrderCancelled: EventSpec(
        "online.order_cancelled", 1, "online_order", "online_order_id"
    ),
    KitchenTicketCreated: EventSpec(
        "kitchen.ticket_created", 1, "kitchen_ticket", "ticket_id"
    ),
    KitchenWorkStarted: EventSpec(
        "kitchen.work_started", 1, "kitchen_work_item", "work_item_id"
    ),
    KitchenWorkReady: EventSpec(
        "kitchen.work_ready", 1, "kitchen_work_item", "work_item_id"
    ),
    KitchenTicketReady: EventSpec(
        "kitchen.ticket_ready", 1, "kitchen_ticket", "ticket_id"
    ),
    KitchenTicketCompleted: EventSpec(
        "kitchen.ticket_completed", 1, "kitchen_ticket", "ticket_id"
    ),
    KitchenTicketRecalled: EventSpec(
        "kitchen.ticket_recalled", 1, "kitchen_ticket", "ticket_id"
    ),
    CashDrawerClosed: EventSpec("cash.drawer_closed", 1, "cash_drawer", "drawer_id"),
    RefundCompleted: EventSpec("refund.completed", 1, "refund", "refund_id"),
    PosDevicePaired: EventSpec("pos.device_paired", 1, "pos_device", "device_id"),
    PosDeviceRevoked: EventSpec("pos.device_revoked", 1, "pos_device", "device_id"),
    OfflineSessionStarted: EventSpec(
        "pos.offline_session_started", 1, "pos_offline_session", "session_id"
    ),
    OfflineSessionClosed: EventSpec(
        "pos.offline_session_closed", 1, "pos_offline_session", "session_id"
    ),
    OfflineOrderSynced: EventSpec("pos.offline_order_synced", 1, "sales_order", "order_id"),
    OfflineSyncConflict: EventSpec(
        "pos.offline_sync_conflict", 1, "pos_offline_session", "session_id"
    ),
    IntegrationConnectionCreated: EventSpec(
        "integration.connection_created", 1, "integration_connection", "connection_id"
    ),
    IntegrationConnectionActivated: EventSpec(
        "integration.connection_activated", 1, "integration_connection", "connection_id"
    ),
    IntegrationConnectionDegraded: EventSpec(
        "integration.connection_degraded", 1, "integration_connection", "connection_id"
    ),
    IntegrationConnectionRevoked: EventSpec(
        "integration.connection_revoked", 1, "integration_connection", "connection_id"
    ),
    IntegrationJobSucceeded: EventSpec("integration.job_succeeded", 1, "integration_job", "job_id"),
    IntegrationJobDeadLettered: EventSpec(
        "integration.job_dead_lettered", 1, "integration_job", "job_id"
    ),
    IntegrationWebhookProcessed: EventSpec(
        "integration.webhook_processed", 1, "integration_inbox", "inbox_event_id"
    ),
    ExpenseCreated: EventSpec("finance.expense_created", 1, "expense", "expense_id"),
    ExpensePosted: EventSpec("finance.expense_posted", 1, "expense", "expense_id"),
    ExpenseReversed: EventSpec("finance.expense_reversed", 1, "expense", "expense_id"),
    CashMovementPosted: EventSpec(
        "finance.cash_movement_posted", 1, "cash_movement", "cash_movement_id"
    ),
    CashMovementReversed: EventSpec(
        "finance.cash_movement_reversed", 1, "cash_movement", "cash_movement_id"
    ),
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
    aggregate_id = getattr(event, spec.aggregate_id_field) if spec.aggregate_id_field else None
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
