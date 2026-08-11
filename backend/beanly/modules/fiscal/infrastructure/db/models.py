from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from beanly.core.database.base import Base

JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")
_NKT_DIGITS = " AND ".join(
    f"substr(ntin, {position}, 1) BETWEEN '0' AND '9'" for position in range(1, 14)
)


def utc_now() -> datetime:
    return datetime.now(UTC)


class FiscalTaxProfileModel(Base):
    __tablename__ = "fiscal_tax_profiles"
    __table_args__ = (
        CheckConstraint("length(country_code) = 2", name="ck_fiscal_tax_country"),
        CheckConstraint(
            "(vat_registered = false) OR (default_vat_rate IS NOT NULL AND default_vat_rate > 0)",
            name="ck_fiscal_tax_vat_profile",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_fiscal_tax_effective_range",
        ),
        Index(
            "uq_fiscal_tax_current_org",
            "organization_id",
            unique=True,
            postgresql_where=text("effective_to IS NULL"),
            sqlite_where=text("effective_to IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    country_code: Mapped[str] = mapped_column(String(2))
    tax_regime_code: Mapped[str] = mapped_column(String(64))
    vat_registered: Mapped[bool] = mapped_column(Boolean)
    default_vat_rate: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_by: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class FiscalVariantProfileModel(Base):
    __tablename__ = "fiscal_variant_profiles"
    __table_args__ = (
        UniqueConstraint("product_variant_id"),
        CheckConstraint("length(trim(fiscal_name)) > 0", name="ck_fiscal_variant_name"),
        CheckConstraint(
            "nkt_code IS NULL OR length(trim(nkt_code)) > 0",
            name="ck_fiscal_variant_nkt",
        ),
        CheckConstraint(
            "vat_rate_override IS NULL OR vat_rate_override >= 0",
            name="ck_fiscal_variant_vat",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    product_variant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("product_variants.id", ondelete="CASCADE"), index=True
    )
    fiscal_name: Mapped[str] = mapped_column(String(300))
    nkt_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    nkt_code_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    fiscal_unit_code: Mapped[str] = mapped_column(String(50))
    vat_rate_override: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
    requires_marking: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    nkt_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    nkt_external_product_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class FiscalNktCacheModel(Base):
    __tablename__ = "fiscal_nkt_cache"
    __table_args__ = (
        CheckConstraint(
            f"length(ntin) = 13 AND {_NKT_DIGITS}", name="ck_fiscal_nkt_ntin"
        ),
        Index("ix_fiscal_nkt_cache_name_ru", "name_ru"),
        Index("ix_fiscal_nkt_cache_name_kk", "name_kk"),
        Index("ix_fiscal_nkt_cache_expires_at", "expires_at"),
        Index("ix_fiscal_nkt_cache_gtins", "gtins", postgresql_using="gin"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    external_product_id: Mapped[str] = mapped_column(String(255))
    ntin: Mapped[str] = mapped_column(String(13), unique=True)
    gtins: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list)
    name_ru: Mapped[str] = mapped_column(String(500))
    name_kk: Mapped[str] = mapped_column(String(500))
    category_code: Mapped[str] = mapped_column(String(100))
    unit_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(32))
    source_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload_hash: Mapped[str] = mapped_column(String(64))


class FiscalReceiptModel(Base):
    __tablename__ = "fiscal_receipts"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "source_type", "source_id", name="uq_fiscal_receipt_source"
        ),
        UniqueConstraint(
            "connection_id",
            "provider_correlation_id",
            name="uq_fiscal_receipt_correlation",
        ),
        CheckConstraint("source_type IN ('SALE','REFUND')", name="ck_fiscal_receipt_source"),
        CheckConstraint(
            "status IN ('PENDING','PROCESSING','SUCCEEDED','RETRYING','UNKNOWN','DEAD')",
            name="ck_fiscal_receipt_status",
        ),
        Index("ix_fiscal_receipts_org_created", "organization_id", "created_at"),
        Index("ix_fiscal_receipts_location_status", "location_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE")
    )
    location_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("locations.id", ondelete="CASCADE")
    )
    connection_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("integration_connections.id", ondelete="RESTRICT")
    )
    source_type: Mapped[str] = mapped_column(String(16))
    source_id: Mapped[UUID] = mapped_column(Uuid)
    provider_code: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(16))
    external_receipt_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    receipt_number: Mapped[str | None] = mapped_column(String(255), nullable=True)
    receipt_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    provider_request_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_correlation_id: Mapped[str] = mapped_column(String(255))
    fiscalized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class FiscalRouteModel(Base):
    __tablename__ = "fiscal_routes"
    __table_args__ = (
        CheckConstraint(
            "source_mode IN ('EXTERNAL_KKM','PAYMENT_TERMINAL_KKM')",
            name="ck_fiscal_route_source_mode",
        ),
        Index(
            "uq_fiscal_routes_active_register",
            "register_id",
            unique=True,
            postgresql_where=text("is_active"),
            sqlite_where=text("is_active = 1"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    location_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("locations.id", ondelete="CASCADE"), index=True
    )
    register_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("pos_registers.id", ondelete="CASCADE")
    )
    provider_connection_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("integration_connections.id", ondelete="RESTRICT")
    )
    source_mode: Mapped[str] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class FiscalSaleSnapshotModel(Base):
    __tablename__ = "fiscal_sale_snapshots"
    __table_args__ = (
        UniqueConstraint("order_id"),
        UniqueConstraint("payment_id"),
        CheckConstraint("length(currency_code) = 3", name="ck_fiscal_snapshot_currency"),
        CheckConstraint("total_minor >= 0", name="ck_fiscal_snapshot_total"),
        CheckConstraint("vat_total_minor >= 0", name="ck_fiscal_snapshot_vat"),
        CheckConstraint(
            "compliance_status IN ('COMPLETE','INCOMPLETE')",
            name="ck_fiscal_snapshot_compliance",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    location_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("locations.id", ondelete="CASCADE"), index=True
    )
    order_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("sales_orders.id"))
    payment_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("payments.id"))
    tax_profile_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("fiscal_tax_profiles.id"), nullable=True
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    currency_code: Mapped[str] = mapped_column(String(3))
    total_minor: Mapped[int] = mapped_column(BigInteger)
    vat_total_minor: Mapped[int] = mapped_column(BigInteger)
    compliance_status: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    lines: Mapped[list["FiscalSaleSnapshotLineModel"]] = relationship(
        back_populates="snapshot", cascade="all, delete-orphan"
    )


class FiscalSaleSnapshotLineModel(Base):
    __tablename__ = "fiscal_sale_snapshot_lines"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "order_item_id"),
        CheckConstraint("quantity > 0", name="ck_fiscal_snapshot_line_quantity"),
        CheckConstraint("unit_price_minor >= 0", name="ck_fiscal_snapshot_line_unit_price"),
        CheckConstraint("total_minor >= 0", name="ck_fiscal_snapshot_line_total"),
        CheckConstraint("vat_amount_minor >= 0", name="ck_fiscal_snapshot_line_vat"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    snapshot_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("fiscal_sale_snapshots.id", ondelete="CASCADE"), index=True
    )
    order_item_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("sales_order_items.id"))
    product_variant_id: Mapped[UUID] = mapped_column(Uuid)
    fiscal_name: Mapped[str] = mapped_column(String(300))
    nkt_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    nkt_code_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    unit_code: Mapped[str] = mapped_column(String(50))
    quantity: Mapped[int] = mapped_column()
    unit_price_minor: Mapped[int] = mapped_column(BigInteger)
    total_minor: Mapped[int] = mapped_column(BigInteger)
    vat_rate: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
    vat_amount_minor: Mapped[int] = mapped_column(BigInteger)
    marking_codes: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    snapshot: Mapped[FiscalSaleSnapshotModel] = relationship(back_populates="lines")
