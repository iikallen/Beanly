import logging

from beanly.core.events.handlers.registry import EventHandlerRegistry
from beanly.core.events.outbox.repositories import OutboxRepository
from beanly.core.observability import metrics, traced

logger = logging.getLogger(__name__)


class OutboxDispatcher:
    def __init__(
        self,
        repository: OutboxRepository,
        handlers: EventHandlerRegistry,
        worker_id: str,
        *,
        batch_size: int = 50,
        lease_seconds: int = 30,
        max_attempts: int = 12,
    ) -> None:
        if not worker_id or len(worker_id) > 120:
            raise ValueError("worker_id must contain between 1 and 120 characters")
        if min(batch_size, lease_seconds, max_attempts) < 1:
            raise ValueError("Outbox dispatcher settings must be positive")
        self.repository = repository
        self.handlers = handlers
        self.worker_id = worker_id
        self.batch_size = batch_size
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts

    async def run_once(self) -> int:
        try:
            claimed = await self.repository.claim_batch(
                self.worker_id,
                self.batch_size,
                self.lease_seconds,
            )
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise

        for envelope in claimed:
            try:
                with traced(
                    "outbox.event.dispatch",
                    event_name=envelope.event_name,
                    event_id=str(envelope.id),
                ):
                    await self.handlers.dispatch(envelope)
            except Exception as exc:
                logger.exception(
                    "Outbox event handler failed: event_id=%s event_name=%s",
                    envelope.id,
                    envelope.event_name,
                )
                try:
                    # Handler writes and failure bookkeeping must never share a commit.
                    await self.repository.rollback()
                    await self.repository.mark_failed(
                        envelope.id,
                        self.worker_id,
                        exc,
                        self.max_attempts,
                    )
                    await self.repository.commit()
                except Exception:
                    await self.repository.rollback()
                    logger.exception(
                        "Could not persist outbox event failure: event_id=%s",
                        envelope.id,
                    )
                continue
            try:
                await self.repository.mark_processed(envelope.id, self.worker_id)
                await self.repository.commit()
                metrics.outbox_processed.add(1)
                if envelope.event_name == "inventory.stock_went_negative":
                    metrics.negative_stock.add(1)
            except Exception:
                await self.repository.rollback()
                logger.exception(
                    "Could not mark outbox event processed: event_id=%s",
                    envelope.id,
                )
        return len(claimed)
