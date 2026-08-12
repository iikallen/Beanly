from beanly.core.events.envelope import EventEnvelope
from beanly.core.events.handlers.registry import EventHandlerRegistry
from beanly.core.security.audit import SecurityAuditRecorder
from beanly.modules.onboarding.application.onboarding_service import OnboardingService


def register_onboarding_handlers(
    registry: EventHandlerRegistry,
    service: OnboardingService,
    audit: SecurityAuditRecorder | None = None,
) -> None:
    async def payment_completed(envelope: EventEnvelope) -> None:
        organization_id = envelope.organization_id
        if organization_id is None:
            return
        changed = await service.complete_from_payment(organization_id, envelope.occurred_at)
        if changed and audit:
            state = await service.repository.get_state(organization_id)
            await audit.record(
                action="ONBOARDING_COMPLETED",
                resource_type="onboarding_state",
                organization_id=organization_id,
                resource_id=state.id if state else None,
                metadata={"source_event_id": str(envelope.id)},
            )

    registry.register("payment.completed", 1, payment_completed)
