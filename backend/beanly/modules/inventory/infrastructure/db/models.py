from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
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


class WarehouseModel(Base):
    __tablename__ = "warehouses"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    location_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("locations.id"), index=True)
    name: Mapped[str] = mapped_column(String(150))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class InventoryItemModel(Base):
    __tablename__ = "inventory_items"
    __table_args__ = (
        Index(
            "uq_inventory_items_organization_sku",
            "organization_id",
            "sku",
            unique=True,
            postgresql_where=text("sku IS NOT NULL"),
            sqlite_where=text("sku IS NOT NULL"),
        ),
        CheckConstraint("base_unit IN ('g', 'ml', 'pcs')", name="ck_item_base_unit"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(150))
    sku: Mapped[str | None] = mapped_column(String(100), nullable=True)
    base_unit: Mapped[str] = mapped_column(String(8))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class StockBalanceModel(Base):
    __tablename__ = "stock_balances"
    __table_args__ = (UniqueConstraint("warehouse_id", "inventory_item_id"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    location_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("locations.id"), index=True)
    warehouse_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("warehouses.id"), index=True)
    inventory_item_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("inventory_items.id"), index=True
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), default=Decimal(0))
    average_unit_cost: Mapped[Decimal] = mapped_column(Numeric(20, 6), default=Decimal(0))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class InventoryTransactionModel(Base):
    __tablename__ = "inventory_transactions"
    __table_args__ = (
        Index(
            "uq_inventory_transactions_idempotency",
            "organization_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
            sqlite_where=text("idempotency_key IS NOT NULL"),
        ),
        UniqueConstraint("reversal_of_id"),
        CheckConstraint(
            "(reference_type IS NULL) = (reference_id IS NULL)",
            name="ck_inventory_transaction_reference_pair",
        ),
        CheckConstraint(
            "status IN ('DRAFT', 'POSTED', 'REVERSED')",
            name="ck_inventory_transaction_status",
        ),
        CheckConstraint(
            "type IN ('PURCHASE', 'SALE', 'WRITE_OFF', 'ADJUSTMENT', 'TRANSFER_IN', "
            "'TRANSFER_OUT', 'RETURN_IN', 'RETURN_OUT', 'PRODUCTION', 'OPENING_BALANCE')",
            name="ck_inventory_transaction_type",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    location_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("locations.id"), index=True)
    warehouse_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("warehouses.id"), index=True)
    type: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))
    reference_type: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    reference_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True
    )
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reversal_of_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("inventory_transactions.id"), nullable=True
    )


class InventoryTransactionLineModel(Base):
    __tablename__ = "inventory_transaction_lines"
    __table_args__ = (CheckConstraint("quantity_delta <> 0", name="ck_inventory_line_nonzero"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    transaction_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("inventory_transactions.id", ondelete="CASCADE"), index=True
    )
    inventory_item_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("inventory_items.id"), index=True
    )
    quantity_delta: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    requested_unit_cost_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 6), nullable=True
    )
    requested_total_cost_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 6), nullable=True
    )
    unit_cost_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    total_cost_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    quantity_after: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    average_unit_cost_after: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 6), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class WriteOffReasonModel(Base):
    __tablename__ = "inventory_writeoff_reasons"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(150))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class WriteOffModel(Base):
    __tablename__ = "inventory_writeoffs"
    __table_args__ = (
        UniqueConstraint("organization_id", "number"),
        CheckConstraint(
            "status IN ('DRAFT', 'POSTED', 'REVERSED')", name="ck_writeoff_status"
        ),
        Index(
            "ix_inventory_writeoffs_organization_status_occurred",
            "organization_id",
            "status",
            "occurred_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id"), index=True
    )
    location_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("locations.id"), index=True)
    warehouse_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("warehouses.id"), index=True)
    number: Mapped[str] = mapped_column(String(32))
    reason_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("inventory_writeoff_reasons.id"), index=True
    )
    status: Mapped[str] = mapped_column(String(16))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    posted_by: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reversed_by: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    inventory_transaction_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("inventory_transactions.id"), nullable=True, unique=True
    )
    total_cost_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class WriteOffLineModel(Base):
    __tablename__ = "inventory_writeoff_lines"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_writeoff_line_quantity_positive"),
        CheckConstraint("base_quantity > 0", name="ck_writeoff_line_base_quantity_positive"),
        UniqueConstraint("writeoff_id", "inventory_item_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    writeoff_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("inventory_writeoffs.id", ondelete="CASCADE"), index=True
    )
    inventory_item_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("inventory_items.id"), index=True
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    unit_code: Mapped[str] = mapped_column(String(8))
    base_quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class InventoryCountModel(Base):
    __tablename__ = "inventory_counts"
    __table_args__ = (
        UniqueConstraint("organization_id", "number"),
        CheckConstraint("type IN ('FULL', 'PARTIAL')", name="ck_inventory_count_type"),
        CheckConstraint(
            "status IN ('COUNTING', 'POSTED', 'CANCELLED')",
            name="ck_inventory_count_status",
        ),
        Index(
            "ix_inventory_counts_organization_status_snapshot",
            "organization_id",
            "status",
            "snapshot_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id"), index=True
    )
    location_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("locations.id"), index=True)
    warehouse_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("warehouses.id"), index=True)
    number: Mapped[str] = mapped_column(String(32))
    type: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    started_by: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    posted_by: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_by: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    inventory_transaction_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("inventory_transactions.id"), nullable=True, unique=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class InventoryCountLineModel(Base):
    __tablename__ = "inventory_count_lines"
    __table_args__ = (
        UniqueConstraint("inventory_count_id", "inventory_item_id"),
        CheckConstraint(
            "counted_quantity IS NULL OR counted_quantity >= 0",
            name="ck_inventory_count_line_counted_nonnegative",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    inventory_count_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("inventory_counts.id", ondelete="CASCADE"), index=True
    )
    inventory_item_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("inventory_items.id"), index=True
    )
    expected_quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    counted_quantity: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    current_quantity_before_post: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 6), nullable=True
    )
    difference_quantity: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    difference_cost_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 6), nullable=True
    )
    unit_cost_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class InventoryTransferModel(Base):
    __tablename__ = "inventory_transfers"
    __table_args__ = (
        UniqueConstraint("organization_id", "number"),
        CheckConstraint(
            "status IN ('DRAFT', 'POSTED', 'REVERSED')", name="ck_inventory_transfer_status"
        ),
        CheckConstraint(
            "source_warehouse_id <> destination_warehouse_id",
            name="ck_inventory_transfer_distinct_warehouses",
        ),
        Index(
            "ix_inventory_transfers_organization_status_occurred",
            "organization_id",
            "status",
            "occurred_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id"), index=True
    )
    number: Mapped[str] = mapped_column(String(32))
    source_location_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("locations.id"), index=True
    )
    source_warehouse_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("warehouses.id"), index=True
    )
    destination_location_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("locations.id"), index=True
    )
    destination_warehouse_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("warehouses.id"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    posted_by: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reversed_by: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    out_transaction_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("inventory_transactions.id"), nullable=True, unique=True
    )
    in_transaction_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("inventory_transactions.id"), nullable=True, unique=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class InventoryTransferLineModel(Base):
    __tablename__ = "inventory_transfer_lines"
    __table_args__ = (
        UniqueConstraint("transfer_id", "inventory_item_id"),
        CheckConstraint("quantity > 0", name="ck_inventory_transfer_line_quantity_positive"),
        CheckConstraint(
            "base_quantity > 0", name="ck_inventory_transfer_line_base_quantity_positive"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    transfer_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("inventory_transfers.id", ondelete="CASCADE"), index=True
    )
    inventory_item_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("inventory_items.id"), index=True
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    unit_code: Mapped[str] = mapped_column(String(8))
    base_quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
