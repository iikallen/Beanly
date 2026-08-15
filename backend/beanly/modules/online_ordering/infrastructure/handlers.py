from uuid import UUID

from beanly.core.events.envelope import EventEnvelope
from beanly.core.events.handlers.registry import EventHandlerRegistry
from beanly.modules.online_ordering.infrastructure.service import OnlineOrderingService


def register_online_ordering_handlers(
    registry: EventHandlerRegistry, service: OnlineOrderingService
) -> None:
    for event_type in (
        "payment.completed",
        "kitchen.work_started",
        "kitchen.ticket_ready",
        "kitchen.ticket_completed",
    ):
        registry.register(event_type, 1, _handler(service, event_type))


def _handler(service: OnlineOrderingService, event_type: str):
    async def handler(envelope: EventEnvelope) -> None:
        if envelope.organization_id is None:
            return
        order_id = _optional_id(envelope, "order_id")
        ticket_id = _optional_id(envelope, "ticket_id")
        await service.apply_event(
            envelope.organization_id,
            envelope.id,
            event_type,
            order_id,
            ticket_id,
            envelope.occurred_at,
        )

    return handler


def _optional_id(envelope: EventEnvelope, key: str) -> UUID | None:
    value = envelope.payload.get(key)
    return UUID(value) if isinstance(value, str) else None
