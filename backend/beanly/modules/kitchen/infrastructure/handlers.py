from uuid import UUID

from beanly.core.events.envelope import EventEnvelope
from beanly.core.events.handlers.registry import EventHandlerRegistry
from beanly.modules.kitchen.infrastructure.service import KitchenService


def register_kitchen_handlers(registry: EventHandlerRegistry, service: KitchenService) -> None:
    registry.register("payment.completed", 1, _payment(service))


def _payment(service: KitchenService):
    async def handler(envelope: EventEnvelope) -> None:
        if envelope.organization_id is None:
            raise ValueError("Kitchen payment event must belong to an organization")
        await service.project_payment(
            envelope.organization_id,
            _id(envelope, "payment_id"),
            _id(envelope, "order_id"),
        )

    return handler


def _id(envelope: EventEnvelope, key: str) -> UUID:
    value = envelope.payload.get(key)
    if not isinstance(value, str):
        raise ValueError(f"Kitchen payment event is missing {key}")
    return UUID(value)
