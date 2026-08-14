import asyncio
import logging
import socket
import time
from datetime import UTC, datetime
from uuid import uuid4

from beanly.core.config.settings import get_settings
from beanly.core.database.session import engine, session_factory
from beanly.core.events.outbox.repositories import OutboxRepository
from beanly.core.events.outbox.writer import OutboxEventSink
from beanly.core.logging.config import configure_logging
from beanly.core.observability import (
    configure_telemetry,
    metrics,
    shutdown_telemetry,
)
from beanly.core.runtime import ShutdownSignal
from beanly.modules.customers.infrastructure.db import models as _customer_models  # noqa: F401
from beanly.modules.fiscal.infrastructure.live_repository import (
    SqlAlchemyFiscalLiveRepository,
)
from beanly.modules.integrations.application.job_service import IntegrationJobService
from beanly.modules.integrations.domain.events import IntegrationWebhookProcessed
from beanly.modules.integrations.infrastructure.crypto import FernetSecretCipher
from beanly.modules.integrations.infrastructure.db.repositories import (
    SqlAlchemyIntegrationRepository,
)
from beanly.modules.integrations.infrastructure.providers import build_provider_registry
from beanly.modules.integrations.infrastructure.source_reader import (
    SqlAlchemyIntegrationSourceReader,
)
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.infrastructure.db.repositories import (
    SqlAlchemyOrganizationRepository,
)
from beanly.modules.promotions.infrastructure.db import models as _promotions_models  # noqa: F401

logger = logging.getLogger(__name__)


async def run_worker(shutdown: ShutdownSignal | None = None) -> None:
    settings = get_settings()
    shutdown = shutdown or ShutdownSignal()
    worker_id = f"{socket.gethostname()[:83]}-{uuid4()}"
    registry = build_provider_registry(settings)
    cipher = FernetSecretCipher(settings.integration_encryption_key_list)
    last_stats_at = 0.0
    logger.info("Integration worker started: worker_id=%s", worker_id)
    async with session_factory() as session:
        repository = SqlAlchemyIntegrationRepository(session)
        sink = OutboxEventSink(OutboxRepository(session))
        jobs = IntegrationJobService(
            repository,
            SqlAlchemyIntegrationSourceReader(session),
            registry,
            cipher,
            sink,
            max_attempts=settings.integration_job_max_attempts,
            receipts=SqlAlchemyFiscalLiveRepository(
                session,
                OrganizationService(SqlAlchemyOrganizationRepository(session)),
            ),
        )
        while not shutdown.is_set:
            claimed = await repository.claim_jobs(
                worker_id,
                settings.integration_job_batch_size,
                settings.integration_job_lease_seconds,
            )
            await repository.commit()
            for job in claimed:
                try:
                    await jobs.execute(job, worker_id)
                except Exception:
                    await repository.rollback()
                    logger.exception(
                        "Integration job bookkeeping failed: job_id=%s", job.id
                    )
            if shutdown.is_set:
                continue

            inbox = await repository.claim_inbox(
                worker_id,
                settings.integration_job_batch_size,
                settings.integration_job_lease_seconds,
            )
            await repository.commit()
            for inbox_id in inbox:
                try:
                    organization_id = await repository.mark_inbox_processed(
                        inbox_id, worker_id
                    )
                    await sink.stage(
                        IntegrationWebhookProcessed(inbox_id, organization_id)
                    )
                    await repository.commit()
                except Exception as exc:
                    await repository.rollback()
                    try:
                        await repository.mark_inbox_failed(
                            inbox_id,
                            worker_id,
                            exc,
                            settings.integration_job_max_attempts,
                        )
                        await repository.commit()
                    except Exception:
                        await repository.rollback()
                        logger.exception(
                            "Integration inbox bookkeeping failed: inbox_id=%s",
                            inbox_id,
                        )
            monotonic_now = time.monotonic()
            if monotonic_now - last_stats_at >= 60:
                stats = await repository.queue_stats()
                await repository.rollback()
                oldest_seconds = (
                    max(
                        0,
                        (datetime.now(UTC) - stats.oldest_pending_at).total_seconds(),
                    )
                    if stats.oldest_pending_at
                    else 0
                )
                metrics.set_queue(
                    integration_jobs_pending=stats.pending,
                    integration_oldest_pending_seconds=oldest_seconds,
                    integration_dead_lettered=stats.dead_lettered,
                )
                last_stats_at = monotonic_now
            if not claimed and not inbox:
                await shutdown.wait(settings.integration_poll_interval_seconds)
    logger.info("Integration worker stopped", extra={"worker_id": worker_id})


async def _main() -> None:
    settings = get_settings()
    shutdown = ShutdownSignal()
    shutdown.install()
    configure_telemetry(settings, engine=engine, service_name="beanly-integration-worker")
    try:
        await run_worker(shutdown)
    finally:
        await engine.dispose()
        shutdown_telemetry()


def main() -> None:
    configure_logging("beanly-integration-worker")
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
