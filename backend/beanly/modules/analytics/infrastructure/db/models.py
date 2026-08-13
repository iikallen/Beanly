from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from beanly.core.database.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class AnalyticsProjectionReceiptModel(Base):
    __tablename__ = "analytics_projection_receipts"
    __table_args__ = (
        Index(
            "ix_analytics_receipts_org_occurred",
            "organization_id",
            "source_occurred_at",
        ),
    )

    projection_name: Mapped[str] = mapped_column(String(80), primary_key=True)
    source_type: Mapped[str] = mapped_column(String(80), primary_key=True)
    source_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE")
    )
    source_event_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    source_occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    projected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AnalyticsSalesDailyModel(Base):
    __tablename__ = "analytics_sales_daily"
    __table_args__ = (
        CheckConstraint("length(currency_code) = 3", name="ck_an_sales_currency"),
        Index("ix_an_sales_org_date", "organization_id", "local_date"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    location_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("locations.id", ondelete="CASCADE"), primary_key=True
    )
    local_date: Mapped[date] = mapped_column(Date, primary_key=True)
    timezone: Mapped[str] = mapped_column(String(64))
    currency_code: Mapped[str] = mapped_column(String(3))
    revenue_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), default=Decimal(0), server_default=text("0")
    )
    gross_revenue_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), default=Decimal(0), server_default=text("0")
    )
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), default=Decimal(0), server_default=text("0")
    )
    refund_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), default=Decimal(0), server_default=text("0")
    )
    refund_count: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    refunded_items: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    paid_orders: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    items_sold: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    cogs_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), default=Decimal(0), server_default=text("0")
    )
    incomplete_cogs_orders: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default=text("0")
    )
    dine_in_orders: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    takeaway_orders: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    delivery_orders: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AnalyticsProductSalesDailyModel(Base):
    __tablename__ = "analytics_product_sales_daily"
    __table_args__ = (
        Index(
            "ix_an_product_org_location_date",
            "organization_id",
            "location_id",
            "local_date",
        ),
        Index("ix_an_product_product", "product_id"),
        Index("ix_an_product_variant", "product_variant_id"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    location_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("locations.id", ondelete="CASCADE"), primary_key=True
    )
    local_date: Mapped[date] = mapped_column(Date, primary_key=True)
    product_id: Mapped[UUID] = mapped_column(Uuid)
    product_variant_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    product_name: Mapped[str] = mapped_column(String(200))
    variant_name: Mapped[str] = mapped_column(String(100))
    quantity_sold: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    orders_count: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    revenue_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), default=Decimal(0), server_default=text("0")
    )
    gross_revenue_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), default=Decimal(0), server_default=text("0")
    )
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), default=Decimal(0), server_default=text("0")
    )
    refund_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), default=Decimal(0), server_default=text("0")
    )
    refunded_quantity: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    refund_orders: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    cogs_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), default=Decimal(0), server_default=text("0")
    )
    incomplete_cogs_orders: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default=text("0")
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AnalyticsPromotionsDailyModel(Base):
    __tablename__ = "analytics_promotions_daily"
    __table_args__ = (
        CheckConstraint("orders_count >= 0", name="ck_analytics_promotion_orders"),
        Index("ix_analytics_promotions_org_date", "organization_id", "local_date"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    location_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("locations.id", ondelete="CASCADE"), primary_key=True
    )
    local_date: Mapped[date] = mapped_column(Date, primary_key=True)
    promotion_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    promotion_name: Mapped[str] = mapped_column(String(200))
    orders_count: Mapped[int] = mapped_column(BigInteger, default=0)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(20, 6), default=Decimal(0))
    gross_revenue_amount: Mapped[Decimal] = mapped_column(Numeric(20, 6), default=Decimal(0))
    net_revenue_amount: Mapped[Decimal] = mapped_column(Numeric(20, 6), default=Decimal(0))
    refunded_discount_amount: Mapped[Decimal] = mapped_column(Numeric(20, 6), default=Decimal(0))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AnalyticsHourlySalesModel(Base):
    __tablename__ = "analytics_hourly_sales"
    __table_args__ = (
        CheckConstraint("local_hour BETWEEN 0 AND 23", name="ck_an_hour_local_hour"),
        Index("ix_an_hour_org_date", "organization_id", "local_date"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    location_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("locations.id", ondelete="CASCADE"), primary_key=True
    )
    local_date: Mapped[date] = mapped_column(Date, primary_key=True)
    local_hour: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    revenue_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), default=Decimal(0), server_default=text("0")
    )
    paid_orders: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    items_sold: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    cogs_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), default=Decimal(0), server_default=text("0")
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AnalyticsLocationMetricsDailyModel(Base):
    __tablename__ = "analytics_location_metrics_daily"
    __table_args__ = (Index("ix_an_location_org_date", "organization_id", "local_date"),)

    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    location_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("locations.id", ondelete="CASCADE"), primary_key=True
    )
    local_date: Mapped[date] = mapped_column(Date, primary_key=True)
    revenue_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), default=Decimal(0), server_default=text("0")
    )
    refund_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), default=Decimal(0), server_default=text("0")
    )
    paid_orders: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    items_sold: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    cogs_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), default=Decimal(0), server_default=text("0")
    )
    operating_expenses: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), default=Decimal(0), server_default=text("0")
    )
    inventory_losses: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), default=Decimal(0), server_default=text("0")
    )
    inventory_gains: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), default=Decimal(0), server_default=text("0")
    )
    incomplete_cogs_orders: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default=text("0")
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AnalyticsInventoryConsumptionDailyModel(Base):
    __tablename__ = "analytics_inventory_consumption_daily"
    __table_args__ = (
        Index(
            "ix_an_consumption_org_location_date",
            "organization_id",
            "location_id",
            "local_date",
        ),
        Index("ix_an_consumption_item", "inventory_item_id"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    location_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("locations.id", ondelete="CASCADE"), primary_key=True
    )
    warehouse_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("warehouses.id", ondelete="CASCADE"), primary_key=True
    )
    local_date: Mapped[date] = mapped_column(Date, primary_key=True)
    inventory_item_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    inventory_item_name: Mapped[str] = mapped_column(String(200))
    base_unit: Mapped[str] = mapped_column(String(16))
    sale_quantity: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), default=Decimal(0), server_default=text("0")
    )
    sale_cost_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), default=Decimal(0), server_default=text("0")
    )
    writeoff_quantity: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), default=Decimal(0), server_default=text("0")
    )
    writeoff_cost_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), default=Decimal(0), server_default=text("0")
    )
    adjustment_quantity: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), default=Decimal(0), server_default=text("0")
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
