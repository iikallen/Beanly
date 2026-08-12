import asyncio
import logging
import socket
import time
from datetime import UTC, datetime
from uuid import uuid4

from beanly.core.config.settings import get_settings
from beanly.core.database.session import engine, session_factory
from beanly.core.events.handlers.registry import EventHandlerRegistry
from beanly.core.events.outbox.dispatcher import OutboxDispatcher
from beanly.core.events.outbox.repositories import OutboxRepository
from beanly.core.logging.config import configure_logging
from beanly.core.observability import configure_telemetry, metrics, shutdown_telemetry
from beanly.core.runtime import ShutdownSignal
from beanly.core.security.audit import SecurityAuditRecorder
from beanly.modules.analytics.application.projection_service import (
    AnalyticsProjectionService,
)
from beanly.modules.analytics.infrastructure.db.repositories import (
    SqlAlchemyAnalyticsRepository,
)
from beanly.modules.analytics.infrastructure.handlers import register_analytics_handlers
from beanly.modules.analytics.infrastructure.source_reader import (
    SqlAlchemyAnalyticsSourceReader,
)
from beanly.modules.finance.application.projection_service import FinanceProjectionService
from beanly.modules.finance.infrastructure.db.repositories import (
    SqlAlchemyFinanceRepository,
)
from beanly.modules.finance.infrastructure.handlers import register_finance_handlers
from beanly.modules.finance.infrastructure.source_reader import (
    SqlAlchemyFinanceSourceReader,
)
from beanly.modules.fiscal.infrastructure.live_repository import (
    SqlAlchemyFiscalLiveRepository,
)
from beanly.modules.integrations.infrastructure.db.repositories import (
    SqlAlchemyIntegrationRepository,
)
from beanly.modules.integrations.infrastructure.handlers import (
    register_integration_handlers,
)
from beanly.modules.onboarding.application.onboarding_service import OnboardingService
from beanly.modules.onboarding.infrastructure.db.repositories import (
    SqlAlchemyOnboardingRepository,
)
from beanly.modules.onboarding.infrastructure.gateway import SqlAlchemyOnboardingGateway
from beanly.modules.onboarding.infrastructure.handlers import register_onboarding_handlers
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.infrastructure.db.repositories import (
    SqlAlchemyOrganizationRepository,
)

logger = logging.getLogger(__name__)


async def run_worker(shutdown: ShutdownSignal | None = None) -> None:
    settings = get_settings()
    shutdown = shutdown or ShutdownSignal()
    worker_id = f"{socket.gethostname()[:83]}-{uuid4()}"
    last_stats_at = 0.0
    logger.info("Outbox worker started: worker_id=%s", worker_id)
    async with session_factory() as session:
        handlers = EventHandlerRegistry()
        register_finance_handlers(
            handlers,
            FinanceProjectionService(
                SqlAlchemyFinanceRepository(session),
                SqlAlchemyFinanceSourceReader(session),
            ),
        )
        register_analytics_handlers(
            handlers,
            AnalyticsProjectionService(
                SqlAlchemyAnalyticsRepository(session),
                SqlAlchemyAnalyticsSourceReader(session),
            ),
        )
        register_integration_handlers(
            handlers,
            SqlAlchemyIntegrationRepository(session),
            SqlAlchemyFiscalLiveRepository(
                session,
                OrganizationService(SqlAlchemyOrganizationRepository(session)),
            ),
        )
        register_onboarding_handlers(
            handlers,
            OnboardingService(
                SqlAlchemyOnboardingRepository(session),
                SqlAlchemyOnboardingGateway(
                    session,
                    live_transport_enabled=settings.live_kz_fiscalization,
                    nkt_configured=settings.nkt_api_key is not None,
                ),
            ),
            SecurityAuditRecorder(session) if settings.audit_enabled else None,
        )
        repository = OutboxRepository(session)
        dispatcher = OutboxDispatcher(
            repository,
            handlers,
            worker_id,
            batch_size=settings.outbox_batch_size,
            lease_seconds=settings.outbox_lease_seconds,
            max_attempts=settings.outbox_max_attempts,
        )
        while not shutdown.is_set:
            processed = await dispatcher.run_once()
            monotonic_now = time.monotonic()
            if monotonic_now - last_stats_at >= 60:
                stats = await repository.queue_stats()
                await repository.rollback()
                logger.info(
                    "Outbox queue status: pending=%s oldest_pending_at=%s dead_lettered=%s",
                    stats.pending,
                    (stats.oldest_pending_at.isoformat() if stats.oldest_pending_at else None),
                    stats.dead_lettered,
                )
                oldest_seconds = (
                    max(0, (datetime.now(UTC) - stats.oldest_pending_at).total_seconds())
                    if stats.oldest_pending_at
                    else 0
                )
                metrics.set_queue(
                    outbox_pending=stats.pending,
                    outbox_oldest_pending_seconds=oldest_seconds,
                    outbox_dead_lettered=stats.dead_lettered,
                )
                last_stats_at = monotonic_now
            if not processed:
                await shutdown.wait(settings.outbox_poll_interval_seconds)
    logger.info("Outbox worker stopped", extra={"worker_id": worker_id})


async def _main() -> None:
    settings = get_settings()
    shutdown = ShutdownSignal()
    shutdown.install()
    configure_telemetry(settings, engine=engine, service_name="beanly-outbox-worker")
    try:
        await run_worker(shutdown)
    finally:
        await engine.dispose()
        shutdown_telemetry()


def main() -> None:
    configure_logging("beanly-outbox-worker")
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
