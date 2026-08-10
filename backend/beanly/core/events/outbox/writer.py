from typing import Protocol

from beanly.core.events.outbox.repositories import OutboxRepository
from beanly.core.events.registry import to_envelope


class DomainEventSink(Protocol):
    async def stage(self, event: object) -> None: ...

    async def stage_many(self, events: tuple[object, ...]) -> None: ...


class NullDomainEventSink:
    async def stage(self, event: object) -> None:
        del event

    async def stage_many(self, events: tuple[object, ...]) -> None:
        del events


class CollectingDomainEventSink:
    def __init__(self) -> None:
        self.events: list[object] = []

    async def stage(self, event: object) -> None:
        self.events.append(event)

    async def stage_many(self, events: tuple[object, ...]) -> None:
        self.events.extend(events)


class OutboxEventSink:
    def __init__(self, repository: OutboxRepository) -> None:
        self.repository = repository

    async def stage(self, event: object) -> None:
        await self.repository.add_many((to_envelope(event),))

    async def stage_many(self, events: tuple[object, ...]) -> None:
        await self.repository.add_many(tuple(to_envelope(event) for event in events))
