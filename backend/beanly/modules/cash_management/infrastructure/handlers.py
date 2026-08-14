from uuid import UUID

from beanly.core.events.envelope import EventEnvelope
from beanly.core.events.handlers.registry import EventHandlerRegistry
from beanly.modules.cash_management.infrastructure.service import CashDrawerService


def register_cash_handlers(registry: EventHandlerRegistry, service: CashDrawerService) -> None:
    registry.register("payment.completed", 1, _payment(service))
    registry.register("refund.completed", 1, _refund(service))
    registry.register("integration.job_succeeded", 1, _job(service, dead=False))
    registry.register("integration.job_dead_lettered", 1, _job(service, dead=True))


def _payment(service: CashDrawerService):
    async def handler(envelope: EventEnvelope) -> None:
        await service.project_payment(_organization(envelope), _id(envelope, "payment_id"))

    return handler


def _refund(service: CashDrawerService):
    async def handler(envelope: EventEnvelope) -> None:
        await service.project_refund(_organization(envelope), _id(envelope, "refund_id"))

    return handler


def _job(service: CashDrawerService, *, dead: bool):
    async def handler(envelope: EventEnvelope) -> None:
        await service.on_integration_job(
            _organization(envelope), _id(envelope, "job_id"), dead=dead
        )

    return handler


def _organization(envelope: EventEnvelope) -> UUID:
    if envelope.organization_id is None:
        raise ValueError("Cash event must belong to an organization")
    return envelope.organization_id


def _id(envelope: EventEnvelope, key: str) -> UUID:
    value = envelope.payload.get(key)
    if not isinstance(value, str):
        raise ValueError(f"Cash event is missing {key}")
    return UUID(value)
