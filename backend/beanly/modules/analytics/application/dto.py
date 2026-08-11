from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from beanly.modules.analytics.domain.enums import (
    ABCClass,
    HourMetric,
    MenuEngineeringClass,
    ProductGroupBy,
)


@dataclass(frozen=True, slots=True)
class SalesDailyDelta:
    organization_id: UUID
    location_id: UUID
    local_date: date
    timezone: str
    currency_code: str
    revenue_amount: Decimal
    paid_orders: int
    items_sold: int
    cogs_amount: Decimal
    incomplete_cogs_orders: int
    dine_in_orders: int
    takeaway_orders: int
    delivery_orders: int
    refund_amount: Decimal = Decimal(0)
    refund_count: int = 0
    refunded_items: int = 0


@dataclass(frozen=True, slots=True)
class ProductSalesDailyDelta:
    organization_id: UUID
    location_id: UUID
    local_date: date
    product_id: UUID
    product_variant_id: UUID
    product_name: str
    variant_name: str
    quantity_sold: int
    orders_count: int
    revenue_amount: Decimal
    cogs_amount: Decimal
    incomplete_cogs_orders: int
    refund_amount: Decimal = Decimal(0)
    refunded_quantity: int = 0
    refund_orders: int = 0


@dataclass(frozen=True, slots=True)
class HourlySalesDelta:
    organization_id: UUID
    location_id: UUID
    local_date: date
    local_hour: int
    revenue_amount: Decimal
    paid_orders: int
    items_sold: int
    cogs_amount: Decimal


@dataclass(frozen=True, slots=True)
class LocationMetricsDailyDelta:
    organization_id: UUID
    location_id: UUID
    local_date: date
    revenue_amount: Decimal = Decimal(0)
    paid_orders: int = 0
    items_sold: int = 0
    cogs_amount: Decimal = Decimal(0)
    operating_expenses: Decimal = Decimal(0)
    inventory_losses: Decimal = Decimal(0)
    inventory_gains: Decimal = Decimal(0)
    incomplete_cogs_orders: int = 0
    refund_amount: Decimal = Decimal(0)


@dataclass(frozen=True, slots=True)
class InventoryConsumptionDailyDelta:
    organization_id: UUID
    location_id: UUID
    warehouse_id: UUID
    local_date: date
    inventory_item_id: UUID
    inventory_item_name: str
    base_unit: str
    sale_quantity: Decimal = Decimal(0)
    sale_cost_amount: Decimal = Decimal(0)
    writeoff_quantity: Decimal = Decimal(0)
    writeoff_cost_amount: Decimal = Decimal(0)
    adjustment_quantity: Decimal = Decimal(0)


@dataclass(frozen=True, slots=True)
class AnalyticsOverview:
    organization_id: UUID
    location_id: UUID | None
    date_from: date
    date_to: date
    currency_code: str
    revenue: Decimal
    paid_orders: int
    items_sold: int
    average_check: Decimal
    cogs: Decimal | None
    gross_profit: Decimal | None
    gross_margin_percent: Decimal | None
    inventory_losses: Decimal | None
    incomplete_cogs_orders: int | None
    data_as_of: datetime | None
    gross_revenue: Decimal = Decimal(0)
    refund_amount: Decimal = Decimal(0)
    net_revenue: Decimal = Decimal(0)


@dataclass(frozen=True, slots=True)
class ProductAnalyticsRow:
    product_id: UUID
    product_variant_id: UUID | None
    name: str
    variant_name: str | None
    quantity_sold: int
    revenue: Decimal
    orders: int
    cogs: Decimal | None
    gross_profit: Decimal | None
    gross_margin_percent: Decimal | None
    incomplete_cogs_orders: int | None
    gross_revenue: Decimal = Decimal(0)
    refund_amount: Decimal = Decimal(0)
    net_revenue: Decimal = Decimal(0)
    refunded_quantity: int = 0
    net_quantity: int = 0
    refund_orders: int = 0


@dataclass(frozen=True, slots=True)
class ProductsAnalytics:
    group_by: ProductGroupBy
    rows: tuple[ProductAnalyticsRow, ...]
    data_as_of: datetime | None


@dataclass(frozen=True, slots=True)
class ABCThresholds:
    a_max_cumulative_share: Decimal = Decimal(80)
    b_max_cumulative_share: Decimal = Decimal(95)


@dataclass(frozen=True, slots=True)
class ABCRow:
    product_id: UUID
    name: str
    revenue: Decimal
    revenue_share_percent: Decimal
    cumulative_share_percent: Decimal
    abc_class: ABCClass


@dataclass(frozen=True, slots=True)
class ABCAnalytics:
    thresholds: ABCThresholds
    rows: tuple[ABCRow, ...]
    data_as_of: datetime | None


@dataclass(frozen=True, slots=True)
class MenuEngineeringThresholds:
    popularity_factor: Decimal
    expected_popularity_share_percent: Decimal
    high_popularity_share_percent: Decimal
    average_contribution_margin_per_item: Decimal


@dataclass(frozen=True, slots=True)
class MenuEngineeringRow:
    product_id: UUID
    name: str
    quantity_sold: int
    revenue: Decimal
    orders: int
    popularity_share_percent: Decimal
    contribution_margin_per_item: Decimal
    gross_margin_percent: Decimal | None
    classification: MenuEngineeringClass


@dataclass(frozen=True, slots=True)
class MenuEngineeringAnalytics:
    thresholds: MenuEngineeringThresholds
    rows: tuple[MenuEngineeringRow, ...]
    data_as_of: datetime | None


@dataclass(frozen=True, slots=True)
class HourAnalyticsRow:
    day_of_week: int
    local_hour: int
    value: Decimal


@dataclass(frozen=True, slots=True)
class HourAnalytics:
    metric: HourMetric
    rows: tuple[HourAnalyticsRow, ...]
    data_as_of: datetime | None


@dataclass(frozen=True, slots=True)
class InventoryConsumptionRow:
    inventory_item_id: UUID
    name: str
    base_unit: str
    sale_quantity: Decimal
    sale_cost_amount: Decimal | None
    writeoff_quantity: Decimal
    writeoff_cost_amount: Decimal | None
    adjustment_quantity: Decimal
    waste_rate_percent: Decimal | None


@dataclass(frozen=True, slots=True)
class InventoryConsumptionAnalytics:
    rows: tuple[InventoryConsumptionRow, ...]
    data_as_of: datetime | None


@dataclass(frozen=True, slots=True)
class LocationAnalyticsRow:
    location_id: UUID
    location_name: str
    revenue: Decimal
    paid_orders: int
    items_sold: int
    average_check: Decimal
    cogs: Decimal | None
    gross_profit: Decimal | None
    gross_margin_percent: Decimal | None
    operating_expenses: Decimal | None
    operating_profit: Decimal | None
    revenue_rank: int
    orders_rank: int
    average_check_rank: int
    gross_margin_rank: int | None
    operating_profit_rank: int | None
    gross_revenue: Decimal = Decimal(0)
    refund_amount: Decimal = Decimal(0)
    net_revenue: Decimal = Decimal(0)


@dataclass(frozen=True, slots=True)
class LocationAnalytics:
    rows: tuple[LocationAnalyticsRow, ...]
    data_as_of: datetime | None
