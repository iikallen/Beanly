from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from beanly.core.database.base import Base

if TYPE_CHECKING:
    from beanly.modules.promotions.infrastructure.db.models import SalesOrderDiscountModel


def utc_now() -> datetime:
    return datetime.now(UTC)


class PosRegisterModel(Base):
    __tablename__ = "pos_registers"
    __table_args__ = (UniqueConstraint("organization_id", "location_id", "name"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    location_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("locations.id"), index=True)
    name: Mapped[str] = mapped_column(String(150))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by_user_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class RegisterShiftModel(Base):
    __tablename__ = "register_shifts"
    __table_args__ = (
        CheckConstraint("status IN ('OPEN', 'CLOSING', 'CLOSED')", name="ck_register_shift_status"),
        Index(
            "uq_register_shifts_open_register",
            "register_id",
            unique=True,
            postgresql_where=text("status IN ('OPEN','CLOSING')"),
            sqlite_where=text("status IN ('OPEN','CLOSING')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    location_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("locations.id"), index=True)
    register_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("pos_registers.id"), index=True)
    warehouse_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("warehouses.id"))
    status: Mapped[str] = mapped_column(String(16), index=True)
    opened_by_user_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    closed_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class SalesOrderModel(Base):
    __tablename__ = "sales_orders"
    __table_args__ = (
        UniqueConstraint("organization_id", "client_order_id"),
        CheckConstraint(
            "order_type IN ('DINE_IN', 'TAKEAWAY', 'DELIVERY')",
            name="ck_sales_order_type",
        ),
        CheckConstraint(
            "order_source IN ('POS', 'ONLINE', 'QR')", name="ck_sales_order_source"
        ),
        CheckConstraint("status IN ('OPEN', 'PAID', 'CANCELLED')", name="ck_sales_order_status"),
        CheckConstraint("guest_count IS NULL OR guest_count > 0", name="ck_order_guest_count"),
        CheckConstraint("subtotal_minor >= 0", name="ck_order_subtotal_nonnegative"),
        CheckConstraint("total_minor >= 0", name="ck_order_total_nonnegative"),
        CheckConstraint(
            "cogs_amount IS NULL OR cogs_amount >= 0",
            name="ck_sales_order_cogs_nonnegative",
        ),
        CheckConstraint(
            "cogs_status IS NULL OR cogs_status IN ('COMPLETE', 'INCOMPLETE', 'ESTIMATED')",
            name="ck_sales_order_cogs_status",
        ),
        CheckConstraint("version > 0", name="ck_sales_order_version_positive"),
        CheckConstraint("discount_total_minor >= 0", name="ck_sales_order_discount_nonnegative"),
        CheckConstraint(
            "discount_total_minor <= subtotal_minor", name="ck_sales_order_discount_bounded"
        ),
        CheckConstraint("pricing_revision > 0", name="ck_sales_order_pricing_revision"),
        UniqueConstraint("inventory_transaction_id"),
        Index("ix_sales_orders_organization_created", "organization_id", "created_at"),
        Index(
            "ix_sales_orders_dashboard_paid",
            "organization_id",
            "location_id",
            "paid_at",
            postgresql_where=text("status = 'PAID'"),
            sqlite_where=text("status = 'PAID'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    location_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("locations.id"), index=True)
    shift_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("register_shifts.id"), index=True)
    warehouse_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("warehouses.id"))
    customer_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    customer_name_snapshot: Mapped[str | None] = mapped_column(String(201), nullable=True)
    customer_phone_snapshot: Mapped[str | None] = mapped_column(String(32), nullable=True)
    number: Mapped[int] = mapped_column(BigInteger)
    client_order_id: Mapped[UUID] = mapped_column(Uuid)
    version: Mapped[int] = mapped_column(default=1)
    pos_device_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("pos_devices.id"), nullable=True, index=True
    )
    offline_session_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("pos_offline_sessions.id"), nullable=True, index=True
    )
    client_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    offline_display_number: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    order_type: Mapped[str] = mapped_column(String(16))
    order_source: Mapped[str] = mapped_column(
        String(16), default="POS", server_default="POS", index=True
    )
    status: Mapped[str] = mapped_column(String(16), index=True)
    currency_code: Mapped[str] = mapped_column(String(3))
    guest_count: Mapped[int | None] = mapped_column(nullable=True)
    table_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    subtotal_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    total_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    discount_total_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    pricing_revision: Mapped[int] = mapped_column(default=1)
    priced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    cancelled_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    paid_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    inventory_transaction_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("inventory_transactions.id"), nullable=True
    )
    cogs_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    cogs_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    items: Mapped[list["SalesOrderItemModel"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    discounts: Mapped[list["SalesOrderDiscountModel"]] = relationship(cascade="all, delete-orphan")


class SalesOrderItemModel(Base):
    __tablename__ = "sales_order_items"
    __table_args__ = (
        UniqueConstraint("order_id", "client_item_id"),
        CheckConstraint("quantity > 0", name="ck_sales_order_item_quantity"),
        CheckConstraint("base_price_minor >= 0", name="ck_order_item_base_price"),
        CheckConstraint("modifier_price_minor >= 0", name="ck_order_item_modifier_price"),
        CheckConstraint("unit_price_minor >= 0", name="ck_order_item_unit_price"),
        CheckConstraint("line_total_minor >= 0", name="ck_order_item_line_total"),
        CheckConstraint("discount_amount_minor >= 0", name="ck_order_item_discount_nonnegative"),
        CheckConstraint(
            "discount_amount_minor <= line_total_minor", name="ck_order_item_discount_bounded"
        ),
        CheckConstraint("net_line_total_minor >= 0", name="ck_order_item_net_nonnegative"),
        CheckConstraint(
            "net_line_total_minor = line_total_minor - discount_amount_minor",
            name="ck_order_item_net_reconciles",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    order_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("sales_orders.id", ondelete="CASCADE"), index=True
    )
    client_item_id: Mapped[UUID] = mapped_column(Uuid)
    product_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("products.id"))
    product_variant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("product_variants.id"), index=True
    )
    product_name: Mapped[str] = mapped_column(String(200))
    variant_name: Mapped[str] = mapped_column(String(100))
    quantity: Mapped[int] = mapped_column()
    base_price_minor: Mapped[int] = mapped_column(BigInteger)
    modifier_price_minor: Mapped[int] = mapped_column(BigInteger)
    unit_price_minor: Mapped[int] = mapped_column(BigInteger)
    line_total_minor: Mapped[int] = mapped_column(BigInteger)
    discount_amount_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    net_line_total_minor: Mapped[int] = mapped_column(BigInteger)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    order: Mapped[SalesOrderModel] = relationship(back_populates="items")
    modifiers: Mapped[list["SalesOrderItemModifierModel"]] = relationship(
        back_populates="order_item", cascade="all, delete-orphan"
    )
    components: Mapped[list["SalesOrderItemComponentModel"]] = relationship(
        back_populates="order_item", cascade="all, delete-orphan"
    )


class SalesOrderItemModifierModel(Base):
    __tablename__ = "sales_order_item_modifiers"
    __table_args__ = (UniqueConstraint("order_item_id", "modifier_option_id"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    order_item_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("sales_order_items.id", ondelete="CASCADE"), index=True
    )
    modifier_group_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("modifier_groups.id"))
    modifier_group_name: Mapped[str] = mapped_column(String(150))
    modifier_option_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("modifier_options.id"))
    modifier_option_name: Mapped[str] = mapped_column(String(150))
    price_delta_minor: Mapped[int] = mapped_column(BigInteger)
    sort_order: Mapped[int] = mapped_column(default=0)
    order_item: Mapped[SalesOrderItemModel] = relationship(back_populates="modifiers")


class SalesOrderItemComponentModel(Base):
    __tablename__ = "sales_order_item_components"
    __table_args__ = (
        UniqueConstraint("order_item_id", "inventory_item_id"),
        CheckConstraint("quantity_per_unit > 0", name="ck_order_item_component_quantity"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    order_item_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("sales_order_items.id", ondelete="CASCADE"), index=True
    )
    inventory_item_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("inventory_items.id"))
    inventory_item_name: Mapped[str] = mapped_column(String(200))
    base_unit: Mapped[str] = mapped_column(String(16))
    quantity_per_unit: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    order_item: Mapped[SalesOrderItemModel] = relationship(back_populates="components")
