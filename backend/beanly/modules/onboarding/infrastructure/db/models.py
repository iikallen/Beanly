from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from beanly.core.database.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


json_document = JSON().with_variant(JSONB, "postgresql")


class OnboardingStateModel(Base):
    __tablename__ = "onboarding_states"
    __table_args__ = (
        CheckConstraint(
            "status IN ('NOT_STARTED','IN_PROGRESS','READY_FOR_POS','COMPLETED')",
            name="ck_onboarding_state_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), unique=True
    )
    status: Mapped[str] = mapped_column(String(24))
    current_step: Mapped[str | None] = mapped_column(String(80), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class OnboardingImportRunModel(Base):
    __tablename__ = "onboarding_import_runs"
    __table_args__ = (
        UniqueConstraint("organization_id", "client_import_id", name="uq_onboarding_import_client"),
        CheckConstraint(
            "source_type IN ('BEANLY_TEMPLATE','BEANLY_SPREADSHEET',"
            "'GENERIC_SPREADSHEET','POSTER_EXPORT','AI_EXTRACTION')",
            name="ck_onboarding_import_source",
        ),
        CheckConstraint(
            "status IN ('UPLOADED','PARSING','NEEDS_REVIEW','READY','APPLYING',"
            "'APPLIED','FAILED','CANCELLED')",
            name="ck_onboarding_import_status",
        ),
        CheckConstraint("entity_count >= 0", name="ck_onboarding_import_entity_count"),
        CheckConstraint("error_count >= 0", name="ck_onboarding_import_error_count"),
        CheckConstraint("warning_count >= 0", name="ck_onboarding_import_warning_count"),
        Index("ix_onboarding_import_org_created", "organization_id", "created_at"),
        Index("ix_onboarding_import_org_status", "organization_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE")
    )
    location_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("locations.id", ondelete="RESTRICT"))
    client_import_id: Mapped[UUID] = mapped_column(Uuid)
    source_type: Mapped[str] = mapped_column(String(32))
    source_name: Mapped[str] = mapped_column(String(200))
    source_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(24))
    entity_count: Mapped[int] = mapped_column(default=0)
    error_count: Mapped[int] = mapped_column(default=0)
    warning_count: Mapped[int] = mapped_column(default=0)
    payload_hash: Mapped[str] = mapped_column(String(64))
    mapping: Mapped[dict[str, str]] = mapped_column(json_document, default=dict)
    created_by: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    entities: Mapped[list["OnboardingImportEntityModel"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class OnboardingImportEntityModel(Base):
    __tablename__ = "onboarding_import_entities"
    __table_args__ = (
        UniqueConstraint("import_run_id", "source_key", name="uq_onboarding_entity_source"),
        CheckConstraint(
            "entity_type IN ('CATEGORY','INVENTORY_ITEM','PRODUCT','VARIANT','RECIPE',"
            "'MODIFIER_GROUP','MODIFIER_OPTION','LOCATION_PRICE','OPENING_BALANCE')",
            name="ck_onboarding_entity_type",
        ),
        CheckConstraint(
            "resolution IN ('CREATE','MATCH_EXISTING','SKIP')",
            name="ck_onboarding_entity_resolution",
        ),
        CheckConstraint("sort_order >= 0", name="ck_onboarding_entity_sort_order"),
        Index("ix_onboarding_entity_run_order", "import_run_id", "sort_order"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    import_run_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("onboarding_import_runs.id", ondelete="CASCADE")
    )
    entity_type: Mapped[str] = mapped_column(String(32))
    source_key: Mapped[str] = mapped_column(String(255))
    payload: Mapped[dict[str, object]] = mapped_column(json_document)
    resolution: Mapped[str] = mapped_column(String(24))
    target_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    error_codes: Mapped[list[str]] = mapped_column(json_document, default=list)
    warning_codes: Mapped[list[str]] = mapped_column(json_document, default=list)
    sort_order: Mapped[int] = mapped_column(default=0)
    run: Mapped[OnboardingImportRunModel] = relationship(back_populates="entities")
