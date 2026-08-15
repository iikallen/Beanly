from datetime import UTC, datetime, time
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from beanly.core.database.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class ReservationLocationModel(Base):
    __tablename__ = "reservation_locations"
    __table_args__ = (
        UniqueConstraint("organization_id", "location_id", name="uq_reservation_location_scope"),
        UniqueConstraint("public_slug", name="uq_reservation_location_slug"),
        CheckConstraint(
            "default_duration_minutes BETWEEN 15 AND 480 AND "
            "cleanup_buffer_minutes BETWEEN 0 AND 240 AND "
            "minimum_lead_minutes BETWEEN 0 AND 43200 AND "
            "maximum_advance_days BETWEEN 1 AND 365 AND "
            "guest_cancellation_cutoff_minutes BETWEEN 0 AND 10080 AND "
            "maximum_party_size BETWEEN 1 AND 1000 AND "
            "slot_interval_minutes BETWEEN 5 AND 120",
            name="ck_reservation_location_policy",
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
    reservations_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    default_duration_minutes: Mapped[int] = mapped_column(SmallInteger, default=90)
    cleanup_buffer_minutes: Mapped[int] = mapped_column(SmallInteger, default=15)
    minimum_lead_minutes: Mapped[int] = mapped_column(Integer, default=60)
    maximum_advance_days: Mapped[int] = mapped_column(SmallInteger, default=30)
    guest_cancellation_cutoff_minutes: Mapped[int] = mapped_column(Integer, default=120)
    maximum_party_size: Mapped[int] = mapped_column(SmallInteger, default=12)
    slot_interval_minutes: Mapped[int] = mapped_column(SmallInteger, default=15)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    schedules: Mapped[list["ReservationScheduleModel"]] = relationship(cascade="all, delete-orphan")


class ReservationScheduleModel(Base):
    __tablename__ = "reservation_schedules"
    __table_args__ = (
        UniqueConstraint(
            "location_id",
            "weekday",
            "opens_at_local",
            "closes_at_local",
            name="uq_reservation_schedule_range",
        ),
        CheckConstraint("weekday BETWEEN 0 AND 6", name="ck_reservation_schedule_weekday"),
        CheckConstraint("opens_at_local <> closes_at_local", name="ck_reservation_schedule_time"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    settings_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("reservation_locations.id", ondelete="CASCADE")
    )
    organization_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    location_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    weekday: Mapped[int] = mapped_column(SmallInteger)
    opens_at_local: Mapped[time] = mapped_column(Time)
    closes_at_local: Mapped[time] = mapped_column(Time)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class DiningSectionModel(Base):
    __tablename__ = "dining_sections"
    __table_args__ = (
        UniqueConstraint("id", "organization_id", "location_id", name="uq_dining_section_scope"),
        UniqueConstraint("organization_id", "location_id", "name", name="uq_dining_section_name"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    location_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("locations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class DiningTableModel(Base):
    __tablename__ = "dining_tables"
    __table_args__ = (
        ForeignKeyConstraint(
            ["section_id", "organization_id", "location_id"],
            [
                "dining_sections.id",
                "dining_sections.organization_id",
                "dining_sections.location_id",
            ],
            name="fk_dining_table_section_scope",
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "organization_id", "location_id", name="uq_dining_table_scope"),
        UniqueConstraint(
            "organization_id",
            "location_id",
            "section_id",
            "name",
            name="uq_dining_table_name",
        ),
        CheckConstraint("capacity > 0", name="ck_dining_table_capacity_positive"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    location_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    section_id: Mapped[UUID] = mapped_column(Uuid)
    name: Mapped[str] = mapped_column(String(100))
    capacity: Mapped[int] = mapped_column(SmallInteger)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class ReservationModel(Base):
    __tablename__ = "reservations"
    _overlap = ExcludeConstraint(
        ("dining_table_id", "="),
        (text("tstzrange(start_at, conflict_end_at, '[)')"), "&&"),
        where=text("status = 'BOOKED'"),
        using="gist",
        name="ex_reservation_table_period_active",
    ).ddl_if(dialect="postgresql")
    __table_args__ = (
        ForeignKeyConstraint(
            ["dining_table_id", "organization_id", "location_id"],
            ["dining_tables.id", "dining_tables.organization_id", "dining_tables.location_id"],
            name="fk_reservation_table_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("organization_id", "client_reservation_id", name="uq_reservation_client"),
        UniqueConstraint("guest_access_token_hash", name="uq_reservation_guest_token"),
        CheckConstraint("party_size > 0", name="ck_reservation_party_positive"),
        CheckConstraint(
            "start_at < end_at AND end_at <= conflict_end_at",
            name="ck_reservation_period_order",
        ),
        CheckConstraint(
            "status IN ('BOOKED','SEATED','COMPLETED','CANCELLED','NO_SHOW')",
            name="ck_reservation_status",
        ),
        CheckConstraint("source IN ('GUEST','STAFF','POS')", name="ck_reservation_source"),
        _overlap,
        Index("ix_reservation_location_start", "location_id", "start_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    location_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    client_reservation_id: Mapped[UUID] = mapped_column(Uuid)
    guest_access_token_hash: Mapped[str] = mapped_column(String(64))
    guest_name: Mapped[str] = mapped_column(String(201))
    guest_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    guest_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    party_size: Mapped[int] = mapped_column(SmallInteger)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    conflict_end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    dining_table_id: Mapped[UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(16))
    guest_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    internal_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    seated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    no_show_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class WaitlistEntryModel(Base):
    __tablename__ = "waitlist_entries"
    __table_args__ = (
        UniqueConstraint("organization_id", "client_entry_id", name="uq_waitlist_client"),
        CheckConstraint("party_size > 0", name="ck_waitlist_party_positive"),
        CheckConstraint(
            "quoted_wait_minutes IS NULL OR quoted_wait_minutes >= 0",
            name="ck_waitlist_quote_nonnegative",
        ),
        CheckConstraint("status IN ('WAITING','SEATED','CANCELLED')", name="ck_waitlist_status"),
        Index("ix_waitlist_queue", "location_id", "status", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    location_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("locations.id", ondelete="CASCADE"), index=True
    )
    client_entry_id: Mapped[UUID] = mapped_column(Uuid)
    guest_name: Mapped[str] = mapped_column(String(201))
    guest_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    guest_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    party_size: Mapped[int] = mapped_column(SmallInteger)
    quoted_wait_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16))
    guest_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    seated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class DiningVisitModel(Base):
    __tablename__ = "dining_visits"
    __table_args__ = (
        ForeignKeyConstraint(
            ["dining_table_id", "organization_id", "location_id"],
            ["dining_tables.id", "dining_tables.organization_id", "dining_tables.location_id"],
            name="fk_dining_visit_table_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("organization_id", "client_action_id", name="uq_dining_visit_client"),
        UniqueConstraint("reservation_id", name="uq_dining_visit_reservation"),
        UniqueConstraint("waitlist_entry_id", name="uq_dining_visit_waitlist"),
        UniqueConstraint("sales_order_id", name="uq_dining_visit_sales_order"),
        CheckConstraint("party_size > 0", name="ck_dining_visit_party_positive"),
        CheckConstraint(
            "NOT (reservation_id IS NOT NULL AND waitlist_entry_id IS NOT NULL)",
            name="ck_dining_visit_single_origin",
        ),
        Index(
            "uq_dining_visit_active_table",
            "dining_table_id",
            unique=True,
            postgresql_where=text("closed_at IS NULL"),
            sqlite_where=text("closed_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    location_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    client_action_id: Mapped[UUID] = mapped_column(Uuid)
    dining_table_id: Mapped[UUID] = mapped_column(Uuid)
    reservation_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("reservations.id", ondelete="RESTRICT"), nullable=True
    )
    waitlist_entry_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("waitlist_entries.id", ondelete="RESTRICT"), nullable=True
    )
    sales_order_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("sales_orders.id", ondelete="RESTRICT"), nullable=True
    )
    party_size: Mapped[int] = mapped_column(SmallInteger)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
