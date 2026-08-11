from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
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


class ExpenseCategoryModel(Base):
    __tablename__ = "expense_categories"
    __table_args__ = (UniqueConstraint("organization_id", "name"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(150))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class CashAccountModel(Base):
    __tablename__ = "cash_accounts"
    __table_args__ = (
        CheckConstraint(
            "type IN ('CASH', 'CARD_CLEARING', 'BANK', 'OTHER')",
            name="ck_cash_account_type",
        ),
        CheckConstraint(
            "length(currency_code) = 3", name="ck_cash_account_currency"
        ),
        UniqueConstraint("organization_id", "location_id", "system_key"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id"), index=True
    )
    location_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("locations.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(150))
    type: Mapped[str] = mapped_column(String(20))
    currency_code: Mapped[str] = mapped_column(String(3))
    system_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    opening_balance_minor: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default=text("0")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class FinanceEntryModel(Base):
    __tablename__ = "finance_entries"
    __table_args__ = (
        CheckConstraint(
            "entry_type IN ('REVENUE','COGS','INVENTORY_LOSS','INVENTORY_GAIN',"
            "'OPERATING_EXPENSE','OTHER_INCOME','OTHER_EXPENSE')",
            name="ck_finance_entry_type",
        ),
        CheckConstraint("length(currency_code) = 3", name="ck_finance_currency"),
        CheckConstraint(
            "(entry_type = 'COGS' AND quality_status IS NOT NULL "
            "AND quality_status IN ('COMPLETE','INCOMPLETE','ESTIMATED')) OR "
            "(entry_type <> 'COGS' AND quality_status IS NULL)",
            name="ck_finance_entry_quality",
        ),
        UniqueConstraint("source_event_id", "entry_role"),
        UniqueConstraint("source_type", "source_id", "entry_role"),
        Index(
            "ix_finance_entries_org_effective",
            "organization_id",
            "effective_at",
        ),
        Index("ix_finance_entries_source", "source_type", "source_id"),
        Index(
            "ix_finance_entries_dashboard_scope",
            "organization_id",
            "location_id",
            "effective_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id"), index=True
    )
    location_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("locations.id"), nullable=True, index=True
    )
    entry_type: Mapped[str] = mapped_column(String(30), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    currency_code: Mapped[str] = mapped_column(String(3))
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expense_category_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("expense_categories.id"), nullable=True
    )
    source_type: Mapped[str] = mapped_column(String(80))
    source_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    source_event_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    entry_role: Mapped[str] = mapped_column(String(80))
    reversal_of_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("finance_entries.id"), nullable=True
    )
    quality_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CashEntryModel(Base):
    __tablename__ = "cash_entries"
    __table_args__ = (
        CheckConstraint(
            "cash_flow_activity IN ('OPERATING','INVESTING','FINANCING')",
            name="ck_cash_entry_activity",
        ),
        CheckConstraint("length(currency_code) = 3", name="ck_cash_entry_currency"),
        UniqueConstraint("source_event_id", "entry_role"),
        UniqueConstraint("source_type", "source_id", "entry_role"),
        Index(
            "ix_cash_entries_org_account_effective",
            "organization_id",
            "cash_account_id",
            "effective_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id"), index=True
    )
    location_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("locations.id"), nullable=True, index=True
    )
    cash_account_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("cash_accounts.id"), index=True
    )
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency_code: Mapped[str] = mapped_column(String(3))
    cash_flow_activity: Mapped[str] = mapped_column(String(20), index=True)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_type: Mapped[str] = mapped_column(String(80))
    source_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    source_event_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    entry_role: Mapped[str] = mapped_column(String(80))
    reversal_of_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("cash_entries.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ExpenseModel(Base):
    __tablename__ = "expenses"
    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="ck_expense_amount_positive"),
        CheckConstraint(
            "status IN ('DRAFT','POSTED','REVERSED')", name="ck_expense_status"
        ),
        CheckConstraint("length(currency_code) = 3", name="ck_expense_currency"),
        UniqueConstraint("organization_id", "number"),
        Index("ix_expenses_org_occurred", "organization_id", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id"), index=True
    )
    location_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("locations.id"), nullable=True, index=True
    )
    number: Mapped[str] = mapped_column(String(32))
    category_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("expense_categories.id"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), index=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency_code: Mapped[str] = mapped_column(String(3))
    cash_account_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("cash_accounts.id"), nullable=True
    )
    vendor: Mapped[str | None] = mapped_column(String(200), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    posted_by: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reversed_by: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finance_entry_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("finance_entries.id"), nullable=True, unique=True
    )
    cash_entry_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("cash_entries.id"), nullable=True, unique=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class CashMovementModel(Base):
    __tablename__ = "cash_movements"
    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="ck_cash_movement_amount_positive"),
        CheckConstraint(
            "type IN ('SUPPLIER_PAYMENT','OWNER_CONTRIBUTION','OWNER_WITHDRAWAL',"
            "'OTHER_INFLOW','OTHER_OUTFLOW','TRANSFER')",
            name="ck_cash_movement_type",
        ),
        CheckConstraint(
            "cash_flow_activity IN ('OPERATING','INVESTING','FINANCING')",
            name="ck_cash_movement_activity",
        ),
        CheckConstraint(
            "(type = 'TRANSFER' AND from_account_id IS NOT NULL AND to_account_id IS NOT NULL "
            "AND from_account_id <> to_account_id) OR "
            "(type IN ('OWNER_CONTRIBUTION','OTHER_INFLOW') AND from_account_id IS NULL "
            "AND to_account_id IS NOT NULL) OR "
            "(type IN ('SUPPLIER_PAYMENT','OWNER_WITHDRAWAL','OTHER_OUTFLOW') "
            "AND from_account_id IS NOT NULL AND to_account_id IS NULL)",
            name="ck_cash_movement_accounts",
        ),
        CheckConstraint(
            "(type = 'SUPPLIER_PAYMENT' AND cash_flow_activity = 'OPERATING') OR "
            "(type IN ('OWNER_CONTRIBUTION','OWNER_WITHDRAWAL') "
            "AND cash_flow_activity = 'FINANCING') OR "
            "type IN ('OTHER_INFLOW','OTHER_OUTFLOW','TRANSFER')",
            name="ck_cash_movement_derived_activity",
        ),
        Index("ix_cash_movements_org_occurred", "organization_id", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id"), index=True
    )
    location_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("locations.id"), nullable=True, index=True
    )
    type: Mapped[str] = mapped_column(String(30), index=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency_code: Mapped[str] = mapped_column(String(3))
    from_account_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("cash_accounts.id"), nullable=True
    )
    to_account_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("cash_accounts.id"), nullable=True
    )
    cash_flow_activity: Mapped[str] = mapped_column(String(20))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    reversed_by: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    out_entry_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("cash_entries.id"), nullable=True, unique=True
    )
    in_entry_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("cash_entries.id"), nullable=True, unique=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
