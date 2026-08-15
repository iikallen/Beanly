from datetime import UTC, date, datetime, time
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from beanly.core.database.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class OnlineOrderingLocationModel(Base):
    __tablename__ = "online_ordering_locations"
    __table_args__ = (
        UniqueConstraint("organization_id", "location_id", name="uq_online_location_scope"),
        UniqueConstraint("public_slug", name="uq_online_location_slug"),
        CheckConstraint(
            "minimum_order_minor >= 0", name="ck_online_location_minimum_nonnegative"
        ),
        CheckConstraint(
            "maximum_order_minor IS NULL OR maximum_order_minor >= minimum_order_minor",
            name="ck_online_location_maximum_bounded",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    location_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("locations.id", ondelete="CASCADE"), index=True
    )
    public_slug: Mapped[str] = mapped_column(String(100))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    pickup_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    qr_dine_in_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    qr_auto_accept: Mapped[bool] = mapped_column(Boolean, default=False)
    register_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("pos_registers.id", ondelete="RESTRICT"), nullable=True
    )
    accepting_orders: Mapped[bool] = mapped_column(Boolean, default=True)
    manual_pause_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    paused_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    minimum_order_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    maximum_order_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    guest_name_required: Mapped[bool] = mapped_column(Boolean, default=False)
    guest_phone_required_pickup: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    schedules: Mapped[list["OnlineOrderingScheduleModel"]] = relationship(
        cascade="all, delete-orphan"
    )


class OnlineOrderingScheduleModel(Base):
    __tablename__ = "online_ordering_schedules"
    __table_args__ = (
        UniqueConstraint(
            "location_id", "weekday", "opens_at_local", "closes_at_local",
            name="uq_online_schedule_range",
        ),
        CheckConstraint("weekday BETWEEN 0 AND 6", name="ck_online_schedule_weekday"),
        CheckConstraint("opens_at_local <> closes_at_local", name="ck_online_schedule_time"),
        Index("ix_online_schedule_location_weekday", "location_id", "weekday"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    location_config_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("online_ordering_locations.id", ondelete="CASCADE")
    )
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    location_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("locations.id", ondelete="CASCADE")
    )
    weekday: Mapped[int] = mapped_column(SmallInteger)
    opens_at_local: Mapped[time] = mapped_column(Time)
    closes_at_local: Mapped[time] = mapped_column(Time)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class OrderingStationModel(Base):
    __tablename__ = "online_ordering_stations"
    __table_args__ = (
        UniqueConstraint("public_token_hash", name="uq_online_station_token"),
        CheckConstraint(
            "kind IN ('TABLE','COUNTER','PICKUP_SPOT')", name="ck_online_station_kind"
        ),
        Index("ix_online_station_location_active", "location_id", "is_active"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    location_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("locations.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16))
    label: Mapped[str] = mapped_column(String(100))
    public_token_hash: Mapped[str] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class OnlineOrderModel(Base):
    __tablename__ = "online_orders"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "client_order_id", name="uq_online_order_client"
        ),
        UniqueConstraint("sales_order_id", name="uq_online_order_sales_order"),
        UniqueConstraint("status_token_hash", name="uq_online_order_status_token"),
        CheckConstraint("source IN ('ONLINE','QR')", name="ck_online_order_source"),
        CheckConstraint(
            "status IN ('PENDING','AWAITING_PAYMENT','PAID','PREPARING','READY',"
            "'COMPLETED','REJECTED','CANCELLED')",
            name="ck_online_order_status",
        ),
        CheckConstraint(
            "subtotal_minor >= 0 AND discount_minor >= 0 AND total_minor >= 0 "
            "AND discount_minor <= subtotal_minor "
            "AND total_minor = subtotal_minor - discount_minor",
            name="ck_online_order_money",
        ),
        Index("ix_online_order_location_status", "location_id", "status", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    location_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("locations.id", ondelete="RESTRICT"), index=True
    )
    sales_order_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("sales_orders.id", ondelete="RESTRICT"), index=True
    )
    station_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("online_ordering_stations.id", ondelete="RESTRICT"), nullable=True
    )
    client_order_id: Mapped[UUID] = mapped_column(Uuid)
    payload_hash: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24), index=True)
    guest_name_snapshot: Mapped[str | None] = mapped_column(String(201), nullable=True)
    guest_phone_snapshot: Mapped[str | None] = mapped_column(String(32), nullable=True)
    station_label_snapshot: Mapped[str | None] = mapped_column(String(100), nullable=True)
    subtotal_minor: Mapped[int] = mapped_column(BigInteger)
    discount_minor: Mapped[int] = mapped_column(BigInteger)
    total_minor: Mapped[int] = mapped_column(BigInteger)
    quote_revision: Mapped[str] = mapped_column(String(96))
    status_token_hash: Mapped[str] = mapped_column(String(64))
    accepted_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    cancelled_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    preparing_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    actions: Mapped[list["OnlineOrderActionModel"]] = relationship(
        cascade="all, delete-orphan"
    )


class OnlineOrderActionModel(Base):
    __tablename__ = "online_order_actions"
    __table_args__ = (
        Index(
            "uq_online_order_action_client",
            "organization_id",
            "client_action_id",
            unique=True,
            postgresql_where=text("client_action_id IS NOT NULL"),
            sqlite_where=text("client_action_id IS NOT NULL"),
        ),
        Index(
            "uq_online_order_action_event",
            "organization_id",
            "source_event_id",
            unique=True,
            postgresql_where=text("source_event_id IS NOT NULL"),
            sqlite_where=text("source_event_id IS NOT NULL"),
        ),
        Index("ix_online_order_actions_order", "online_order_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    online_order_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("online_orders.id", ondelete="CASCADE")
    )
    action_type: Mapped[str] = mapped_column(String(32))
    from_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    to_status: Mapped[str] = mapped_column(String(24))
    actor_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    client_action_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    source_event_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
