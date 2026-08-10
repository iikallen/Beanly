from uuid import UUID

from beanly.core.events.envelope import EventEnvelope
from beanly.core.events.handlers.registry import EventHandlerRegistry
from beanly.modules.analytics.application.projection_service import (
    AnalyticsProjectionService,
)


def register_analytics_handlers(
    registry: EventHandlerRegistry, service: AnalyticsProjectionService
) -> None:
    registry.register("payment.completed", 1, _payment(service))
    registry.register(
        "inventory.transaction_posted", 1, _inventory_transaction(service)
    )
    registry.register("finance.expense_posted", 1, _expense(service, reversed_=False))
    registry.register("finance.expense_reversed", 1, _expense(service, reversed_=True))


def _organization(envelope: EventEnvelope) -> UUID:
    if envelope.organization_id is None:
        raise ValueError("Analytics source event must belong to an organization")
    return envelope.organization_id


def _id(envelope: EventEnvelope, key: str) -> UUID:
    value = envelope.payload.get(key)
    if not isinstance(value, str):
        raise ValueError(f"Analytics source event is missing {key}")
    return UUID(value)


def _payment(service: AnalyticsProjectionService):
    async def handler(envelope: EventEnvelope) -> None:
        await service.apply_payment_completed(
            envelope.id,
            _organization(envelope),
            _id(envelope, "payment_id"),
            _id(envelope, "order_id"),
            envelope.occurred_at,
        )

    return handler


def _inventory_transaction(service: AnalyticsProjectionService):
    async def handler(envelope: EventEnvelope) -> None:
        await service.apply_inventory_transaction_posted(
            envelope.id,
            _organization(envelope),
            _id(envelope, "transaction_id"),
            envelope.occurred_at,
        )

    return handler


def _expense(service: AnalyticsProjectionService, *, reversed_: bool):
    async def handler(envelope: EventEnvelope) -> None:
        method = (
            service.apply_expense_reversed
            if reversed_
            else service.apply_expense_posted
        )
        await method(
            envelope.id,
            _organization(envelope),
            _id(envelope, "expense_id"),
            envelope.occurred_at,
        )

    return handler
