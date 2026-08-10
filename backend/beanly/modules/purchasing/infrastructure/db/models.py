from datetime import UTC, datetime
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
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from beanly.core.database.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class SupplierModel(Base):
    __tablename__ = "suppliers"
    __table_args__ = (Index("ix_suppliers_organization_name", "organization_id", "name"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    contact_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tax_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class PurchaseOrderModel(Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        UniqueConstraint("organization_id", "number"),
        CheckConstraint(
            "status IN ('DRAFT', 'ORDERED', 'PARTIALLY_RECEIVED', 'RECEIVED', 'CANCELLED')",
            name="ck_purchase_order_status",
        ),
        Index(
            "ix_purchase_orders_organization_status_created",
            "organization_id",
            "status",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    location_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("locations.id"), index=True)
    warehouse_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("warehouses.id"), index=True)
    supplier_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("suppliers.id"), index=True)
    number: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), index=True)
    currency_code: Mapped[str] = mapped_column(String(3))
    ordered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class PurchaseOrderLineModel(Base):
    __tablename__ = "purchase_order_lines"
    __table_args__ = (
        UniqueConstraint("purchase_order_id", "inventory_item_id"),
        CheckConstraint("ordered_quantity > 0", name="ck_purchase_order_line_quantity"),
        CheckConstraint("base_quantity > 0", name="ck_purchase_order_line_base_quantity"),
        CheckConstraint("unit_multiplier > 0", name="ck_purchase_order_line_multiplier"),
        CheckConstraint("unit_price >= 0", name="ck_purchase_order_line_unit_price"),
        CheckConstraint("line_total_minor >= 0", name="ck_purchase_order_line_total"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    purchase_order_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("purchase_orders.id", ondelete="CASCADE"), index=True
    )
    inventory_item_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("inventory_items.id"), index=True
    )
    ordered_quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    base_quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    purchase_unit: Mapped[str] = mapped_column(String(50))
    unit_multiplier: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    line_total_minor: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class GoodsReceiptModel(Base):
    __tablename__ = "goods_receipts"
    __table_args__ = (
        UniqueConstraint("organization_id", "number"),
        UniqueConstraint("inventory_transaction_id"),
        CheckConstraint(
            "status IN ('DRAFT', 'POSTED', 'REVERSED')",
            name="ck_goods_receipt_status",
        ),
        Index(
            "ix_goods_receipts_organization_status_received",
            "organization_id",
            "status",
            "received_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    location_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("locations.id"), index=True)
    warehouse_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("warehouses.id"), index=True)
    purchase_order_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("purchase_orders.id"), nullable=True, index=True
    )
    supplier_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("suppliers.id"), index=True)
    number: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), index=True)
    document_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    posted_by: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reversed_by: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    inventory_transaction_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("inventory_transactions.id"), nullable=True
    )


class GoodsReceiptLineModel(Base):
    __tablename__ = "goods_receipt_lines"
    __table_args__ = (
        UniqueConstraint("goods_receipt_id", "inventory_item_id"),
        CheckConstraint("received_quantity > 0", name="ck_goods_receipt_line_quantity"),
        CheckConstraint("base_quantity > 0", name="ck_goods_receipt_line_base_quantity"),
        CheckConstraint("unit_multiplier > 0", name="ck_goods_receipt_line_multiplier"),
        CheckConstraint("unit_price >= 0", name="ck_goods_receipt_line_unit_price"),
        CheckConstraint("line_total_minor >= 0", name="ck_goods_receipt_line_total"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    goods_receipt_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("goods_receipts.id", ondelete="CASCADE"), index=True
    )
    purchase_order_line_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("purchase_order_lines.id"), nullable=True, index=True
    )
    inventory_item_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("inventory_items.id"), index=True
    )
    received_quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    base_quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    purchase_unit: Mapped[str] = mapped_column(String(50))
    unit_multiplier: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    line_total_minor: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SupplierReturnModel(Base):
    __tablename__ = "supplier_returns"
    __table_args__ = (
        UniqueConstraint("organization_id", "number"),
        UniqueConstraint("inventory_transaction_id"),
        CheckConstraint(
            "status IN ('DRAFT', 'POSTED', 'REVERSED')",
            name="ck_supplier_return_status",
        ),
        Index(
            "ix_supplier_returns_organization_status_returned",
            "organization_id",
            "status",
            "returned_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    location_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("locations.id"), index=True)
    warehouse_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("warehouses.id"), index=True)
    supplier_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("suppliers.id"), index=True)
    goods_receipt_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("goods_receipts.id"), nullable=True, index=True
    )
    number: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), index=True)
    document_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    returned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    posted_by: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reversed_by: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    inventory_transaction_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("inventory_transactions.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class SupplierReturnLineModel(Base):
    __tablename__ = "supplier_return_lines"
    __table_args__ = (
        UniqueConstraint("supplier_return_id", "inventory_item_id"),
        CheckConstraint("return_quantity > 0", name="ck_supplier_return_line_quantity"),
        CheckConstraint("base_quantity > 0", name="ck_supplier_return_line_base_quantity"),
        CheckConstraint("unit_multiplier > 0", name="ck_supplier_return_line_multiplier"),
        CheckConstraint("unit_price >= 0", name="ck_supplier_return_line_unit_price"),
        CheckConstraint("line_total_minor >= 0", name="ck_supplier_return_line_total"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    supplier_return_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("supplier_returns.id", ondelete="CASCADE"), index=True
    )
    goods_receipt_line_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("goods_receipt_lines.id"), nullable=True, index=True
    )
    inventory_item_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("inventory_items.id"), index=True
    )
    return_quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    base_quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    purchase_unit: Mapped[str] = mapped_column(String(50))
    unit_multiplier: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    line_total_minor: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
