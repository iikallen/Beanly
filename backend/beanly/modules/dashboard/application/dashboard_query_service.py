from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from beanly.modules.dashboard.application.dto import (
    CountMetric,
    DashboardAlert,
    DashboardOverview,
    DashboardScope,
    DecimalMetric,
    FinanceBlock,
    InventoryBlock,
    LocationSalesRow,
    LocationScorecardRow,
    SalesBlock,
)
from beanly.modules.dashboard.application.period_service import PeriodService
from beanly.modules.dashboard.application.ports import (
    FinanceDashboardPort,
    InventoryDashboardPort,
    OrganizationDashboardPort,
    PaymentsDashboardPort,
    SalesDashboardPort,
)
from beanly.modules.dashboard.domain.enums import (
    AlertSeverity,
    DashboardPeriod,
    MetricDirection,
)
from beanly.modules.dashboard.domain.exceptions import DashboardLocationNotFound
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.organizations.domain.permissions import Permission


class DashboardQueryService:
    def __init__(
        self,
        organizations: OrganizationDashboardPort,
        sales: SalesDashboardPort,
        payments: PaymentsDashboardPort,
        inventory: InventoryDashboardPort,
        finance: FinanceDashboardPort,
        periods: PeriodService | None = None,
    ) -> None:
        self.organizations = organizations
        self.sales = sales
        self.payments = payments
        self.inventory = inventory
        self.finance = finance
        self.periods = periods or PeriodService()

    async def overview(
        self,
        context: TenantContext,
        period: DashboardPeriod,
        location_id: UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        *,
        now: datetime | None = None,
    ) -> DashboardOverview:
        accessible = await self.organizations.locations(context)
        selected = next(
            (value for value in accessible if value.id == location_id), None
        )
        if location_id is not None and selected is None:
            raise DashboardLocationNotFound("Location not found")
        if selected is not None:
            timezone = selected.timezone
            location_name = selected.name
            scoped_locations = (selected,)
        else:
            timezone = await self.organizations.reporting_timezone(context)
            location_name = "All locations"
            scoped_locations = accessible

        resolved = self.periods.resolve(
            period,
            timezone,
            date_from=date_from,
            date_to=date_to,
            now=now,
        )
        location_ids = tuple(value.id for value in scoped_locations)

        current_sales = await self.sales.summary(
            context.organization_id,
            location_ids,
            resolved.current.date_from,
            resolved.current.date_to,
        )
        previous_sales = await self.sales.summary(
            context.organization_id,
            location_ids,
            resolved.previous.date_from,
            resolved.previous.date_to,
        )
        open_orders, open_shifts = await self.sales.operations(
            context.organization_id, location_ids
        )
        sales_block = SalesBlock(
            _decimal_metric(current_sales.revenue, previous_sales.revenue),
            _count_metric(current_sales.paid_orders, previous_sales.paid_orders),
            _decimal_metric(
                current_sales.average_check, previous_sales.average_check
            ),
            open_orders,
            open_shifts,
        )

        health = await self.inventory.health(context.organization_id, location_ids)
        negative_items = await self.inventory.negative_items(
            context.organization_id, location_ids, 5
        )
        active_counts = await self.inventory.active_counts(
            context.organization_id, location_ids
        )
        inventory_block = InventoryBlock(
            health.total_value,
            health.negative_stock_count,
            health.active_count_count,
            negative_items,
        )

        finance_block = None
        finance_locations = ()
        if Permission.FINANCE_READ in context.permissions:
            current_finance = await self.finance.snapshot(
                context,
                resolved.current.date_from,
                resolved.current.date_to,
                location_id,
            )
            previous_profit = await self.finance.operating_profit(
                context,
                resolved.previous.date_from,
                resolved.previous.date_to,
                location_id,
            )
            finance_block = FinanceBlock(
                current_finance.currency_code,
                current_finance.cogs,
                current_finance.gross_profit,
                current_finance.gross_margin_percent,
                current_finance.operating_expenses,
                current_finance.inventory_losses,
                current_finance.inventory_gains,
                current_finance.operating_profit,
                _decimal_metric(current_finance.operating_profit, previous_profit),
                str(current_finance.net_cash_movement_minor),
                current_finance.incomplete_cogs_sales,
                current_finance.data_as_of,
            )
            finance_locations = await self.finance.locations(
                context,
                resolved.current.date_from,
                resolved.current.date_to,
            )

        mix = await self.payments.mix(
            context.organization_id,
            location_ids,
            resolved.current.date_from,
            resolved.current.date_to,
        )
        trend = await self.sales.trend(
            context.organization_id,
            location_ids,
            self.periods.buckets(resolved),
        )
        location_sales = await self.sales.locations(
            context.organization_id,
            location_ids,
            resolved.current.date_from,
            resolved.current.date_to,
        )
        sales_by_location = {value.location_id: value for value in location_sales}
        profit_by_location = {
            value.location_id: value.operating_profit for value in finance_locations
        }
        scorecard = tuple(
            _location_row(
                location.id,
                location.name,
                sales_by_location,
                profit_by_location if finance_block else None,
            )
            for location in scoped_locations
        )

        alerts: list[DashboardAlert] = []
        if health.negative_stock_count:
            alerts.append(
                DashboardAlert(
                    "NEGATIVE_STOCK",
                    AlertSeverity.CRITICAL,
                    "Negative stock",
                    f"{health.negative_stock_count} inventory items are negative.",
                    location_id,
                    None,
                    None,
                    "/app/inventory",
                )
            )
        if finance_block and finance_block.incomplete_cogs_sales:
            alerts.append(
                DashboardAlert(
                    "INCOMPLETE_COGS",
                    AlertSeverity.WARNING,
                    "Incomplete inventory cost",
                    f"{finance_block.incomplete_cogs_sales} sales have incomplete "
                    "inventory cost. Profit may be understated.",
                    location_id,
                    None,
                    None,
                    "/app/finance/pnl",
                )
            )
        alerts.extend(
            DashboardAlert(
                "INVENTORY_COUNT_IN_PROGRESS",
                AlertSeverity.INFO,
                "Inventory count in progress",
                f"Inventory count {value.number} is still in progress.",
                value.location_id,
                "inventory_count",
                value.id,
                f"/app/inventory/counts/{value.id}",
            )
            for value in active_counts
        )

        return DashboardOverview(
            DashboardScope(
                context.organization_id,
                location_id,
                location_name,
                timezone,
                period,
                resolved.current,
                resolved.previous,
            ),
            sales_block,
            finance_block,
            inventory_block,
            mix,
            trend,
            scorecard,
            tuple(alerts),
        )


def _decimal_metric(current: Decimal, previous: Decimal) -> DecimalMetric:
    change = current - previous
    return DecimalMetric(
        current,
        previous,
        change,
        _percent_change(change, previous),
        _direction(change),
    )


def _count_metric(current: int, previous: int) -> CountMetric:
    change = current - previous
    return CountMetric(
        current,
        previous,
        change,
        _percent_change(Decimal(change), Decimal(previous)),
        _direction(Decimal(change)),
    )


def _percent_change(change: Decimal, previous: Decimal) -> Decimal | None:
    if not previous:
        return None
    return (change * 100 / abs(previous)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def _direction(change: Decimal) -> MetricDirection:
    if change > 0:
        return MetricDirection.UP
    if change < 0:
        return MetricDirection.DOWN
    return MetricDirection.FLAT


def _location_row(
    location_id: UUID,
    location_name: str,
    sales: dict[UUID, LocationSalesRow],
    profits: dict[UUID, Decimal] | None,
) -> LocationScorecardRow:
    row = sales.get(location_id)
    return LocationScorecardRow(
        location_id,
        location_name,
        row.revenue if row else Decimal(0),
        row.paid_orders if row else 0,
        row.average_check if row else Decimal(0),
        profits.get(location_id) if profits is not None else None,
    )
