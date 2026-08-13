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
    RefundAggregate,
    RefundLocationRow,
    RefundTrendRow,
    SalesBlock,
)
from beanly.modules.dashboard.application.period_service import PeriodService
from beanly.modules.dashboard.application.ports import (
    FinanceDashboardPort,
    InventoryDashboardPort,
    OrganizationDashboardPort,
    PaymentsDashboardPort,
    RefundsDashboardPort,
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
        refunds: RefundsDashboardPort | None = None,
    ) -> None:
        self.organizations = organizations
        self.sales = sales
        self.payments = payments
        self._refunds_configured = refunds is not None
        self.refunds = refunds or _NoRefundsDashboard()
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
        selected = next((value for value in accessible if value.id == location_id), None)
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
        current_refunds = await self.refunds.summary(
            context.organization_id,
            location_ids,
            resolved.current.date_from,
            resolved.current.date_to,
        )
        previous_refunds = await self.refunds.summary(
            context.organization_id,
            location_ids,
            resolved.previous.date_from,
            resolved.previous.date_to,
        )
        current_gross_minor = _minor(current_sales.revenue)
        previous_gross_minor = _minor(previous_sales.revenue)
        current_discount_minor = _minor(current_sales.discount)
        previous_discount_minor = _minor(previous_sales.discount)
        current_net = _major(
            current_gross_minor - current_discount_minor - current_refunds.amount_minor
        )
        previous_net = _major(
            previous_gross_minor - previous_discount_minor - previous_refunds.amount_minor
        )
        open_orders, open_shifts = await self.sales.operations(
            context.organization_id, location_ids
        )
        sales_block = SalesBlock(
            revenue=_decimal_metric(current_net, previous_net),
            paid_orders=_count_metric(current_sales.paid_orders, previous_sales.paid_orders),
            average_check=_decimal_metric(
                _average(current_net, current_sales.paid_orders),
                _average(previous_net, previous_sales.paid_orders),
            ),
            open_orders=open_orders,
            open_shifts=open_shifts,
            gross_sales_minor=str(current_gross_minor),
            discount_amount_minor=str(current_discount_minor),
            refund_amount_minor=str(current_refunds.amount_minor),
            net_sales_minor=str(
                current_gross_minor - current_discount_minor - current_refunds.amount_minor
            ),
        )

        health = await self.inventory.health(context.organization_id, location_ids)
        negative_items = await self.inventory.negative_items(
            context.organization_id, location_ids, 5
        )
        active_counts = await self.inventory.active_counts(context.organization_id, location_ids)
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
        gross_trend = await self.sales.trend(
            context.organization_id,
            location_ids,
            self.periods.buckets(resolved),
        )
        refund_trend = (
            await self.refunds.trend(
                context.organization_id,
                location_ids,
                self.periods.buckets(resolved),
            )
            if self._refunds_configured
            else tuple(RefundTrendRow(0) for _ in gross_trend)
        )
        trend = tuple(
            _trend_row(gross, refund)
            for gross, refund in zip(gross_trend, refund_trend, strict=True)
        )
        location_sales = await self.sales.locations(
            context.organization_id,
            location_ids,
            resolved.current.date_from,
            resolved.current.date_to,
        )
        location_refunds = await self.refunds.locations(
            context.organization_id,
            location_ids,
            resolved.current.date_from,
            resolved.current.date_to,
        )
        sales_by_location = {value.location_id: value for value in location_sales}
        refunds_by_location = {value.location_id: value.amount_minor for value in location_refunds}
        profit_by_location = {
            value.location_id: value.operating_profit for value in finance_locations
        }
        scorecard = tuple(
            _location_row(
                location.id,
                location.name,
                sales_by_location,
                refunds_by_location,
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
    return (change * 100 / abs(previous)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


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
    refunds: dict[UUID, int],
    profits: dict[UUID, Decimal] | None,
) -> LocationScorecardRow:
    row = sales.get(location_id)
    gross_minor = _minor(row.revenue + row.discount) if row else 0
    discount_minor = _minor(row.discount) if row else 0
    refund_minor = refunds.get(location_id, 0)
    net = _major(gross_minor - discount_minor - refund_minor)
    paid_orders = row.paid_orders if row else 0
    return LocationScorecardRow(
        location_id=location_id,
        location_name=location_name,
        revenue=net,
        paid_orders=paid_orders,
        average_check=_average(net, paid_orders),
        operating_profit=profits.get(location_id) if profits is not None else None,
        gross_sales_minor=str(gross_minor),
        discount_amount_minor=str(discount_minor),
        refund_amount_minor=str(refund_minor),
        net_sales_minor=str(gross_minor - discount_minor - refund_minor),
    )


def _trend_row(gross, refund: RefundTrendRow):
    discount_minor = int(gross.discount_amount_minor)
    gross_minor = int(gross.gross_sales_minor)
    if not gross_minor and gross.revenue:
        gross_minor = _minor(gross.revenue) + discount_minor
    net_minor = gross_minor - discount_minor - refund.amount_minor
    return type(gross)(
        bucket_start=gross.bucket_start,
        revenue=_major(net_minor),
        orders=gross.orders,
        gross_sales_minor=str(gross_minor),
        discount_amount_minor=str(discount_minor),
        refund_amount_minor=str(refund.amount_minor),
        net_sales_minor=str(net_minor),
    )


def _minor(value: Decimal) -> int:
    return int((value * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _major(value_minor: int) -> Decimal:
    return Decimal(value_minor) / Decimal(100)


def _average(value: Decimal, count: int) -> Decimal:
    if not count:
        return Decimal(0)
    return (value / count).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


class _NoRefundsDashboard:
    async def summary(self, *args, **kwargs) -> RefundAggregate:
        return RefundAggregate(0)

    async def trend(
        self,
        organization_id: UUID,
        location_ids: tuple[UUID, ...],
        buckets: tuple[tuple[datetime, datetime], ...],
    ) -> tuple[RefundTrendRow, ...]:
        return tuple(RefundTrendRow(0) for _ in buckets)

    async def locations(self, *args, **kwargs) -> tuple[RefundLocationRow, ...]:
        return ()
