from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from beanly.core.database.base import Base

JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


def utc_now() -> datetime:
    return datetime.now(UTC)


class IntegrationConnectionModel(Base):
    __tablename__ = "integration_connections"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','ACTIVE','DEGRADED','REVOKED')",
            name="ck_integration_connection_status",
        ),
        CheckConstraint(
            "auth_type IN ('NONE','API_KEY','OAUTH2')",
            name="ck_integration_connection_auth",
        ),
        Index("ix_integration_connections_org_provider", "organization_id", "provider_code"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    provider_code: Mapped[str] = mapped_column(String(80))
    display_name: Mapped[str] = mapped_column(String(150))
    status: Mapped[str] = mapped_column(String(24), index=True)
    auth_type: Mapped[str] = mapped_column(String(24))
    config: Mapped[dict[str, object]] = mapped_column(JSON_DOCUMENT, default=dict)
    credentials_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    credentials_key_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    external_account_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_health_check_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class IntegrationLocationBindingModel(Base):
    __tablename__ = "integration_location_bindings"
    __table_args__ = (
        UniqueConstraint("connection_id", "location_id", "capability"),
        CheckConstraint(
            "capability IN ('PAYMENT','FISCAL','DELIVERY','NOTIFICATION')",
            name="ck_integration_binding_capability",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    connection_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("integration_connections.id", ondelete="CASCADE"), index=True
    )
    location_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("locations.id", ondelete="CASCADE"), index=True
    )
    capability: Mapped[str] = mapped_column(String(24))
    external_location_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    settings: Mapped[dict[str, object]] = mapped_column(JSON_DOCUMENT, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class IntegrationOAuthSessionModel(Base):
    __tablename__ = "integration_oauth_sessions"
    __table_args__ = (UniqueConstraint("state_hash"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    provider_code: Mapped[str] = mapped_column(String(80))
    state_hash: Mapped[str] = mapped_column(String(64))
    code_verifier_ciphertext: Mapped[str] = mapped_column(Text)
    redirect_uri: Mapped[str] = mapped_column(String(500))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class IntegrationJobModel(Base):
    __tablename__ = "integration_jobs"
    __table_args__ = (
        UniqueConstraint("connection_id", "idempotency_key"),
        CheckConstraint(
            "capability IN ('PAYMENT','FISCAL','DELIVERY','NOTIFICATION')",
            name="ck_integration_job_capability",
        ),
        CheckConstraint(
            "status IN ('PENDING','PROCESSING','RETRYING','SUCCESS','DEAD')",
            name="ck_integration_job_status",
        ),
        CheckConstraint("attempts >= 0", name="ck_integration_job_attempts"),
        CheckConstraint(
            "(locked_by IS NULL) = (locked_until IS NULL)",
            name="ck_integration_job_lock_pair",
        ),
        Index("ix_integration_jobs_claim", "status", "available_at", "locked_until"),
        Index("ix_integration_jobs_org_created", "organization_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    connection_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("integration_connections.id", ondelete="CASCADE"), index=True
    )
    location_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("locations.id", ondelete="CASCADE"), nullable=True
    )
    capability: Mapped[str] = mapped_column(String(24))
    job_type: Mapped[str] = mapped_column(String(100), index=True)
    source_event_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    source_type: Mapped[str] = mapped_column(String(80))
    source_id: Mapped[UUID] = mapped_column(Uuid)
    idempotency_key: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(24), index=True)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    locked_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dead_lettered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class IntegrationJobAttemptModel(Base):
    __tablename__ = "integration_job_attempts"
    __table_args__ = (UniqueConstraint("job_id", "attempt_number"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    job_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("integration_jobs.id", ondelete="CASCADE"), index=True
    )
    attempt_number: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str] = mapped_column(String(32))
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider_request_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)


class IntegrationInboxEventModel(Base):
    __tablename__ = "integration_inbox_events"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_event_id"),
        CheckConstraint("attempts >= 0", name="ck_integration_inbox_attempts"),
        CheckConstraint(
            "(locked_by IS NULL) = (locked_until IS NULL)",
            name="ck_integration_inbox_lock_pair",
        ),
        Index("ix_integration_inbox_claim", "available_at", "locked_until"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    connection_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("integration_connections.id", ondelete="CASCADE"), index=True
    )
    provider_code: Mapped[str] = mapped_column(String(80))
    external_event_id: Mapped[str] = mapped_column(String(255))
    event_type: Mapped[str] = mapped_column(String(150))
    payload: Mapped[dict[str, object]] = mapped_column(JSON_DOCUMENT)
    payload_hash: Mapped[str] = mapped_column(String(64))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    locked_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dead_lettered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
