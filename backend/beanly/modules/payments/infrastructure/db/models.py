from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from beanly.core.database.base import Base

JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


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
    organization_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    location_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("locations.id"), index=True)
    order_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("sales_orders.id"))
    shift_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("register_shifts.id"), index=True)
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
        UniqueConstraint("external_payment_attempt_id", name="uq_payment_lines_external_attempt"),
        CheckConstraint("method IN ('CASH', 'CARD', 'OTHER')", name="ck_payment_line_method"),
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
    external_payment_attempt_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("external_payment_attempts.id", ondelete="RESTRICT"),
        nullable=True,
    )
    provider_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    provider_transaction_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sort_order: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    payment: Mapped[PaymentModel] = relationship(back_populates="lines")


class TerminalBindingModel(Base):
    __tablename__ = "integration_terminal_bindings"
    __table_args__ = (
        UniqueConstraint("register_id", "provider_code"),
        Index("ix_terminal_bindings_organization_id", "organization_id"),
        Index("ix_terminal_bindings_location_id", "location_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE")
    )
    connection_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("integration_connections.id", ondelete="CASCADE")
    )
    location_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("locations.id", ondelete="CASCADE"))
    register_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("pos_registers.id", ondelete="CASCADE")
    )
    provider_code: Mapped[str] = mapped_column(String(80))
    external_terminal_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    transport_config: Mapped[dict[str, object]] = mapped_column(JSON_DOCUMENT, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class ExternalPaymentAttemptModel(Base):
    __tablename__ = "external_payment_attempts"
    __table_args__ = (
        UniqueConstraint("organization_id", "client_attempt_id"),
        CheckConstraint(
            "status IN ('CREATED','TERMINAL_PENDING','APPROVED','DECLINED','CANCELLED','UNKNOWN')",
            name="ck_external_payment_attempt_status",
        ),
        CheckConstraint("method IN ('CARD','QR')", name="ck_external_payment_attempt_method"),
        CheckConstraint("amount_minor > 0", name="ck_external_payment_attempt_amount"),
        CheckConstraint("length(currency_code) = 3", name="ck_external_payment_currency"),
        CheckConstraint(
            "(status = 'APPROVED' AND approved_at IS NOT NULL AND payment_id IS NOT NULL "
            "AND provider_operation_id IS NOT NULL AND provider_reference IS NOT NULL "
            "AND failed_at IS NULL AND failure_code IS NULL) OR "
            "(status <> 'APPROVED' AND approved_at IS NULL AND payment_id IS NULL)",
            name="ck_external_payment_attempt_approval",
        ),
        Index("ix_external_payment_attempts_org_created", "organization_id", "created_at"),
        Index("ix_external_payment_attempts_order", "order_id"),
        Index(
            "uq_external_payment_attempts_unresolved_order",
            "order_id",
            unique=True,
            postgresql_where=text("status IN ('CREATED','TERMINAL_PENDING','UNKNOWN')"),
            sqlite_where=text("status IN ('CREATED','TERMINAL_PENDING','UNKNOWN')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE")
    )
    location_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("locations.id", ondelete="CASCADE"))
    order_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("sales_orders.id"))
    register_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("pos_registers.id"))
    pos_device_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("pos_devices.id"), nullable=True
    )
    connection_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("integration_connections.id", ondelete="RESTRICT")
    )
    client_attempt_id: Mapped[UUID] = mapped_column(Uuid)
    provider_code: Mapped[str] = mapped_column(String(80))
    method: Mapped[str] = mapped_column(String(20))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    order_pricing_revision: Mapped[int | None] = mapped_column(nullable=True)
    currency_code: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(24), index=True)
    provider_operation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    created_by_user_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    payment_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("payments.id"), nullable=True, unique=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
