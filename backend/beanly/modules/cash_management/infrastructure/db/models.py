from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from beanly.core.database.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class CashDrawerSessionModel(Base):
    __tablename__ = "cash_drawer_sessions"
    __table_args__ = (
        UniqueConstraint("shift_id", name="uq_cash_drawer_shift"),
        UniqueConstraint("organization_id", "client_open_id", name="uq_cash_drawer_client_open"),
        CheckConstraint("status IN ('OPEN','CLOSING','CLOSED')", name="ck_cash_drawer_status"),
        CheckConstraint("starting_cash_minor >= 0", name="ck_cash_drawer_starting"),
        CheckConstraint("length(currency_code) = 3", name="ck_cash_drawer_currency"),
        CheckConstraint("version > 0", name="ck_cash_drawer_version"),
        Index("ix_cash_drawer_org_opened", "organization_id", "opened_at"),
        Index("ix_cash_drawer_location_status", "location_id", "status"),
        Index(
            "uq_cash_drawer_active_register",
            "register_id",
            unique=True,
            postgresql_where=text("status IN ('OPEN','CLOSING')"),
            sqlite_where=text("status IN ('OPEN','CLOSING')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    location_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("locations.id", ondelete="RESTRICT"), index=True
    )
    register_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("pos_registers.id", ondelete="RESTRICT"), index=True
    )
    shift_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("register_shifts.id", ondelete="RESTRICT")
    )
    currency_code: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(16), index=True)
    starting_cash_minor: Mapped[int] = mapped_column(BigInteger)
    expected_cash_minor_snapshot: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    actual_cash_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    variance_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    opened_by_user_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    close_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_open_id: Mapped[UUID] = mapped_column(Uuid)
    client_close_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    version: Mapped[int] = mapped_column(default=1)


class CashDrawerMovementModel(Base):
    __tablename__ = "cash_drawer_movements"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "source_type",
            "source_id",
            "source_line_id",
            name="uq_cash_drawer_movement_source",
        ),
        UniqueConstraint(
            "organization_id", "client_movement_id", name="uq_cash_drawer_movement_client"
        ),
        CheckConstraint(
            "kind IN ('OPENING_FLOAT','CASH_PAYMENT','CASH_REFUND','PAY_IN','PAY_OUT')",
            name="ck_cash_drawer_movement_kind",
        ),
        CheckConstraint(
            "amount_minor <> 0 OR kind = 'OPENING_FLOAT'", name="ck_cash_drawer_movement_amount"
        ),
        Index("ix_cash_drawer_movement_session_time", "drawer_session_id", "occurred_at"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    drawer_session_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("cash_drawer_sessions.id", ondelete="RESTRICT"), index=True
    )
    kind: Mapped[str] = mapped_column(String(24))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    source_type: Mapped[str] = mapped_column(String(40))
    source_id: Mapped[UUID] = mapped_column(Uuid)
    source_line_id: Mapped[UUID] = mapped_column(Uuid)
    client_movement_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CashDrawerCloseSnapshotModel(Base):
    __tablename__ = "cash_drawer_close_snapshots"
    __table_args__ = (
        UniqueConstraint("drawer_session_id", name="uq_cash_drawer_close_snapshot"),
        CheckConstraint("actual_cash_minor >= 0", name="ck_cash_close_actual"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    drawer_session_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("cash_drawer_sessions.id", ondelete="RESTRICT")
    )
    starting_cash_minor: Mapped[int] = mapped_column(BigInteger)
    cash_payments_minor: Mapped[int] = mapped_column(BigInteger)
    cash_refunds_minor: Mapped[int] = mapped_column(BigInteger)
    pay_in_minor: Mapped[int] = mapped_column(BigInteger)
    pay_out_minor: Mapped[int] = mapped_column(BigInteger)
    expected_cash_minor: Mapped[int] = mapped_column(BigInteger)
    actual_cash_minor: Mapped[int] = mapped_column(BigInteger)
    variance_minor: Mapped[int] = mapped_column(BigInteger)
    approval_threshold_minor: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CashDrawerFiscalStateModel(Base):
    __tablename__ = "cash_drawer_fiscal_states"
    __table_args__ = (UniqueConstraint("drawer_session_id", name="uq_cash_drawer_fiscal_state"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    drawer_session_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("cash_drawer_sessions.id", ondelete="RESTRICT")
    )
    fiscal_job_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("integration_jobs.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), default="NOT_REQUIRED")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
