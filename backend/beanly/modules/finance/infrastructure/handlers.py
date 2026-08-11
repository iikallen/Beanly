from uuid import UUID

from beanly.core.events.envelope import EventEnvelope
from beanly.core.events.handlers.registry import EventHandlerRegistry
from beanly.modules.finance.application.projection_service import FinanceProjectionService


def register_finance_handlers(
    registry: EventHandlerRegistry, service: FinanceProjectionService
) -> None:
    registry.register("payment.completed", 1, _payment(service))
    registry.register("refund.completed", 1, _refund(service))
    registry.register("inventory.writeoff_posted", 1, _writeoff(service))
    registry.register("inventory.writeoff_reversed", 1, _writeoff_reversal(service))
    registry.register("inventory.count_posted", 1, _count(service))


def _organization(envelope: EventEnvelope) -> UUID:
    if envelope.organization_id is None:
        raise ValueError("Finance source event must belong to an organization")
    return envelope.organization_id


def _id(envelope: EventEnvelope, key: str) -> UUID:
    value = envelope.payload.get(key)
    if not isinstance(value, str):
        raise ValueError(f"Finance source event is missing {key}")
    return UUID(value)


def _payment(service: FinanceProjectionService):
    async def handler(envelope: EventEnvelope) -> None:
        await service.apply_payment_completed(
            envelope.id,
            _organization(envelope),
            _id(envelope, "payment_id"),
            _id(envelope, "order_id"),
        )

    return handler


def _refund(service: FinanceProjectionService):
    async def handler(envelope: EventEnvelope) -> None:
        await service.apply_refund_completed(
            envelope.id, _organization(envelope), _id(envelope, "refund_id")
        )

    return handler


def _writeoff(service: FinanceProjectionService):
    async def handler(envelope: EventEnvelope) -> None:
        await service.apply_writeoff_posted(
            envelope.id, _organization(envelope), _id(envelope, "writeoff_id")
        )

    return handler


def _writeoff_reversal(service: FinanceProjectionService):
    async def handler(envelope: EventEnvelope) -> None:
        await service.apply_writeoff_reversed(
            envelope.id, _organization(envelope), _id(envelope, "writeoff_id")
        )

    return handler


def _count(service: FinanceProjectionService):
    async def handler(envelope: EventEnvelope) -> None:
        await service.apply_inventory_count_posted(
            envelope.id,
            _organization(envelope),
            _id(envelope, "inventory_count_id"),
        )

    return handler
