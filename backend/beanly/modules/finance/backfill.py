import asyncio
from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid5

from beanly.core.database.session import engine, session_factory
from beanly.modules.finance.application.projection_service import FinanceProjectionService
from beanly.modules.finance.application.source_ports import FinanceSourceReader
from beanly.modules.finance.domain.repositories import FinanceRepository
from beanly.modules.finance.infrastructure.db.repositories import SqlAlchemyFinanceRepository
from beanly.modules.finance.infrastructure.source_reader import SqlAlchemyFinanceSourceReader


@dataclass(frozen=True, slots=True)
class BackfillResult:
    payments: int
    writeoffs: int
    counts: int


class FinanceBackfillService:
    def __init__(
        self,
        projections: FinanceProjectionService,
        sources: FinanceSourceReader,
        repository: FinanceRepository,
    ) -> None:
        self.projections = projections
        self.sources = sources
        self.repository = repository

    async def run(self) -> BackfillResult:
        payments = await self.sources.paid_payment_ids()
        writeoffs = await self.sources.posted_writeoff_ids()
        counts = await self.sources.posted_count_ids()
        try:
            for organization_id, payment_id in payments:
                payment = await self.sources.payment(organization_id, payment_id)
                await self.projections.apply_payment_completed(
                    _event_id("payment", payment_id),
                    organization_id,
                    payment_id,
                    payment.order_id,
                )
                await self.repository.commit()
            for organization_id, writeoff_id in writeoffs:
                source = await self.sources.writeoff(organization_id, writeoff_id)
                await self.projections.apply_writeoff_posted(
                    _event_id("writeoff-posted", writeoff_id),
                    organization_id,
                    writeoff_id,
                )
                if source.status == "REVERSED":
                    await self.projections.apply_writeoff_reversed(
                        _event_id("writeoff-reversed", writeoff_id),
                        organization_id,
                        writeoff_id,
                    )
                await self.repository.commit()
            for organization_id, count_id in counts:
                await self.projections.apply_inventory_count_posted(
                    _event_id("count", count_id), organization_id, count_id
                )
                await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise
        return BackfillResult(len(payments), len(writeoffs), len(counts))


def _event_id(kind: str, source_id: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, f"beanly:finance-backfill:{kind}:{source_id}")


async def _main() -> None:
    try:
        async with session_factory() as session:
            repository = SqlAlchemyFinanceRepository(session)
            sources = SqlAlchemyFinanceSourceReader(session)
            result = await FinanceBackfillService(
                FinanceProjectionService(repository, sources), sources, repository
            ).run()
            print(
                f"Finance backfill complete: payments={result.payments} "
                f"writeoffs={result.writeoffs} counts={result.counts}"
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
