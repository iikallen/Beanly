from uuid import UUID

from beanly.core.events.envelope import EventEnvelope
from beanly.core.events.handlers.registry import EventHandlerRegistry
from beanly.modules.customers.infrastructure.service import CustomerProjectionService


def register_customer_handlers(
    registry: EventHandlerRegistry, service: CustomerProjectionService
) -> None:
    registry.register("refund.completed", 1, _refund(service))


def _organization(envelope: EventEnvelope) -> UUID:
    if envelope.organization_id is None:
        raise ValueError("Customer event must belong to an organization")
    return envelope.organization_id


def _id(envelope: EventEnvelope, key: str) -> UUID:
    value = envelope.payload.get(key)
    if not isinstance(value, str):
        raise ValueError(f"Customer event is missing {key}")
    return UUID(value)


def _refund(service: CustomerProjectionService):
    async def handler(envelope: EventEnvelope) -> None:
        await service.apply_refund(
            _id(envelope, "refund_id"), _organization(envelope), envelope.occurred_at
        )

    return handler
