from datetime import UTC, datetime
from uuid import UUID, uuid4

from beanly.core.events.envelope import EventEnvelope
from beanly.core.events.handlers.registry import EventHandlerRegistry
from beanly.core.observability import metrics
from beanly.modules.integrations.application.ports import FiscalReceiptProjectionPort
from beanly.modules.integrations.domain.entities import IntegrationJob
from beanly.modules.integrations.domain.enums import (
    IntegrationCapability,
    IntegrationJobStatus,
)
from beanly.modules.integrations.infrastructure.db.repositories import (
    SqlAlchemyIntegrationRepository,
)


def register_integration_handlers(
    registry: EventHandlerRegistry,
    repository: SqlAlchemyIntegrationRepository,
    receipts: FiscalReceiptProjectionPort | None = None,
) -> None:
    registry.register("payment.completed", 1, _plan_fiscalization(repository, receipts))
    registry.register(
        "refund.completed", 1, _plan_refund_fiscalization(repository, receipts)
    )


def _plan_fiscalization(
    repository: SqlAlchemyIntegrationRepository,
    receipts: FiscalReceiptProjectionPort | None,
):
    async def handler(envelope: EventEnvelope) -> None:
        organization_id = _organization(envelope)
        payment_id = _id(envelope, "payment_id")
        location_id = _id(envelope, "location_id")
        now = datetime.now(UTC)
        resolver = getattr(receipts, "resolve_fiscal_connection", None)
        if resolver is None:
            connections = await repository.active_connections(
                organization_id, IntegrationCapability.FISCAL, location_id
            )
        else:
            resolved = await resolver(organization_id, "SALE", payment_id)
            connections = [resolved] if resolved is not None else []
        for connection, bound_location_id in connections[:1]:
            if receipts:
                await receipts.ensure_pending_receipt(
                    organization_id=organization_id,
                    location_id=location_id,
                    connection_id=connection.id,
                    provider_code=connection.provider_code,
                    source_type="SALE",
                    source_id=payment_id,
                )
            await repository.add_job(
                IntegrationJob(
                    id=uuid4(),
                    organization_id=organization_id,
                    connection_id=connection.id,
                    location_id=bound_location_id,
                    capability=IntegrationCapability.FISCAL,
                    job_type="FISCALIZE_PAYMENT",
                    source_event_id=envelope.id,
                    source_type="PAYMENT",
                    source_id=payment_id,
                    idempotency_key=f"fiscalize:payment:{payment_id}",
                    status=IntegrationJobStatus.PENDING,
                    available_at=now,
                    attempts=0,
                    locked_by=None,
                    locked_until=None,
                    external_id=None,
                    completed_at=None,
                    dead_lettered_at=None,
                    last_error_code=None,
                    last_error_message=None,
                    created_at=now,
                    updated_at=now,
                )
            )

    return handler


def _plan_refund_fiscalization(
    repository: SqlAlchemyIntegrationRepository,
    receipts: FiscalReceiptProjectionPort | None,
):
    async def handler(envelope: EventEnvelope) -> None:
        organization_id = _organization(envelope)
        refund_id = _id(envelope, "refund_id")
        location_id = _id(envelope, "location_id")
        now = datetime.now(UTC)
        resolver = getattr(receipts, "resolve_fiscal_connection", None)
        if resolver is None:
            connections = await repository.active_connections(
                organization_id, IntegrationCapability.FISCAL, location_id
            )
        else:
            resolved = await resolver(organization_id, "REFUND", refund_id)
            connections = [resolved] if resolved is not None else []
        for connection, bound_location_id in connections[:1]:
            if receipts:
                await receipts.ensure_pending_receipt(
                    organization_id=organization_id,
                    location_id=location_id,
                    connection_id=connection.id,
                    provider_code=connection.provider_code,
                    source_type="REFUND",
                    source_id=refund_id,
                )
            await repository.add_job(
                IntegrationJob(
                    id=uuid4(),
                    organization_id=organization_id,
                    connection_id=connection.id,
                    location_id=bound_location_id,
                    capability=IntegrationCapability.FISCAL,
                    job_type="FISCALIZE_REFUND",
                    source_event_id=envelope.id,
                    source_type="REFUND",
                    source_id=refund_id,
                    idempotency_key=f"fiscalize:refund:{refund_id}",
                    status=IntegrationJobStatus.PENDING,
                    available_at=now,
                    attempts=0,
                    locked_by=None,
                    locked_until=None,
                    external_id=None,
                    completed_at=None,
                    dead_lettered_at=None,
                    last_error_code=None,
                    last_error_message=None,
                    created_at=now,
                    updated_at=now,
                )
            )
            metrics.fiscal_refund_jobs.add(1)

    return handler


def _organization(envelope: EventEnvelope) -> UUID:
    if envelope.organization_id is None:
        raise ValueError("Integration source event must belong to an organization")
    return envelope.organization_id


def _id(envelope: EventEnvelope, key: str) -> UUID:
    value = envelope.payload.get(key)
    if not isinstance(value, str):
        raise ValueError(f"Integration source event is missing {key}")
    return UUID(value)
