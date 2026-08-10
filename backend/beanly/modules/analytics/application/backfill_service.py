from dataclasses import dataclass
from datetime import date, datetime
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo

from beanly.modules.analytics.application.ports import AnalyticsRepository
from beanly.modules.analytics.application.projection_service import (
    AnalyticsProjectionService,
)
from beanly.modules.analytics.application.source_ports import AnalyticsSourceReader


@dataclass(frozen=True, slots=True)
class AnalyticsBackfillResult:
    payments: int
    inventory_transactions: int
    expenses_posted: int
    expenses_reversed: int


class AnalyticsBackfillService:
    def __init__(
        self,
        projections: AnalyticsProjectionService,
        sources: AnalyticsSourceReader,
        repository: AnalyticsRepository,
    ) -> None:
        self.projections = projections
        self.sources = sources
        self.repository = repository

    async def run(
        self,
        *,
        organization_id: UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        batch_size: int = 500,
    ) -> AnalyticsBackfillResult:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        if date_from is not None and date_to is not None and date_from > date_to:
            raise ValueError("date_from must not be after date_to")
        payments = 0
        inventory = 0
        expenses_posted = 0
        expenses_reversed = 0
        pending = 0
        try:
            cursor = None
            while True:
                page = await self.sources.paid_payments(
                    organization_id,
                    date_from,
                    date_to,
                    limit=batch_size,
                    after=cursor,
                )
                if not page:
                    break
                for source in page:
                    sale = await self.sources.sale(
                        source.organization_id, source.source_id
                    )
                    if not _in_range(sale.paid_at, sale.timezone, date_from, date_to):
                        continue
                    payments += int(
                        await self.projections.apply_payment_completed(
                            _event_id("payment", source.source_id),
                            source.organization_id,
                            source.source_id,
                            sale.order_id,
                            source.occurred_at,
                        )
                    )
                    pending += 1
                    pending = await self._maybe_commit(pending, batch_size)
                cursor = (page[-1].occurred_at, page[-1].source_id)
                if len(page) < batch_size:
                    break

            cursor = None
            while True:
                page = await self.sources.posted_inventory_transactions(
                    organization_id,
                    date_from,
                    date_to,
                    limit=batch_size,
                    after=cursor,
                )
                if not page:
                    break
                for source in page:
                    value = await self.sources.inventory_transaction(
                        source.organization_id, source.source_id
                    )
                    if not _in_range(
                        value.posted_at, value.timezone, date_from, date_to
                    ):
                        continue
                    inventory += int(
                        await self.projections.apply_inventory_transaction_posted(
                            _event_id("inventory", source.source_id),
                            source.organization_id,
                            source.source_id,
                            source.occurred_at,
                        )
                    )
                    pending += 1
                    pending = await self._maybe_commit(pending, batch_size)
                cursor = (page[-1].occurred_at, page[-1].source_id)
                if len(page) < batch_size:
                    break

            cursor = None
            while True:
                page = await self.sources.posted_expenses(
                    organization_id,
                    date_from,
                    date_to,
                    limit=batch_size,
                    after=cursor,
                )
                if not page:
                    break
                for source in page:
                    value = await self.sources.expense(
                        source.organization_id, source.source_id
                    )
                    if value.location_id is None or value.timezone is None:
                        # Central expenses remain organization-level Finance.
                        include_posted = date_from is None and date_to is None
                        include_reversed = value.reversed_at is not None and include_posted
                    else:
                        include_posted = _in_range(
                            value.occurred_at, value.timezone, date_from, date_to
                        )
                        include_reversed = value.reversed_at is not None and _in_range(
                            value.reversed_at, value.timezone, date_from, date_to
                        )
                    if include_posted:
                        expenses_posted += int(
                            await self.projections.apply_expense_posted(
                                _event_id("expense-posted", source.source_id),
                                source.organization_id,
                                source.source_id,
                                value.occurred_at,
                            )
                        )
                        pending += 1
                    if include_reversed and value.reversed_at is not None:
                        expenses_reversed += int(
                            await self.projections.apply_expense_reversed(
                                _event_id("expense-reversed", source.source_id),
                                source.organization_id,
                                source.source_id,
                                value.reversed_at,
                            )
                        )
                        pending += 1
                    pending = await self._maybe_commit(pending, batch_size)
                cursor = (page[-1].occurred_at, page[-1].source_id)
                if len(page) < batch_size:
                    break
            if pending:
                await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise
        return AnalyticsBackfillResult(
            payments, inventory, expenses_posted, expenses_reversed
        )

    async def _maybe_commit(self, pending: int, batch_size: int) -> int:
        if pending < batch_size:
            return pending
        await self.repository.commit()
        return 0


def _event_id(kind: str, source_id: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, f"beanly:analytics-backfill:{kind}:{source_id}")


def _in_range(
    value: datetime,
    timezone: str,
    date_from: date | None,
    date_to: date | None,
) -> bool:
    local_date = value.astimezone(ZoneInfo(timezone)).date()
    return (date_from is None or local_date >= date_from) and (
        date_to is None or local_date <= date_to
    )
