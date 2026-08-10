import asyncio
import logging
import socket
import time
from uuid import uuid4

from beanly.core.config.settings import get_settings
from beanly.core.database.session import engine, session_factory
from beanly.core.events.handlers.registry import EventHandlerRegistry
from beanly.core.events.outbox.dispatcher import OutboxDispatcher
from beanly.core.events.outbox.repositories import OutboxRepository
from beanly.core.logging.config import configure_logging
from beanly.modules.finance.application.projection_service import FinanceProjectionService
from beanly.modules.finance.infrastructure.db.repositories import (
    SqlAlchemyFinanceRepository,
)
from beanly.modules.finance.infrastructure.handlers import register_finance_handlers
from beanly.modules.finance.infrastructure.source_reader import (
    SqlAlchemyFinanceSourceReader,
)

logger = logging.getLogger(__name__)


async def run_worker() -> None:
    settings = get_settings()
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
        repository = OutboxRepository(session)
        dispatcher = OutboxDispatcher(
            repository,
            handlers,
            worker_id,
            batch_size=settings.outbox_batch_size,
            lease_seconds=settings.outbox_lease_seconds,
            max_attempts=settings.outbox_max_attempts,
        )
        while True:
            processed = await dispatcher.run_once()
            monotonic_now = time.monotonic()
            if monotonic_now - last_stats_at >= 60:
                stats = await repository.queue_stats()
                await repository.rollback()
                logger.info(
                    "Outbox queue status: pending=%s oldest_pending_at=%s "
                    "dead_lettered=%s",
                    stats.pending,
                    (
                        stats.oldest_pending_at.isoformat()
                        if stats.oldest_pending_at
                        else None
                    ),
                    stats.dead_lettered,
                )
                last_stats_at = monotonic_now
            if not processed:
                await asyncio.sleep(settings.outbox_poll_interval_seconds)


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
