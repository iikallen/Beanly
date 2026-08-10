import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable

from beanly.core.events.envelope import EventEnvelope

logger = logging.getLogger(__name__)
EventHandler = Callable[[EventEnvelope], Awaitable[None]]


class EventHandlerRegistry:
    """Handlers are at-least-once consumers and therefore must be idempotent."""

    def __init__(self) -> None:
        self._handlers: dict[tuple[str, int], list[EventHandler]] = defaultdict(list)

    def register(self, event_name: str, event_version: int, handler: EventHandler) -> None:
        self._handlers[(event_name, event_version)].append(handler)

    async def dispatch(self, envelope: EventEnvelope) -> None:
        handlers = self._handlers.get(
            (envelope.event_name, envelope.event_version), ()
        )
        if not handlers:
            logger.debug(
                "Outbox event has no registered handlers",
                extra={
                    "event_id": str(envelope.id),
                    "event_name": envelope.event_name,
                    "event_version": envelope.event_version,
                },
            )
            return
        for handler in handlers:
            await handler(envelope)
