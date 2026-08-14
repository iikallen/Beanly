from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
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
from sqlalchemy.orm import Mapped, mapped_column

from beanly.core.database.base import Base


class CustomerModel(Base):
    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("organization_id", "phone_normalized", name="uq_customers_org_phone"),
        Index("ix_customers_org_name", "organization_id", "last_name", "first_name"),
        Index("ix_customers_org_active", "organization_id", "deleted_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    phone_normalized: Mapped[str] = mapped_column(String(32), nullable=False)
    phone_display: Mapped[str] = mapped_column(String(32), nullable=False)
    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    marketing_consent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by_user_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LoyaltyProgramModel(Base):
    __tablename__ = "loyalty_programs"
    __table_args__ = (
        UniqueConstraint("organization_id", name="uq_loyalty_programs_org"),
        CheckConstraint(
            "earn_rate_bps >= 0 AND earn_rate_bps <= 10000", name="ck_loyalty_program_earn"
        ),
        CheckConstraint("point_value_minor > 0", name="ck_loyalty_program_point_value"),
        CheckConstraint("birthday_reward_points >= 0", name="ck_loyalty_program_birthday"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    earn_rate_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    point_value_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=100)
    birthday_reward_points: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_by_user_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LoyaltyTierModel(Base):
    __tablename__ = "loyalty_tiers"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_loyalty_tiers_org_name"),
        UniqueConstraint(
            "organization_id", "threshold_lifetime_points", name="uq_loyalty_tiers_org_threshold"
        ),
        CheckConstraint("threshold_lifetime_points >= 0", name="ck_loyalty_tier_threshold"),
        CheckConstraint(
            "earn_multiplier_bps >= 0 AND earn_multiplier_bps <= 100000",
            name="ck_loyalty_tier_multiplier",
        ),
        Index("ix_loyalty_tiers_org_threshold", "organization_id", "threshold_lifetime_points"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    threshold_lifetime_points: Mapped[int] = mapped_column(BigInteger, nullable=False)
    earn_multiplier_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=10000)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LoyaltyAccountModel(Base):
    __tablename__ = "loyalty_accounts"
    __table_args__ = (
        UniqueConstraint("organization_id", "customer_id", name="uq_loyalty_accounts_customer"),
        CheckConstraint("lifetime_earned_points >= 0", name="ck_loyalty_account_lifetime"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    customer_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False
    )
    tier_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("loyalty_tiers.id", ondelete="SET NULL"), nullable=True
    )
    points_balance: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    lifetime_earned_points: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LoyaltyLedgerEntryModel(Base):
    __tablename__ = "loyalty_ledger_entries"
    __table_args__ = (
        CheckConstraint("points_delta <> 0", name="ck_loyalty_ledger_nonzero"),
        CheckConstraint(
            "kind IN ('EARN','REDEEM','REFUND_REVERSAL','REDEMPTION_REVERSAL',"
            "'ADJUSTMENT','BIRTHDAY_REWARD')",
            name="ck_loyalty_ledger_kind",
        ),
        UniqueConstraint(
            "organization_id",
            "customer_id",
            "kind",
            "source_type",
            "source_id",
            name="uq_loyalty_ledger_source",
        ),
        Index("ix_loyalty_ledger_customer_time", "organization_id", "customer_id", "occurred_at"),
        Index(
            "uq_loyalty_adjustment_org_client",
            "organization_id",
            "source_id",
            unique=True,
            postgresql_where=text(
                "kind = 'ADJUSTMENT' AND source_type = 'CLIENT_ADJUSTMENT'"
            ),
            sqlite_where=text(
                "kind = 'ADJUSTMENT' AND source_type = 'CLIENT_ADJUSTMENT'"
            ),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    customer_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False
    )
    points_delta: Mapped[int] = mapped_column(BigInteger, nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str] = mapped_column(String(100), nullable=False)
    related_source_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LoyaltyRedemptionModel(Base):
    __tablename__ = "loyalty_redemptions"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "client_redemption_id", name="uq_loyalty_redemption_client"
        ),
        UniqueConstraint("order_id", name="uq_loyalty_redemption_order"),
        CheckConstraint("points_requested > 0", name="ck_loyalty_redemption_points"),
        CheckConstraint(
            "points_applied IS NULL OR (points_applied > 0 AND points_applied <= points_requested)",
            name="ck_loyalty_redemption_applied",
        ),
        CheckConstraint("discount_minor > 0", name="ck_loyalty_redemption_discount"),
        CheckConstraint(
            "status IN ('RESERVED','APPLIED','REVERSED')", name="ck_loyalty_redemption_status"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    customer_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False
    )
    order_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("sales_orders.id"), nullable=False)
    client_redemption_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    points_requested: Mapped[int] = mapped_column(BigInteger, nullable=False)
    points_applied: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    discount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_by_user_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PromotionAudienceModel(Base):
    __tablename__ = "promotion_audiences"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('ALL','CUSTOMER','TIER','BIRTHDAY')", name="ck_promotion_audience_kind"
        ),
        CheckConstraint(
            "(kind = 'TIER' AND tier_id IS NOT NULL) OR (kind <> 'TIER' AND tier_id IS NULL)",
            name="ck_promotion_audience_tier",
        ),
    )

    promotion_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("promotions.id", ondelete="CASCADE"), primary_key=True
    )
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="ALL")
    tier_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("loyalty_tiers.id", ondelete="CASCADE"), nullable=True
    )


class PromotionAudienceCustomerModel(Base):
    __tablename__ = "promotion_audience_customers"
    promotion_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("promotion_audiences.promotion_id", ondelete="CASCADE"), primary_key=True
    )
    customer_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("customers.id", ondelete="CASCADE"), primary_key=True
    )
