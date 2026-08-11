from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from beanly.core.database.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class PaymentModel(Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount_minor >= 0", name="ck_payment_amount_nonnegative"),
        UniqueConstraint("order_id"),
        UniqueConstraint("organization_id", "client_payment_id"),
        Index("ix_payments_completed_at", "completed_at"),
        Index(
            "ix_payments_dashboard_completed",
            "organization_id",
            "location_id",
            "completed_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id"), index=True
    )
    location_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("locations.id"), index=True)
    order_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("sales_orders.id"))
    shift_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("register_shifts.id"), index=True
    )
    offline_session_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("pos_offline_sessions.id"), nullable=True, index=True
    )
    client_payment_id: Mapped[UUID] = mapped_column(Uuid)
    currency_code: Mapped[str] = mapped_column(String(3))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    created_by_user_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    lines: Mapped[list["PaymentLineModel"]] = relationship(
        back_populates="payment", cascade="all, delete-orphan"
    )


class PaymentLineModel(Base):
    __tablename__ = "payment_lines"
    __table_args__ = (
        CheckConstraint(
            "method IN ('CASH', 'CARD', 'OTHER')", name="ck_payment_line_method"
        ),
        CheckConstraint("amount_minor >= 0", name="ck_payment_line_amount_nonnegative"),
        CheckConstraint("change_minor >= 0", name="ck_payment_line_change_nonnegative"),
        CheckConstraint("sort_order >= 0", name="ck_payment_line_sort_nonnegative"),
        CheckConstraint(
            "(method = 'CASH' AND cash_received_minor IS NOT NULL "
            "AND cash_received_minor >= amount_minor "
            "AND change_minor = cash_received_minor - amount_minor) "
            "OR (method IN ('CARD', 'OTHER') AND cash_received_minor IS NULL "
            "AND change_minor = 0)",
            name="ck_payment_line_cash_values",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    payment_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("payments.id", ondelete="CASCADE"), index=True
    )
    method: Mapped[str] = mapped_column(String(20), index=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    cash_received_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    change_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    reference: Mapped[str | None] = mapped_column(String(200), nullable=True)
    sort_order: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    payment: Mapped[PaymentModel] = relationship(back_populates="lines")
