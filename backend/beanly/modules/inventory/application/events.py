from typing import Protocol


class EventPublisher(Protocol):
    async def publish(self, event: object) -> None: ...


class NullEventPublisher:
    async def publish(self, event: object) -> None:
        pass


class CollectingEventPublisher:
    def __init__(self) -> None:
        self.events: list[object] = []

    async def publish(self, event: object) -> None:
        self.events.append(event)
