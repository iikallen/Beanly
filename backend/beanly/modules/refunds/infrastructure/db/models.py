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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from beanly.core.database.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class RefundModel(Base):
    __tablename__ = "refunds"
    __table_args__ = (
        UniqueConstraint("organization_id", "client_refund_id"),
        CheckConstraint("status IN ('PENDING','COMPLETED','FAILED')", name="ck_refund_status"),
        CheckConstraint(
            "reason IN ('QUALITY_ISSUE','WRONG_ITEM','ORDER_ERROR','CUSTOMER_RETURN',"
            "'DUPLICATE_PAYMENT','GOODWILL','OTHER')",
            name="ck_refund_reason",
        ),
        CheckConstraint("length(currency_code) = 3", name="ck_refund_currency"),
        CheckConstraint("total_amount_minor > 0", name="ck_refund_total_positive"),
        CheckConstraint("cogs_reversal_amount >= 0", name="ck_refund_cogs_nonnegative"),
        CheckConstraint(
            "cogs_quality_status IS NULL OR cogs_quality_status IN "
            "('COMPLETE','INCOMPLETE','ESTIMATED')",
            name="ck_refund_cogs_quality",
        ),
        Index("ix_refunds_org_created", "organization_id", "created_at"),
        Index("ix_refunds_payment", "payment_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    location_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("locations.id"), index=True)
    order_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("sales_orders.id"), index=True)
    payment_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("payments.id"), index=True)
    client_refund_id: Mapped[UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(16), index=True)
    reason: Mapped[str] = mapped_column(String(32))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    currency_code: Mapped[str] = mapped_column(String(3))
    total_amount_minor: Mapped[int] = mapped_column(BigInteger)
    inventory_transaction_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("inventory_transactions.id"), nullable=True, unique=True
    )
    cogs_reversal_amount: Mapped[Decimal] = mapped_column(Numeric(20, 6), default=Decimal(0))
    cogs_quality_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_by_user_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lines: Mapped[list["RefundLineModel"]] = relationship(
        back_populates="refund", cascade="all, delete-orphan"
    )
    payment_lines: Mapped[list["RefundPaymentLineModel"]] = relationship(
        back_populates="refund", cascade="all, delete-orphan"
    )


class RefundLineModel(Base):
    __tablename__ = "refund_lines"
    __table_args__ = (
        UniqueConstraint("refund_id", "order_item_id"),
        CheckConstraint("quantity > 0", name="ck_refund_line_quantity"),
        CheckConstraint(
            "restock_quantity >= 0 AND restock_quantity <= quantity", name="ck_refund_line_restock"
        ),
        CheckConstraint("unit_refund_minor >= 0", name="ck_refund_line_unit_amount"),
        CheckConstraint("total_refund_minor >= 0", name="ck_refund_line_total"),
        CheckConstraint(
            "gross_refund_minor >= 0 AND discount_refund_minor >= 0 AND "
            "net_refund_minor >= 0 AND "
            "net_refund_minor = gross_refund_minor - discount_refund_minor AND "
            "total_refund_minor = net_refund_minor",
            name="ck_refund_line_discount_values",
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    refund_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("refunds.id", ondelete="CASCADE"), index=True
    )
    order_item_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("sales_order_items.id"), index=True
    )
    quantity: Mapped[int] = mapped_column()
    restock_quantity: Mapped[int] = mapped_column()
    unit_refund_minor: Mapped[int] = mapped_column(BigInteger)
    total_refund_minor: Mapped[int] = mapped_column(BigInteger)
    gross_refund_minor: Mapped[int] = mapped_column(BigInteger)
    discount_refund_minor: Mapped[int] = mapped_column(BigInteger)
    net_refund_minor: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    refund: Mapped[RefundModel] = relationship(back_populates="lines")


class RefundDiscountAllocationModel(Base):
    __tablename__ = "refund_discount_allocations"
    __table_args__ = (
        UniqueConstraint(
            "refund_line_id", "order_discount_id", name="uq_refund_discount_allocation"
        ),
        CheckConstraint("discount_amount_minor >= 0", name="ck_refund_discount_allocation_amount"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    refund_line_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("refund_lines.id", ondelete="CASCADE")
    )
    order_discount_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("sales_order_discounts.id"))
    discount_amount_minor: Mapped[int] = mapped_column(BigInteger)


class RefundPaymentLineModel(Base):
    __tablename__ = "refund_payment_lines"
    __table_args__ = (
        UniqueConstraint("refund_id", "original_payment_line_id"),
        CheckConstraint("method IN ('CASH','CARD','OTHER')", name="ck_refund_payment_method"),
        CheckConstraint("amount_minor > 0", name="ck_refund_payment_amount"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    refund_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("refunds.id", ondelete="CASCADE"), index=True
    )
    original_payment_line_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("payment_lines.id"), index=True
    )
    method: Mapped[str] = mapped_column(String(20))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    external_refund_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    reference: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    refund: Mapped[RefundModel] = relationship(back_populates="payment_lines")
