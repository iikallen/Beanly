from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from beanly.modules.finance.application.access import (
    allowed_locations,
    require_report_location,
)
from beanly.modules.finance.domain.enums import FinanceEntryType
from beanly.modules.finance.domain.exceptions import InvalidFinanceOperation
from beanly.modules.finance.domain.repositories import FinanceRepository
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.domain.entities import TenantContext

ZERO = Decimal(0)


@dataclass(frozen=True, slots=True)
class PnlResult:
    currency_code: str
    revenue: Decimal
    cogs: Decimal
    gross_profit: Decimal
    inventory_losses: Decimal
    inventory_gains: Decimal
    operating_expenses: Decimal
    other_income: Decimal
    other_expenses: Decimal
    operating_profit: Decimal
    gross_margin_percent: Decimal | None
    incomplete_cogs_sales: int


@dataclass(frozen=True, slots=True)
class LocationPnlResult:
    location_id: UUID | None
    location_name: str
    revenue: Decimal
    cogs: Decimal
    gross_profit: Decimal
    operating_expenses: Decimal
    operating_profit: Decimal


class FinanceQueryService:
    def __init__(
        self, repository: FinanceRepository, organizations: OrganizationService
    ) -> None:
        self.repository = repository
        self.organizations = organizations

    async def pnl(
        self,
        context: TenantContext,
        date_from: datetime,
        date_to: datetime,
        location_id: UUID | None,
    ) -> PnlResult:
        start, end = await self._range(context, date_from, date_to, location_id)
        totals: dict[str, Decimal] = {}
        incomplete = 0
        for scoped_location in await self._report_locations(context, location_id):
            scoped = await self.repository.finance_totals(
                context.organization_id, start, end, scoped_location
            )
            for key, amount in scoped.items():
                totals[key] = totals.get(key, ZERO) + amount
            incomplete += await self.repository.incomplete_cogs_count(
                context.organization_id, start, end, scoped_location
            )
        return _pnl(await self.repository.currency(context.organization_id), totals, incomplete)

    async def expense_breakdown(
        self,
        context: TenantContext,
        date_from: datetime,
        date_to: datetime,
        location_id: UUID | None,
    ) -> list[tuple[UUID | None, str, Decimal]]:
        start, end = await self._range(context, date_from, date_to, location_id)
        grouped: dict[tuple[UUID | None, str], Decimal] = {}
        for scoped_location in await self._report_locations(context, location_id):
            values = await self.repository.expense_breakdown(
                context.organization_id, start, end, scoped_location
            )
            for category_id, name, amount in values:
                key = (category_id, name)
                grouped[key] = grouped.get(key, ZERO) - amount
        sorted_values = sorted(grouped.items(), key=lambda value: value[0][1])
        return [(key[0], key[1], amount) for key, amount in sorted_values]

    async def locations(
        self, context: TenantContext, date_from: datetime, date_to: datetime
    ) -> list[LocationPnlResult]:
        start, end = _aware(date_from), _aware(date_to)
        if start >= end:
            raise InvalidFinanceOperation("date_from must be before date_to")
        rows = await self.repository.location_totals(context.organization_id, start, end)
        allowed = await allowed_locations(self.organizations, context)
        if allowed is not None:
            rows = [row for row in rows if row[0] in allowed]
        return [
            LocationPnlResult(
                location_id,
                name,
                (result := _pnl("", totals, 0)).revenue,
                result.cogs,
                result.gross_profit,
                result.operating_expenses,
                result.operating_profit,
            )
            for location_id, name, totals in rows
        ]

    async def cash_flow(
        self,
        context: TenantContext,
        date_from: datetime,
        date_to: datetime,
        location_id: UUID | None,
    ) -> tuple[str, int, dict[str, tuple[int, int]], int]:
        start, end = await self._range(context, date_from, date_to, location_id)
        opening = 0
        values: dict[str, tuple[int, int]] = {}
        for scoped_location in await self._report_locations(context, location_id):
            scoped_opening, scoped_values = await self.repository.cash_totals(
                context.organization_id, start, end, scoped_location
            )
            opening += scoped_opening
            for key, (inflows, outflows) in scoped_values.items():
                previous = values.get(key, (0, 0))
                values[key] = (previous[0] + inflows, previous[1] + outflows)
        net = sum(inflows - outflows for inflows, outflows in values.values())
        return await self.repository.currency(context.organization_id), opening, values, net

    async def data_as_of(
        self, context: TenantContext, location_id: UUID | None
    ) -> datetime | None:
        await require_report_location(self.organizations, context, location_id)
        values = [
            await self.repository.data_as_of(context.organization_id, scoped_location)
            for scoped_location in await self._report_locations(context, location_id)
        ]
        return max((value for value in values if value is not None), default=None)

    async def entries(
        self,
        context: TenantContext,
        date_from: datetime | None,
        date_to: datetime | None,
        location_id: UUID | None,
        entry_type: FinanceEntryType | None,
        source_type: str | None,
        source_id: UUID | None,
    ):
        if date_from and date_to and _aware(date_from) >= _aware(date_to):
            raise InvalidFinanceOperation("date_from must be before date_to")
        await require_report_location(self.organizations, context, location_id)
        values = []
        for scoped_location in await self._report_locations(context, location_id):
            values.extend(
                await self.repository.list_finance_entries(
                    context.organization_id,
                    _aware(date_from) if date_from else None,
                    _aware(date_to) if date_to else None,
                    scoped_location,
                    entry_type,
                    source_type.strip().upper() if source_type else None,
                    source_id,
                )
            )
        return sorted(values, key=lambda value: (value.effective_at, value.id), reverse=True)

    async def _range(
        self,
        context: TenantContext,
        date_from: datetime,
        date_to: datetime,
        location_id: UUID | None,
    ) -> tuple[datetime, datetime]:
        start, end = _aware(date_from), _aware(date_to)
        if start >= end:
            raise InvalidFinanceOperation("date_from must be before date_to")
        await require_report_location(self.organizations, context, location_id)
        return start, end

    async def _report_locations(
        self, context: TenantContext, location_id: UUID | None
    ) -> list[UUID | None]:
        if location_id is not None:
            return [location_id]
        allowed = await allowed_locations(self.organizations, context)
        return [None] if allowed is None else sorted(allowed, key=str)


def _pnl(currency_code: str, totals: dict[str, Decimal], incomplete: int) -> PnlResult:
    def value(key: str) -> Decimal:
        return totals.get(key, ZERO)
    revenue = value(FinanceEntryType.REVENUE.value)
    cogs = -value(FinanceEntryType.COGS.value)
    gross = revenue - cogs
    losses = -value(FinanceEntryType.INVENTORY_LOSS.value)
    gains = value(FinanceEntryType.INVENTORY_GAIN.value)
    expenses = -value(FinanceEntryType.OPERATING_EXPENSE.value)
    other_income = value(FinanceEntryType.OTHER_INCOME.value)
    other_expenses = -value(FinanceEntryType.OTHER_EXPENSE.value)
    profit = gross - losses + gains - expenses + other_income - other_expenses
    margin = (
        (gross * 100 / revenue).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if revenue
        else None
    )
    return PnlResult(
        currency_code,
        revenue,
        cogs,
        gross,
        losses,
        gains,
        expenses,
        other_income,
        other_expenses,
        profit,
        margin,
        incomplete,
    )


def _aware(value: datetime) -> datetime:
    if value.utcoffset() is None:
        raise InvalidFinanceOperation("Timestamps must include a timezone")
    return value.astimezone(UTC)
