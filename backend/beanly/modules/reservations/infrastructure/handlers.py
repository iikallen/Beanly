from uuid import UUID

from beanly.core.events.envelope import EventEnvelope
from beanly.core.events.handlers.registry import EventHandlerRegistry
from beanly.modules.reservations.infrastructure.service import ReservationService


def register_reservation_handlers(
    registry: EventHandlerRegistry, service: ReservationService
) -> None:
    registry.register("payment.completed", 1, _payment_completed(service))


def _payment_completed(service: ReservationService):
    async def handler(envelope: EventEnvelope) -> None:
        if envelope.organization_id is None:
            return
        order_id = envelope.payload.get("order_id")
        if isinstance(order_id, str):
            await service.apply_payment_completed(envelope.organization_id, UUID(order_id))

    return handler
