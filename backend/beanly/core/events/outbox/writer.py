from datetime import datetime
from typing import Protocol

from beanly.core.events.outbox.repositories import OutboxRepository
from beanly.core.events.registry import to_envelope


class DomainEventSink(Protocol):
    async def stage(self, event: object, *, occurred_at: datetime | None = None) -> None: ...

    async def stage_many(
        self, events: tuple[object, ...], *, occurred_at: datetime | None = None
    ) -> None: ...


class NullDomainEventSink:
    async def stage(self, event: object, *, occurred_at: datetime | None = None) -> None:
        del event
        del occurred_at

    async def stage_many(
        self, events: tuple[object, ...], *, occurred_at: datetime | None = None
    ) -> None:
        del events
        del occurred_at


class CollectingDomainEventSink:
    def __init__(self) -> None:
        self.events: list[object] = []

    async def stage(self, event: object, *, occurred_at: datetime | None = None) -> None:
        self.events.append(event)
        del occurred_at

    async def stage_many(
        self, events: tuple[object, ...], *, occurred_at: datetime | None = None
    ) -> None:
        self.events.extend(events)
        del occurred_at


class OutboxEventSink:
    def __init__(self, repository: OutboxRepository) -> None:
        self.repository = repository

    async def stage(self, event: object, *, occurred_at: datetime | None = None) -> None:
        await self.repository.add_many((to_envelope(event, occurred_at=occurred_at),))

    async def stage_many(
        self, events: tuple[object, ...], *, occurred_at: datetime | None = None
    ) -> None:
        await self.repository.add_many(
            tuple(to_envelope(event, occurred_at=occurred_at) for event in events)
        )
