import logging

from beanly.core.events.envelope import EventEnvelope

logger = logging.getLogger(__name__)


async def log_event(envelope: EventEnvelope) -> None:
    logger.info(
        "Handled outbox event",
        extra={
            "event_id": str(envelope.id),
            "event_name": envelope.event_name,
            "event_version": envelope.event_version,
        },
    )
