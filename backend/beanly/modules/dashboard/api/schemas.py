from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from beanly.modules.dashboard.domain.enums import (
    AlertSeverity,
    DashboardPeriod,
    MetricDirection,
)


class DashboardModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class DateTimeRangeResponse(DashboardModel):
    date_from: datetime = Field(serialization_alias="from")
    date_to: datetime = Field(serialization_alias="to")


class DashboardScopeResponse(DashboardModel):
    organization_id: UUID
    location_id: UUID | None
    location_name: str
    timezone: str
    period: DashboardPeriod
    current: DateTimeRangeResponse
    previous: DateTimeRangeResponse


class DecimalMetricResponse(DashboardModel):
    current: Decimal
    previous: Decimal
    absolute_change: Decimal
    percent_change: Decimal | None
    direction: MetricDirection


class CountMetricResponse(DashboardModel):
    current: int
    previous: int
    absolute_change: int
    percent_change: Decimal | None
    direction: MetricDirection


class SalesResponse(DashboardModel):
    revenue: DecimalMetricResponse
    gross_sales_minor: str
    discount_amount_minor: str
    refund_amount_minor: str
    net_sales_minor: str
    paid_orders: CountMetricResponse
    average_check: DecimalMetricResponse
    open_orders: int
    open_shifts: int


class FinanceResponse(DashboardModel):
    currency_code: str
    cogs: Decimal
    gross_profit: Decimal
    gross_margin_percent: Decimal | None
    operating_expenses: Decimal
    inventory_losses: Decimal
    inventory_gains: Decimal
    operating_profit: Decimal
    operating_profit_comparison: DecimalMetricResponse
    net_cash_movement_minor: str
    incomplete_cogs_sales: int
    data_as_of: datetime | None


class NegativeStockItemResponse(DashboardModel):
    item_id: UUID
    location_id: UUID
    name: str
    quantity: Decimal
    unit_code: str


class InventoryResponse(DashboardModel):
    total_value: Decimal
    negative_stock_count: int
    active_count_count: int
    negative_items: tuple[NegativeStockItemResponse, ...]


class PaymentMixResponse(DashboardModel):
    method: str
    amount: Decimal
    share_percent: Decimal


class TrendPointResponse(DashboardModel):
    bucket_start: datetime
    revenue: Decimal
    orders: int
    gross_sales_minor: str
    discount_amount_minor: str
    refund_amount_minor: str
    net_sales_minor: str


class LocationScorecardResponse(DashboardModel):
    location_id: UUID
    location_name: str
    revenue: Decimal
    paid_orders: int
    average_check: Decimal
    operating_profit: Decimal | None
    gross_sales_minor: str
    discount_amount_minor: str
    refund_amount_minor: str
    net_sales_minor: str


class AlertResponse(DashboardModel):
    code: str
    severity: AlertSeverity
    title: str
    message: str
    location_id: UUID | None
    entity_type: str | None
    entity_id: UUID | None
    action_href: str


class DashboardOverviewResponse(DashboardModel):
    scope: DashboardScopeResponse
    sales: SalesResponse
    finance: FinanceResponse | None
    inventory: InventoryResponse
    payment_mix: tuple[PaymentMixResponse, ...]
    trend: tuple[TrendPointResponse, ...]
    locations: tuple[LocationScorecardResponse, ...]
    alerts: tuple[AlertResponse, ...]
