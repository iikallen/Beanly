from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from beanly.modules.dashboard.domain.enums import (
    AlertSeverity,
    DashboardPeriod,
    MetricDirection,
    TrendBucket,
)


@dataclass(frozen=True, slots=True)
class DateTimeRange:
    date_from: datetime
    date_to: datetime


@dataclass(frozen=True, slots=True)
class ResolvedPeriod:
    period: DashboardPeriod
    timezone: str
    current: DateTimeRange
    previous: DateTimeRange
    bucket: TrendBucket


@dataclass(frozen=True, slots=True)
class ScopeLocation:
    id: UUID
    name: str
    timezone: str
    is_primary: bool


@dataclass(frozen=True, slots=True)
class DashboardScope:
    organization_id: UUID
    location_id: UUID | None
    location_name: str
    timezone: str
    period: DashboardPeriod
    current: DateTimeRange
    previous: DateTimeRange


@dataclass(frozen=True, slots=True)
class DecimalMetric:
    current: Decimal
    previous: Decimal
    absolute_change: Decimal
    percent_change: Decimal | None
    direction: MetricDirection


@dataclass(frozen=True, slots=True)
class CountMetric:
    current: int
    previous: int
    absolute_change: int
    percent_change: Decimal | None
    direction: MetricDirection


@dataclass(frozen=True, slots=True)
class SalesAggregate:
    revenue: Decimal
    paid_orders: int

    @property
    def average_check(self) -> Decimal:
        if not self.paid_orders:
            return Decimal(0)
        return (self.revenue / self.paid_orders).quantize(Decimal("0.000001"))


@dataclass(frozen=True, slots=True)
class SalesBlock:
    revenue: DecimalMetric
    paid_orders: CountMetric
    average_check: DecimalMetric
    open_orders: int
    open_shifts: int
    gross_sales_minor: str = "0"
    refund_amount_minor: str = "0"
    net_sales_minor: str = "0"


@dataclass(frozen=True, slots=True)
class FinanceSnapshot:
    currency_code: str
    cogs: Decimal
    gross_profit: Decimal
    gross_margin_percent: Decimal | None
    operating_expenses: Decimal
    inventory_losses: Decimal
    inventory_gains: Decimal
    operating_profit: Decimal
    incomplete_cogs_sales: int
    net_cash_movement_minor: int
    data_as_of: datetime | None


@dataclass(frozen=True, slots=True)
class FinanceBlock:
    currency_code: str
    cogs: Decimal
    gross_profit: Decimal
    gross_margin_percent: Decimal | None
    operating_expenses: Decimal
    inventory_losses: Decimal
    inventory_gains: Decimal
    operating_profit: Decimal
    operating_profit_comparison: DecimalMetric
    net_cash_movement_minor: str
    incomplete_cogs_sales: int
    data_as_of: datetime | None


@dataclass(frozen=True, slots=True)
class NegativeStockItem:
    item_id: UUID
    location_id: UUID
    name: str
    quantity: Decimal
    unit_code: str


@dataclass(frozen=True, slots=True)
class ActiveInventoryCount:
    id: UUID
    location_id: UUID
    number: str


@dataclass(frozen=True, slots=True)
class InventoryHealth:
    total_value: Decimal
    negative_stock_count: int
    active_count_count: int


@dataclass(frozen=True, slots=True)
class InventoryBlock:
    total_value: Decimal
    negative_stock_count: int
    active_count_count: int
    negative_items: tuple[NegativeStockItem, ...]


@dataclass(frozen=True, slots=True)
class PaymentMixRow:
    method: str
    amount: Decimal
    share_percent: Decimal


@dataclass(frozen=True, slots=True)
class TrendPoint:
    bucket_start: datetime
    revenue: Decimal
    orders: int
    gross_sales_minor: str = "0"
    refund_amount_minor: str = "0"
    net_sales_minor: str = "0"


@dataclass(frozen=True, slots=True)
class LocationSalesRow:
    location_id: UUID
    revenue: Decimal
    paid_orders: int

    @property
    def average_check(self) -> Decimal:
        if not self.paid_orders:
            return Decimal(0)
        return (self.revenue / self.paid_orders).quantize(Decimal("0.000001"))


@dataclass(frozen=True, slots=True)
class LocationFinanceRow:
    location_id: UUID
    operating_profit: Decimal


@dataclass(frozen=True, slots=True)
class LocationScorecardRow:
    location_id: UUID
    location_name: str
    revenue: Decimal
    paid_orders: int
    average_check: Decimal
    operating_profit: Decimal | None
    gross_sales_minor: str = "0"
    refund_amount_minor: str = "0"
    net_sales_minor: str = "0"


@dataclass(frozen=True, slots=True)
class RefundAggregate:
    amount_minor: int


@dataclass(frozen=True, slots=True)
class RefundTrendRow:
    amount_minor: int


@dataclass(frozen=True, slots=True)
class RefundLocationRow:
    location_id: UUID
    amount_minor: int


@dataclass(frozen=True, slots=True)
class DashboardAlert:
    code: str
    severity: AlertSeverity
    title: str
    message: str
    location_id: UUID | None
    entity_type: str | None
    entity_id: UUID | None
    action_href: str


@dataclass(frozen=True, slots=True)
class DashboardOverview:
    scope: DashboardScope
    sales: SalesBlock
    finance: FinanceBlock | None
    inventory: InventoryBlock
    payment_mix: tuple[PaymentMixRow, ...]
    trend: tuple[TrendPoint, ...]
    locations: tuple[LocationScorecardRow, ...]
    alerts: tuple[DashboardAlert, ...]
