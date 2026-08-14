from datetime import datetime, time
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Time,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from beanly.core.database.base import Base


class PromotionModel(Base):
    __tablename__ = "promotions"
    __table_args__ = (
        CheckConstraint("status IN ('DRAFT','ACTIVE','ARCHIVED')", name="ck_promotions_status"),
        CheckConstraint(
            "application_mode IN ('AUTOMATIC','MANUAL','CODE')", name="ck_promotions_application"
        ),
        CheckConstraint(
            "discount_kind IN ('PERCENT','FIXED_AMOUNT','FIXED_PRICE','BOGO')",
            name="ck_promotions_kind",
        ),
        CheckConstraint("scope IN ('ORDER','ITEM','COMBO')", name="ck_promotions_scope"),
        CheckConstraint(
            "stacking_policy IN ('EXCLUSIVE','STACKABLE')", name="ck_promotions_stacking"
        ),
        CheckConstraint(
            "percent_rate IS NULL OR (percent_rate > 0 AND percent_rate <= 100)",
            name="ck_promotions_percent",
        ),
        CheckConstraint("amount_minor IS NULL OR amount_minor >= 0", name="ck_promotions_amount"),
        CheckConstraint(
            "fixed_price_minor IS NULL OR fixed_price_minor >= 0", name="ck_promotions_fixed_price"
        ),
        CheckConstraint(
            "minimum_subtotal_minor IS NULL OR minimum_subtotal_minor >= 0",
            name="ck_promotions_minimum",
        ),
        CheckConstraint(
            "maximum_discount_minor IS NULL OR maximum_discount_minor >= 0",
            name="ck_promotions_maximum",
        ),
        CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from",
            name="ck_promotions_dates",
        ),
        Index("ix_promotions_org_status", "organization_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(200))
    pos_name: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(16))
    application_mode: Mapped[str] = mapped_column(String(16))
    discount_kind: Mapped[str] = mapped_column(String(24))
    scope: Mapped[str] = mapped_column(String(16))
    percent_rate: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
    amount_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    fixed_price_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    priority: Mapped[int] = mapped_column(default=0)
    stacking_policy: Mapped[str] = mapped_column(String(16))
    include_modifier_price: Mapped[bool] = mapped_column(Boolean, default=False)
    minimum_subtotal_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    maximum_discount_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    all_locations: Mapped[bool] = mapped_column(Boolean, default=True)
    requires_override_permission: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    locations: Mapped[list["PromotionLocationModel"]] = relationship(cascade="all, delete-orphan")
    schedules: Mapped[list["PromotionScheduleModel"]] = relationship(cascade="all, delete-orphan")
    targets: Mapped[list["PromotionTargetModel"]] = relationship(cascade="all, delete-orphan")
    codes: Mapped[list["PromotionCodeModel"]] = relationship(cascade="all, delete-orphan")


class PromotionLocationModel(Base):
    __tablename__ = "promotion_locations"
    promotion_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("promotions.id", ondelete="CASCADE"), primary_key=True
    )
    location_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("locations.id", ondelete="CASCADE"), primary_key=True
    )


class PromotionScheduleModel(Base):
    __tablename__ = "promotion_schedules"
    __table_args__ = (
        CheckConstraint("weekday >= 0 AND weekday <= 6", name="ck_promotion_schedule_weekday"),
        CheckConstraint("start_local_time < end_local_time", name="ck_promotion_schedule_time"),
        UniqueConstraint(
            "promotion_id",
            "weekday",
            "start_local_time",
            "end_local_time",
            name="uq_promotion_schedule_range",
        ),
        Index("ix_promotion_schedules_promotion", "promotion_id"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    promotion_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("promotions.id", ondelete="CASCADE")
    )
    weekday: Mapped[int] = mapped_column(SmallInteger)
    start_local_time: Mapped[time] = mapped_column(Time)
    end_local_time: Mapped[time] = mapped_column(Time)


class PromotionTargetModel(Base):
    __tablename__ = "promotion_targets"
    __table_args__ = (
        CheckConstraint(
            "role IN ('ELIGIBLE','BUY','GET','COMBO_COMPONENT')", name="ck_promotion_target_role"
        ),
        CheckConstraint(
            "target_type IN ('CATEGORY','PRODUCT','VARIANT','ALL')", name="ck_promotion_target_type"
        ),
        CheckConstraint(
            "(target_type = 'ALL' AND target_id IS NULL) OR "
            "(target_type <> 'ALL' AND target_id IS NOT NULL)",
            name="ck_promotion_target_id",
        ),
        CheckConstraint("quantity > 0", name="ck_promotion_target_quantity"),
        CheckConstraint("sort_order >= 0", name="ck_promotion_target_sort"),
        Index("ix_promotion_targets_promotion", "promotion_id", "sort_order"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    promotion_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("promotions.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String(24))
    target_type: Mapped[str] = mapped_column(String(16))
    target_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    quantity: Mapped[int] = mapped_column(default=1)
    sort_order: Mapped[int] = mapped_column(default=0)


class PromotionCodeModel(Base):
    __tablename__ = "promotion_codes"
    __table_args__ = (
        UniqueConstraint("organization_id", "code_normalized", name="uq_promotion_codes_org_code"),
        CheckConstraint(
            "max_redemptions IS NULL OR max_redemptions > 0", name="ck_promotion_codes_max"
        ),
        CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from",
            name="ck_promotion_codes_dates",
        ),
        Index("ix_promotion_codes_promotion", "promotion_id"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE")
    )
    promotion_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("promotions.id", ondelete="CASCADE")
    )
    code_normalized: Mapped[str] = mapped_column(String(80))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    max_redemptions: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SalesOrderDiscountModel(Base):
    __tablename__ = "sales_order_discounts"
    __table_args__ = (
        UniqueConstraint("order_id", "client_discount_id", name="uq_order_discount_client"),
        CheckConstraint(
            "source IN ('AUTOMATIC','MANUAL','PROMO_CODE','CUSTOM')",
            name="ck_order_discount_source",
        ),
        CheckConstraint(
            "discount_kind IN ('PERCENT','FIXED_AMOUNT','FIXED_PRICE','BOGO')",
            name="ck_order_discount_kind",
        ),
        CheckConstraint("scope IN ('ORDER','ITEM','COMBO')", name="ck_order_discount_scope"),
        CheckConstraint("discount_total_minor >= 0", name="ck_order_discount_total"),
        CheckConstraint("sort_order >= 0", name="ck_order_discount_sort"),
        CheckConstraint(
            "audience_kind IS NULL OR audience_kind IN ('CUSTOMER','TIER','BIRTHDAY')",
            name="ck_order_discount_audience",
        ),
        Index("ix_sales_order_discounts_order", "order_id", "sort_order"),
        Index("ix_sales_order_discounts_promotion", "promotion_id"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    order_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("sales_orders.id", ondelete="CASCADE"))
    client_discount_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    promotion_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("promotions.id", ondelete="SET NULL"), nullable=True
    )
    source: Mapped[str] = mapped_column(String(16))
    promotion_name: Mapped[str] = mapped_column(String(200))
    discount_kind: Mapped[str] = mapped_column(String(24))
    scope: Mapped[str] = mapped_column(String(16))
    percent_rate: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
    configured_amount_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    promo_code_snapshot: Mapped[str | None] = mapped_column(String(80), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    applied_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    discount_total_minor: Mapped[int] = mapped_column(BigInteger)
    promotion_config_hash: Mapped[str] = mapped_column(String(64))
    sort_order: Mapped[int]
    audience_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    allocations: Mapped[list["SalesOrderDiscountAllocationModel"]] = relationship(
        cascade="all, delete-orphan"
    )


class SalesOrderDiscountAllocationModel(Base):
    __tablename__ = "sales_order_discount_allocations"
    __table_args__ = (
        UniqueConstraint(
            "order_discount_id", "order_item_id", name="uq_order_discount_allocation_item"
        ),
        CheckConstraint("eligible_amount_minor >= 0", name="ck_order_discount_allocation_eligible"),
        CheckConstraint(
            "discount_amount_minor >= 0 AND discount_amount_minor <= eligible_amount_minor",
            name="ck_order_discount_allocation_amount",
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    order_discount_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("sales_order_discounts.id", ondelete="CASCADE")
    )
    order_item_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("sales_order_items.id", ondelete="CASCADE")
    )
    eligible_amount_minor: Mapped[int] = mapped_column(BigInteger)
    discount_amount_minor: Mapped[int] = mapped_column(BigInteger)
    sort_order: Mapped[int]
