from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from beanly.core.database.base import Base
from beanly.modules.organizations.infrastructure.db import (
    models as organization_models,  # noqa: F401
)


def utc_now() -> datetime:
    return datetime.now(UTC)


class OutboxEventModel(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        CheckConstraint("event_version > 0", name="ck_outbox_event_version_positive"),
        CheckConstraint("attempts >= 0", name="ck_outbox_attempts_nonnegative"),
        CheckConstraint(
            "(locked_by IS NULL) = (locked_until IS NULL)",
            name="ck_outbox_lock_pair",
        ),
        CheckConstraint(
            "processed_at IS NULL OR dead_lettered_at IS NULL",
            name="ck_outbox_terminal_state",
        ),
        Index(
            "ix_outbox_pending",
            "available_at",
            "occurred_at",
            postgresql_where=text(
                "processed_at IS NULL AND dead_lettered_at IS NULL"
            ),
            sqlite_where=text("processed_at IS NULL AND dead_lettered_at IS NULL"),
        ),
        Index("ix_outbox_event_name", "event_name"),
        Index("ix_outbox_aggregate", "aggregate_type", "aggregate_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("organizations.id"), nullable=True, index=True
    )
    event_name: Mapped[str] = mapped_column(String(150))
    event_version: Mapped[int] = mapped_column(SmallInteger)
    aggregate_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    aggregate_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    payload: Mapped[dict[str, object]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql")
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    dead_lettered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
