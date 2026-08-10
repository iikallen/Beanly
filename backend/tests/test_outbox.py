from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from beanly.core.events.registry import EVENT_REGISTRY, UnknownDomainEvent, to_envelope
from beanly.core.events.serializer import (
    EventSerializationError,
    serialize_event_payload,
)
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


def _event_contracts() -> tuple[tuple[object, str, str, UUID], ...]:
    organization_id = uuid4()
    location_id = uuid4()
    payment_id = uuid4()
    order_id = uuid4()
    transaction_id = uuid4()
    reversal_id = uuid4()
    warehouse_id = uuid4()
    item_id = uuid4()
    supplier_id = uuid4()
    purchase_order_id = uuid4()
    receipt_id = uuid4()
    writeoff_id = uuid4()
    count_id = uuid4()
    transfer_id = uuid4()
    in_transaction_id = uuid4()
    supplier_return_id = uuid4()
    expense_id = uuid4()
    cash_movement_id = uuid4()
    connection_id = uuid4()
    integration_job_id = uuid4()
    inbox_event_id = uuid4()
    return (
        (
            IntegrationConnectionCreated(connection_id, organization_id),
            "integration.connection_created",
            "integration_connection",
            connection_id,
        ),
        (
            IntegrationConnectionActivated(connection_id, organization_id),
            "integration.connection_activated",
            "integration_connection",
            connection_id,
        ),
        (
            IntegrationConnectionDegraded(connection_id, organization_id),
            "integration.connection_degraded",
            "integration_connection",
            connection_id,
        ),
        (
            IntegrationConnectionRevoked(connection_id, organization_id),
            "integration.connection_revoked",
            "integration_connection",
            connection_id,
        ),
        (
            IntegrationJobSucceeded(integration_job_id, organization_id),
            "integration.job_succeeded",
            "integration_job",
            integration_job_id,
        ),
        (
            IntegrationJobDeadLettered(integration_job_id, organization_id),
            "integration.job_dead_lettered",
            "integration_job",
            integration_job_id,
        ),
        (
            IntegrationWebhookProcessed(inbox_event_id, organization_id),
            "integration.webhook_processed",
            "integration_inbox",
            inbox_event_id,
        ),
        (
            ExpenseCreated(organization_id, expense_id),
            "finance.expense_created",
            "expense",
            expense_id,
        ),
        (
            ExpensePosted(organization_id, expense_id),
            "finance.expense_posted",
            "expense",
            expense_id,
        ),
        (
            ExpenseReversed(organization_id, expense_id),
            "finance.expense_reversed",
            "expense",
            expense_id,
        ),
        (
            CashMovementPosted(organization_id, cash_movement_id),
            "finance.cash_movement_posted",
            "cash_movement",
            cash_movement_id,
        ),
        (
            CashMovementReversed(organization_id, cash_movement_id),
            "finance.cash_movement_reversed",
            "cash_movement",
            cash_movement_id,
        ),
        (
            PaymentCompleted(
                payment_id, order_id, organization_id, location_id, 260000
            ),
            "payment.completed",
            "payment",
            payment_id,
        ),
        (
            InventoryTransactionPosted(organization_id, transaction_id),
            "inventory.transaction_posted",
            "inventory_transaction",
            transaction_id,
        ),
        (
            InventoryTransactionReversed(
                organization_id, transaction_id, reversal_id
            ),
            "inventory.transaction_reversed",
            "inventory_transaction",
            transaction_id,
        ),
        (
            StockWentNegative(
                organization_id, warehouse_id, item_id, Decimal("-18.000000")
            ),
            "inventory.stock_went_negative",
            "inventory_item",
            item_id,
        ),
        (
            StockAdjusted(organization_id, transaction_id),
            "inventory.stock_adjusted",
            "inventory_transaction",
            transaction_id,
        ),
        (
            InventoryCostUpdated(
                organization_id, warehouse_id, item_id, Decimal("8.500000")
            ),
            "inventory.cost_updated",
            "inventory_item",
            item_id,
        ),
        (
            InventoryValuationChanged(
                organization_id, warehouse_id, transaction_id
            ),
            "inventory.valuation_changed",
            "inventory_transaction",
            transaction_id,
        ),
        (
            InventoryWriteOffPosted(
                organization_id,
                writeoff_id,
                transaction_id,
                uuid4(),
                Decimal("42.000000"),
            ),
            "inventory.writeoff_posted",
            "inventory_writeoff",
            writeoff_id,
        ),
        (
            InventoryWriteOffReversed(
                organization_id, writeoff_id, transaction_id, reversal_id
            ),
            "inventory.writeoff_reversed",
            "inventory_writeoff",
            writeoff_id,
        ),
        (
            InventoryCountPosted(organization_id, count_id, transaction_id),
            "inventory.count_posted",
            "inventory_count",
            count_id,
        ),
        (
            InventoryCountCancelled(organization_id, count_id),
            "inventory.count_cancelled",
            "inventory_count",
            count_id,
        ),
        (
            InventoryTransferPosted(
                organization_id, transfer_id, transaction_id, in_transaction_id
            ),
            "inventory.transfer_posted",
            "inventory_transfer",
            transfer_id,
        ),
        (
            InventoryTransferReversed(
                organization_id, transfer_id, reversal_id, uuid4()
            ),
            "inventory.transfer_reversed",
            "inventory_transfer",
            transfer_id,
        ),
        (
            SupplierCreated(organization_id, supplier_id),
            "purchasing.supplier_created",
            "supplier",
            supplier_id,
        ),
        (
            SupplierReturnCreated(organization_id, supplier_return_id),
            "purchasing.supplier_return_created",
            "supplier_return",
            supplier_return_id,
        ),
        (
            SupplierReturnPosted(
                organization_id, supplier_return_id, transaction_id
            ),
            "purchasing.supplier_return_posted",
            "supplier_return",
            supplier_return_id,
        ),
        (
            SupplierReturnReversed(organization_id, supplier_return_id),
            "purchasing.supplier_return_reversed",
            "supplier_return",
            supplier_return_id,
        ),
        (
            PurchaseOrderCreated(organization_id, purchase_order_id),
            "purchasing.order_created",
            "purchase_order",
            purchase_order_id,
        ),
        (
            PurchaseOrderSubmitted(organization_id, purchase_order_id),
            "purchasing.order_submitted",
            "purchase_order",
            purchase_order_id,
        ),
        (
            GoodsReceiptCreated(organization_id, receipt_id),
            "purchasing.goods_receipt_created",
            "goods_receipt",
            receipt_id,
        ),
        (
            GoodsReceiptPosted(organization_id, receipt_id, transaction_id),
            "purchasing.goods_receipt_posted",
            "goods_receipt",
            receipt_id,
        ),
        (
            GoodsReceiptReversed(organization_id, receipt_id),
            "purchasing.goods_receipt_reversed",
            "goods_receipt",
            receipt_id,
        ),
        (
            PurchaseOrderPartiallyReceived(organization_id, purchase_order_id),
            "purchasing.order_partially_received",
            "purchase_order",
            purchase_order_id,
        ),
        (
            PurchaseOrderReceived(organization_id, purchase_order_id),
            "purchasing.order_received",
            "purchase_order",
            purchase_order_id,
        ),
    )


def test_all_domain_events_have_exact_stable_v1_contracts() -> None:
    contracts = _event_contracts()
    assert set(EVENT_REGISTRY) == {type(event) for event, *_ in contracts}
    occurred_at = datetime(2026, 8, 10, 3, 4, 5, tzinfo=UTC)
    event_id = uuid4()
    for event, name, aggregate_type, aggregate_id in contracts:
        envelope = to_envelope(
            event, event_id=event_id, occurred_at=occurred_at
        )
        assert (
            envelope.id,
            envelope.event_name,
            envelope.event_version,
            envelope.aggregate_type,
            envelope.aggregate_id,
            envelope.occurred_at,
        ) == (event_id, name, 1, aggregate_type, aggregate_id, occurred_at)
        assert envelope.payload == serialize_event_payload(event)
        assert f"{envelope.event_name}.v{envelope.event_version}" == f"{name}.v1"

    payment_event = next(
        event for event, name, *_ in contracts if name == "payment.completed"
    )
    payment = to_envelope(payment_event, occurred_at=occurred_at)
    assert payment.payload == {
        "payment_id": str(payment_event.payment_id),
        "order_id": str(payment_event.order_id),
        "organization_id": str(payment_event.organization_id),
        "location_id": str(payment_event.location_id),
        "amount_minor": 260000,
    }


@dataclass(frozen=True, slots=True)
class _NestedEvent:
    identifier: UUID
    amount: Decimal
    happened_at: datetime
    values: tuple[object, ...]
    metadata: dict[str, object]


def test_event_serializer_is_lossless_nested_and_fail_fast() -> None:
    identifier = uuid4()
    happened_at = datetime(
        2026, 8, 10, 8, 30, tzinfo=timezone(timedelta(hours=5))
    )
    event = _NestedEvent(
        identifier,
        Decimal("8.500000"),
        happened_at,
        (1, True, None, Decimal("0.100000")),
        {"ids": [identifier], "enabled": False},
    )
    assert serialize_event_payload(event) == {
        "identifier": str(identifier),
        "amount": "8.500000",
        "happened_at": "2026-08-10T03:30:00Z",
        "values": [1, True, None, "0.100000"],
        "metadata": {"ids": [str(identifier)], "enabled": False},
    }

    for invalid in (
        _NestedEvent(identifier, Decimal("NaN"), happened_at, (), {}),
        _NestedEvent(identifier, Decimal(1), datetime(2026, 8, 10), (), {}),
        _NestedEvent(identifier, Decimal(1), happened_at, (1.5,), {}),
        _NestedEvent(identifier, Decimal(1), happened_at, (object(),), {}),
        _NestedEvent(identifier, Decimal(1), happened_at, (), {1: "bad"}),
    ):
        with pytest.raises(EventSerializationError):
            serialize_event_payload(invalid)

    with pytest.raises(UnknownDomainEvent):
        to_envelope(_NestedEvent(identifier, Decimal(1), happened_at, (), {}))
