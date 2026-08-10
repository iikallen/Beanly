from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from beanly.core.events.envelope import EventEnvelope
from beanly.core.events.outbox.models import OutboxEventModel


class OutboxLeaseLost(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class OutboxStats:
    pending: int
    oldest_pending_at: datetime | None
    dead_lettered: int


class OutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_many(self, envelopes: tuple[EventEnvelope, ...]) -> None:
        self.session.add_all(
            OutboxEventModel(
                id=value.id,
                organization_id=value.organization_id,
                event_name=value.event_name,
                event_version=value.event_version,
                aggregate_type=value.aggregate_type,
                aggregate_id=value.aggregate_id,
                payload=value.payload,
                occurred_at=value.occurred_at,
                available_at=value.occurred_at,
                attempts=0,
                created_at=value.occurred_at,
            )
            for value in envelopes
        )
        if envelopes:
            await self.session.flush()

    async def claim_batch(
        self,
        worker_id: str,
        batch_size: int,
        lease_seconds: int,
        *,
        now: datetime | None = None,
    ) -> tuple[EventEnvelope, ...]:
        timestamp = _now(now)
        models = await self.session.scalars(
            select(OutboxEventModel)
            .where(
                OutboxEventModel.processed_at.is_(None),
                OutboxEventModel.dead_lettered_at.is_(None),
                OutboxEventModel.available_at <= timestamp,
                or_(
                    OutboxEventModel.locked_until.is_(None),
                    OutboxEventModel.locked_until < timestamp,
                ),
            )
            .order_by(OutboxEventModel.occurred_at, OutboxEventModel.id)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        lease_until = timestamp + timedelta(seconds=lease_seconds)
        claimed = tuple(models)
        for model in claimed:
            model.locked_by = worker_id
            model.locked_until = lease_until
        if claimed:
            await self.session.flush()
        return tuple(_envelope(model) for model in claimed)

    async def mark_processed(
        self,
        event_id: UUID,
        worker_id: str,
        *,
        now: datetime | None = None,
    ) -> None:
        model = await self._owned(event_id, worker_id)
        model.processed_at = _now(now)
        model.locked_by = None
        model.locked_until = None
        model.last_error = None
        await self.session.flush()

    async def mark_failed(
        self,
        event_id: UUID,
        worker_id: str,
        error: BaseException,
        max_attempts: int,
        *,
        now: datetime | None = None,
    ) -> None:
        timestamp = _now(now)
        model = await self._owned(event_id, worker_id)
        model.attempts += 1
        model.last_error = f"{type(error).__name__}: {error}"[:4000]
        model.locked_by = None
        model.locked_until = None
        if model.attempts >= max_attempts:
            model.dead_lettered_at = timestamp
        else:
            model.available_at = timestamp + timedelta(
                seconds=min(2 ** (model.attempts - 1), 300)
            )
        await self.session.flush()

    async def queue_stats(self) -> OutboxStats:
        pending, oldest = (
            await self.session.execute(
                select(
                    func.count(OutboxEventModel.id),
                    func.min(OutboxEventModel.occurred_at),
                ).where(
                    OutboxEventModel.processed_at.is_(None),
                    OutboxEventModel.dead_lettered_at.is_(None),
                )
            )
        ).one()
        dead = await self.session.scalar(
            select(func.count(OutboxEventModel.id)).where(
                OutboxEventModel.dead_lettered_at.is_not(None)
            )
        )
        return OutboxStats(int(pending), oldest, int(dead or 0))

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()

    async def _owned(self, event_id: UUID, worker_id: str) -> OutboxEventModel:
        model = await self.session.scalar(
            select(OutboxEventModel)
            .where(
                OutboxEventModel.id == event_id,
                OutboxEventModel.locked_by == worker_id,
                OutboxEventModel.processed_at.is_(None),
                OutboxEventModel.dead_lettered_at.is_(None),
            )
            .with_for_update()
        )
        if model is None:
            raise OutboxLeaseLost(f"Outbox lease lost for event {event_id}")
        return model


def _envelope(model: OutboxEventModel) -> EventEnvelope:
    return EventEnvelope(
        model.id,
        model.organization_id,
        model.event_name,
        model.event_version,
        model.aggregate_type,
        model.aggregate_id,
        model.payload,
        model.occurred_at,
    )


def _now(value: datetime | None) -> datetime:
    result = value or datetime.now(UTC)
    if result.utcoffset() is None:
        raise ValueError("Outbox timestamps must include a timezone")
    return result.astimezone(UTC)
