from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
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
from sqlalchemy.orm import Mapped, mapped_column

from beanly.core.database.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class PosDeviceModel(Base):
    __tablename__ = "pos_devices"
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE', 'REVOKED')", name="ck_pos_device_status"),
        Index(
            "uq_pos_devices_active_register",
            "register_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
            sqlite_where=text("status = 'ACTIVE'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    location_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("locations.id"), index=True)
    register_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("pos_registers.id"), index=True)
    name: Mapped[str] = mapped_column(String(150))
    status: Mapped[str] = mapped_column(String(16), index=True)
    credential_hash: Mapped[str] = mapped_column(String(64), unique=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class PosCatalogSnapshotModel(Base):
    __tablename__ = "pos_catalog_snapshots"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    location_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("locations.id"), index=True)
    warehouse_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("warehouses.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    public_payload: Mapped[dict[str, object]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql")
    )
    private_payload: Mapped[dict[str, object]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql")
    )
    payload_hash: Mapped[str] = mapped_column(String(64), index=True)


class PosOfflineSessionModel(Base):
    __tablename__ = "pos_offline_sessions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ACTIVE', 'CLOSED', 'REVOKED', 'EXPIRED')",
            name="ck_pos_offline_session_status",
        ),
        Index(
            "uq_pos_offline_sessions_active_device",
            "device_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
            sqlite_where=text("status = 'ACTIVE'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    device_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("pos_devices.id"), index=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    location_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("locations.id"), index=True)
    register_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("pos_registers.id"), index=True)
    shift_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("register_shifts.id"), index=True)
    warehouse_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("warehouses.id"))
    actor_user_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    catalog_snapshot_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("pos_catalog_snapshots.id"))
    status: Mapped[str] = mapped_column(String(16), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PosOfflineOrderSyncModel(Base):
    __tablename__ = "pos_offline_order_syncs"
    __table_args__ = (
        UniqueConstraint("session_id", "client_order_id"),
        CheckConstraint(
            "last_client_revision > 0", name="ck_pos_order_sync_revision_positive"
        ),
        CheckConstraint("status IN ('SYNCED', 'CONFLICT')", name="ck_pos_order_sync_status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    session_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("pos_offline_sessions.id"), index=True
    )
    client_order_id: Mapped[UUID] = mapped_column(Uuid)
    server_order_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("sales_orders.id"), nullable=True
    )
    payment_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("payments.id"), nullable=True)
    server_order_number: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_client_revision: Mapped[int] = mapped_column()
    last_server_version: Mapped[int | None] = mapped_column(nullable=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
