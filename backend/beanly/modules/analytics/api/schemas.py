from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from beanly.modules.analytics.domain.enums import (
    ABCClass,
    HourMetric,
    MenuEngineeringClass,
    ProductGroupBy,
)


class AnalyticsModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AnalyticsOverviewResponse(AnalyticsModel):
    organization_id: UUID
    location_id: UUID | None
    date_from: date
    date_to: date
    currency_code: str
    revenue: Decimal
    gross_revenue: Decimal
    refund_amount: Decimal
    net_revenue: Decimal
    paid_orders: int
    items_sold: int
    average_check: Decimal
    cogs: Decimal | None
    gross_profit: Decimal | None
    gross_margin_percent: Decimal | None
    inventory_losses: Decimal | None
    incomplete_cogs_orders: int | None
    data_as_of: datetime | None


class ProductAnalyticsRowResponse(AnalyticsModel):
    product_id: UUID
    product_variant_id: UUID | None
    name: str
    variant_name: str | None
    quantity_sold: int
    revenue: Decimal
    gross_revenue: Decimal
    refund_amount: Decimal
    net_revenue: Decimal
    refunded_quantity: int
    net_quantity: int
    refund_orders: int
    orders: int
    cogs: Decimal | None
    gross_profit: Decimal | None
    gross_margin_percent: Decimal | None
    incomplete_cogs_orders: int | None


class ProductsAnalyticsResponse(AnalyticsModel):
    group_by: ProductGroupBy
    rows: tuple[ProductAnalyticsRowResponse, ...]
    data_as_of: datetime | None


class ABCThresholdsResponse(AnalyticsModel):
    a_max_cumulative_share: Decimal
    b_max_cumulative_share: Decimal


class ABCRowResponse(AnalyticsModel):
    product_id: UUID
    name: str
    revenue: Decimal
    revenue_share_percent: Decimal
    cumulative_share_percent: Decimal
    abc_class: ABCClass


class ABCAnalyticsResponse(AnalyticsModel):
    thresholds: ABCThresholdsResponse
    rows: tuple[ABCRowResponse, ...]
    data_as_of: datetime | None


class MenuEngineeringThresholdsResponse(AnalyticsModel):
    popularity_factor: Decimal
    expected_popularity_share_percent: Decimal
    high_popularity_share_percent: Decimal
    average_contribution_margin_per_item: Decimal


class MenuEngineeringRowResponse(AnalyticsModel):
    product_id: UUID
    name: str
    quantity_sold: int
    revenue: Decimal
    orders: int
    popularity_share_percent: Decimal
    contribution_margin_per_item: Decimal
    gross_margin_percent: Decimal | None
    classification: MenuEngineeringClass


class MenuEngineeringResponse(AnalyticsModel):
    thresholds: MenuEngineeringThresholdsResponse
    rows: tuple[MenuEngineeringRowResponse, ...]
    data_as_of: datetime | None


class HourAnalyticsRowResponse(AnalyticsModel):
    day_of_week: int
    local_hour: int
    value: Decimal


class HourAnalyticsResponse(AnalyticsModel):
    metric: HourMetric
    rows: tuple[HourAnalyticsRowResponse, ...]
    data_as_of: datetime | None


class InventoryConsumptionRowResponse(AnalyticsModel):
    inventory_item_id: UUID
    name: str
    base_unit: str
    sale_quantity: Decimal
    sale_cost_amount: Decimal | None
    writeoff_quantity: Decimal
    writeoff_cost_amount: Decimal | None
    adjustment_quantity: Decimal
    waste_rate_percent: Decimal | None


class InventoryConsumptionResponse(AnalyticsModel):
    rows: tuple[InventoryConsumptionRowResponse, ...]
    data_as_of: datetime | None


class LocationAnalyticsRowResponse(AnalyticsModel):
    location_id: UUID
    location_name: str
    revenue: Decimal
    gross_revenue: Decimal
    refund_amount: Decimal
    net_revenue: Decimal
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


class LocationAnalyticsResponse(AnalyticsModel):
    rows: tuple[LocationAnalyticsRowResponse, ...]
    data_as_of: datetime | None
