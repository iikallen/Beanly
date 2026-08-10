from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from beanly.modules.analytics.application.dto import (
    ABCAnalytics,
    ABCRow,
    ABCThresholds,
    AnalyticsOverview,
    HourAnalytics,
    HourAnalyticsRow,
    InventoryConsumptionAnalytics,
    InventoryConsumptionRow,
    LocationAnalytics,
    LocationAnalyticsRow,
    MenuEngineeringAnalytics,
    MenuEngineeringRow,
    MenuEngineeringThresholds,
    ProductAnalyticsRow,
    ProductsAnalytics,
)
from beanly.modules.analytics.application.ports import AnalyticsRepository
from beanly.modules.analytics.domain.enums import (
    ABCClass,
    HourMetric,
    MenuEngineeringClass,
    ProductGroupBy,
    ProductSort,
)
from beanly.modules.analytics.domain.exceptions import (
    AnalyticsFinancialAccessDenied,
    AnalyticsLocationNotFound,
    InvalidAnalyticsRange,
)
from beanly.modules.organizations.application.queries.list_locations import (
    ListLocationsQuery,
)
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.organizations.domain.enums import LocationAccess
from beanly.modules.organizations.domain.exceptions import OrganizationAccessDenied
from beanly.modules.organizations.domain.permissions import Permission

_SIX = Decimal("0.000001")
_HUNDRED = Decimal(100)


class AnalyticsQueryService:
    def __init__(
        self, repository: AnalyticsRepository, organizations: OrganizationService
    ) -> None:
        self.repository = repository
        self.organizations = organizations

    async def overview(
        self,
        context: TenantContext,
        date_from: date,
        date_to: date,
        location_id: UUID | None = None,
    ) -> AnalyticsOverview:
        _range(date_from, date_to)
        scope = await self._scope(context, location_id)
        aggregate = await self.repository.overview(
            context.organization_id, date_from, date_to, scope
        )
        currency = await self.repository.organization_currency(context.organization_id)
        data_as_of = await self.repository.data_as_of(context.organization_id)
        average_check = _divide(aggregate.revenue, aggregate.paid_orders) or Decimal(0)
        finance = Permission.FINANCE_READ in context.permissions
        gross_profit = aggregate.revenue - aggregate.cogs
        return AnalyticsOverview(
            context.organization_id,
            location_id,
            date_from,
            date_to,
            currency,
            _amount(aggregate.revenue),
            aggregate.paid_orders,
            aggregate.items_sold,
            average_check,
            _amount(aggregate.cogs) if finance else None,
            _amount(gross_profit) if finance else None,
            _percent(gross_profit, aggregate.revenue) if finance else None,
            _amount(aggregate.inventory_losses) if finance else None,
            aggregate.incomplete_cogs_orders if finance else None,
            data_as_of,
        )

    async def products(
        self,
        context: TenantContext,
        date_from: date,
        date_to: date,
        location_id: UUID | None = None,
        group_by: ProductGroupBy = ProductGroupBy.PRODUCT,
        sort_by: ProductSort = ProductSort.REVENUE,
        limit: int = 25,
    ) -> ProductsAnalytics:
        _range(date_from, date_to)
        if not 1 <= limit <= 100:
            raise InvalidAnalyticsRange("limit must be between 1 and 100")
        finance = Permission.FINANCE_READ in context.permissions
        if sort_by == ProductSort.GROSS_PROFIT and not finance:
            raise AnalyticsFinancialAccessDenied(
                "finance.read is required for gross-profit sorting"
            )
        scope = await self._scope(context, location_id)
        rows = await self.repository.products(
            context.organization_id,
            date_from,
            date_to,
            scope,
            group_by,
            sort_by,
            limit,
        )
        result = tuple(_product(row, finance) for row in rows)
        data_as_of = await self.repository.data_as_of(context.organization_id)
        return ProductsAnalytics(group_by, result, data_as_of)

    async def abc(
        self,
        context: TenantContext,
        date_from: date,
        date_to: date,
        location_id: UUID | None = None,
    ) -> ABCAnalytics:
        _range(date_from, date_to)
        scope = await self._scope(context, location_id)
        products = await self.repository.products(
            context.organization_id,
            date_from,
            date_to,
            scope,
            ProductGroupBy.PRODUCT,
            ProductSort.REVENUE,
            None,
        )
        total = sum((row.revenue for row in products), Decimal(0))
        cumulative = Decimal(0)
        rows: list[ABCRow] = []
        for product in products:
            share = _percent(product.revenue, total) or Decimal(0)
            cumulative = _amount(cumulative + share)
            class_ = (
                ABCClass.A
                if cumulative <= Decimal(80)
                else ABCClass.B
                if cumulative <= Decimal(95)
                else ABCClass.C
            )
            rows.append(
                ABCRow(
                    product.product_id,
                    product.name,
                    _amount(product.revenue),
                    share,
                    cumulative,
                    class_,
                )
            )
        return ABCAnalytics(
            ABCThresholds(),
            tuple(rows),
            await self.repository.data_as_of(context.organization_id),
        )

    async def menu_engineering(
        self,
        context: TenantContext,
        date_from: date,
        date_to: date,
        location_id: UUID | None = None,
    ) -> MenuEngineeringAnalytics:
        _range(date_from, date_to)
        if Permission.FINANCE_READ not in context.permissions:
            raise AnalyticsFinancialAccessDenied(
                "finance.read is required for menu engineering"
            )
        scope = await self._scope(context, location_id)
        products = tuple(
            row
            for row in await self.repository.products(
                context.organization_id,
                date_from,
                date_to,
                scope,
                ProductGroupBy.PRODUCT,
                ProductSort.REVENUE,
                None,
            )
            if row.quantity_sold > 0
        )
        total_quantity = sum(row.quantity_sold for row in products)
        total_profit = sum(
            (row.revenue - row.cogs for row in products), Decimal(0)
        )
        count = len(products)
        expected = _amount(_HUNDRED / count) if count else Decimal(0)
        popularity_threshold = _amount(expected * Decimal("0.70"))
        margin_threshold = _divide(total_profit, total_quantity) or Decimal(0)
        rows = tuple(
            _menu_row(
                row,
                total_quantity,
                popularity_threshold,
                margin_threshold,
            )
            for row in products
        )
        return MenuEngineeringAnalytics(
            MenuEngineeringThresholds(
                Decimal("0.70"), expected, popularity_threshold, margin_threshold
            ),
            rows,
            await self.repository.data_as_of(context.organization_id),
        )

    async def hours(
        self,
        context: TenantContext,
        date_from: date,
        date_to: date,
        location_id: UUID | None = None,
        metric: HourMetric = HourMetric.REVENUE,
    ) -> HourAnalytics:
        _range(date_from, date_to)
        scope = await self._scope(context, location_id)
        raw = await self.repository.hours(
            context.organization_id, date_from, date_to, scope
        )
        values: defaultdict[tuple[int, int], Decimal] = defaultdict(Decimal)
        for row in raw:
            value = {
                HourMetric.REVENUE: row.revenue,
                HourMetric.ORDERS: Decimal(row.paid_orders),
                HourMetric.ITEMS: Decimal(row.items_sold),
            }[metric]
            values[(row.local_date.weekday(), row.local_hour)] += value
        rows = tuple(
            HourAnalyticsRow(day, hour, _amount(value))
            for (day, hour), value in sorted(values.items())
        )
        return HourAnalytics(
            metric, rows, await self.repository.data_as_of(context.organization_id)
        )

    async def inventory_consumption(
        self,
        context: TenantContext,
        date_from: date,
        date_to: date,
        location_id: UUID | None = None,
        warehouse_id: UUID | None = None,
        inventory_item_id: UUID | None = None,
    ) -> InventoryConsumptionAnalytics:
        _range(date_from, date_to)
        scope = await self._scope(context, location_id)
        finance = Permission.FINANCE_READ in context.permissions
        rows = await self.repository.consumption(
            context.organization_id,
            date_from,
            date_to,
            scope,
            warehouse_id,
            inventory_item_id,
        )
        return InventoryConsumptionAnalytics(
            tuple(
                InventoryConsumptionRow(
                    row.inventory_item_id,
                    row.name,
                    row.base_unit,
                    _amount(row.sale_quantity),
                    _amount(row.sale_cost_amount) if finance else None,
                    _amount(row.writeoff_quantity),
                    _amount(row.writeoff_cost_amount) if finance else None,
                    _amount(row.adjustment_quantity),
                    _percent(
                        row.writeoff_quantity,
                        row.sale_quantity + row.writeoff_quantity,
                    ),
                )
                for row in rows
            ),
            await self.repository.data_as_of(context.organization_id),
        )

    async def locations(
        self,
        context: TenantContext,
        date_from: date,
        date_to: date,
    ) -> LocationAnalytics:
        _range(date_from, date_to)
        scope = await self._scope(context, None)
        finance = Permission.FINANCE_READ in context.permissions
        values = await self.repository.locations(
            context.organization_id, date_from, date_to, scope
        )
        revenues = _ranks({row.location_id: row.revenue for row in values})
        orders = _ranks({row.location_id: Decimal(row.paid_orders) for row in values})
        averages = _ranks(
            {
                row.location_id: _divide(row.revenue, row.paid_orders) or Decimal(0)
                for row in values
            }
        )
        profits = {
            row.location_id: (
                row.revenue
                - row.cogs
                - row.operating_expenses
                - row.inventory_losses
                + row.inventory_gains
            )
            for row in values
        }
        margins = {
            row.location_id: _percent(row.revenue - row.cogs, row.revenue)
            or Decimal(0)
            for row in values
        }
        profit_ranks = _ranks(profits)
        margin_ranks = _ranks(margins)
        rows = tuple(
            LocationAnalyticsRow(
                row.location_id,
                row.location_name,
                _amount(row.revenue),
                row.paid_orders,
                row.items_sold,
                _divide(row.revenue, row.paid_orders) or Decimal(0),
                _amount(row.cogs) if finance else None,
                _amount(row.revenue - row.cogs) if finance else None,
                margins[row.location_id] if finance else None,
                _amount(row.operating_expenses) if finance else None,
                _amount(profits[row.location_id]) if finance else None,
                revenues[row.location_id],
                orders[row.location_id],
                averages[row.location_id],
                margin_ranks[row.location_id] if finance else None,
                profit_ranks[row.location_id] if finance else None,
            )
            for row in sorted(values, key=lambda value: (-value.revenue, str(value.location_id)))
        )
        return LocationAnalytics(
            rows, await self.repository.data_as_of(context.organization_id)
        )

    async def _scope(
        self, context: TenantContext, location_id: UUID | None
    ) -> set[UUID] | None:
        if location_id is not None:
            try:
                await self.organizations.ensure_location_access(context, location_id)
            except OrganizationAccessDenied as exc:
                raise AnalyticsLocationNotFound("Location not found") from exc
            return {location_id}
        if context.location_access == LocationAccess.ALL:
            return None
        locations = await self.organizations.list_locations(
            ListLocationsQuery(context.user_id, context.organization_id)
        )
        return {location.id for location in locations}


def _product(row, finance: bool) -> ProductAnalyticsRow:
    profit = row.revenue - row.cogs
    return ProductAnalyticsRow(
        row.product_id,
        row.product_variant_id,
        row.name,
        row.variant_name,
        row.quantity_sold,
        _amount(row.revenue),
        row.orders,
        _amount(row.cogs) if finance else None,
        _amount(profit) if finance else None,
        _percent(profit, row.revenue) if finance else None,
        row.incomplete_cogs_orders if finance else None,
    )


def _menu_row(row, total_quantity, popularity_threshold, margin_threshold):
    popularity = _percent(Decimal(row.quantity_sold), Decimal(total_quantity)) or Decimal(0)
    contribution = _divide(row.revenue - row.cogs, row.quantity_sold) or Decimal(0)
    high_popularity = popularity >= popularity_threshold
    high_margin = contribution >= margin_threshold
    classification = {
        (True, True): MenuEngineeringClass.HERO,
        (True, False): MenuEngineeringClass.WORKHORSE,
        (False, True): MenuEngineeringClass.PUZZLE,
        (False, False): MenuEngineeringClass.LOW_PERFORMER,
    }[(high_popularity, high_margin)]
    return MenuEngineeringRow(
        row.product_id,
        row.name,
        row.quantity_sold,
        _amount(row.revenue),
        row.orders,
        popularity,
        contribution,
        _percent(row.revenue - row.cogs, row.revenue),
        classification,
    )


def _range(date_from: date, date_to: date) -> None:
    if date_from > date_to:
        raise InvalidAnalyticsRange("date_from must not be after date_to")


def _divide(numerator: Decimal, denominator: int | Decimal) -> Decimal | None:
    if not denominator:
        return None
    return _amount(numerator / Decimal(denominator))


def _percent(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    if not denominator:
        return None
    return _amount(numerator * _HUNDRED / denominator)


def _amount(value: Decimal) -> Decimal:
    return value.quantize(_SIX, rounding=ROUND_HALF_UP)


def _ranks(values: dict[UUID, Decimal]) -> dict[UUID, int]:
    ordered = sorted(values.items(), key=lambda pair: (-pair[1], str(pair[0])))
    result: dict[UUID, int] = {}
    previous: Decimal | None = None
    rank = 0
    for position, (key, value) in enumerate(ordered, start=1):
        if value != previous:
            rank = position
            previous = value
        result[key] = rank
    return result
