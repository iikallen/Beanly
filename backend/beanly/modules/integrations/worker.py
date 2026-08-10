import asyncio
import logging
import socket
from uuid import uuid4

from beanly.core.config.settings import get_settings
from beanly.core.database.session import engine, session_factory
from beanly.core.events.outbox.repositories import OutboxRepository
from beanly.core.events.outbox.writer import OutboxEventSink
from beanly.core.logging.config import configure_logging
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

logger = logging.getLogger(__name__)


async def run_worker() -> None:
    settings = get_settings()
    worker_id = f"{socket.gethostname()[:83]}-{uuid4()}"
    registry = build_provider_registry(settings)
    cipher = FernetSecretCipher(settings.integration_encryption_key_list)
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
        )
        while True:
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
            if not claimed and not inbox:
                await asyncio.sleep(settings.integration_poll_interval_seconds)


async def _main() -> None:
    try:
        await run_worker()
    finally:
        await engine.dispose()


def main() -> None:
    configure_logging()
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
