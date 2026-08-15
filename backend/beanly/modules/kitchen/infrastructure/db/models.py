from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from beanly.core.database.base import Base

JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


def utc_now() -> datetime:
    return datetime.now(UTC)


class KitchenStationModel(Base):
    __tablename__ = "kitchen_stations"
    __table_args__ = (
        UniqueConstraint("location_id", "code", name="uq_kitchen_station_location_code"),
        CheckConstraint("role IN ('PREP','EXPO','PREP_EXPO')", name="ck_kitchen_station_role"),
        CheckConstraint("warning_after_seconds > 0", name="ck_kitchen_station_warning"),
        CheckConstraint(
            "late_after_seconds > warning_after_seconds", name="ck_kitchen_station_late"
        ),
        CheckConstraint("sort_order >= 0", name="ck_kitchen_station_sort"),
        Index("ix_kitchen_station_location_active", "location_id", "is_active"),
        Index(
            "uq_kitchen_station_location_default",
            "location_id",
            unique=True,
            postgresql_where=text("is_default"),
            sqlite_where=text("is_default = 1"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    location_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("locations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    code: Mapped[str] = mapped_column(String(40))
    role: Mapped[str] = mapped_column(String(16))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    warning_after_seconds: Mapped[int] = mapped_column(Integer, default=600)
    late_after_seconds: Mapped[int] = mapped_column(Integer, default=900)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class KitchenRoutingRuleModel(Base):
    __tablename__ = "kitchen_routing_rules"
    __table_args__ = (
        CheckConstraint("scope IN ('CATEGORY','VARIANT')", name="ck_kitchen_routing_scope"),
        CheckConstraint(
            "(scope = 'CATEGORY' AND category_id IS NOT NULL AND variant_id IS NULL) OR "
            "(scope = 'VARIANT' AND variant_id IS NOT NULL AND category_id IS NULL)",
            name="ck_kitchen_routing_target",
        ),
        CheckConstraint(
            "order_type IS NULL OR order_type IN ('DINE_IN','TAKEAWAY','DELIVERY')",
            name="ck_kitchen_routing_order_type",
        ),
        Index("ix_kitchen_routing_location_active", "location_id", "is_active"),
        Index("ix_kitchen_routing_variant", "variant_id"),
        Index("ix_kitchen_routing_category", "category_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    location_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("locations.id", ondelete="CASCADE"), index=True
    )
    station_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("kitchen_stations.id", ondelete="CASCADE"), index=True
    )
    scope: Mapped[str] = mapped_column(String(16))
    category_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("menu_categories.id", ondelete="CASCADE"), nullable=True
    )
    variant_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("product_variants.id", ondelete="CASCADE"), nullable=True
    )
    order_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class KitchenTicketModel(Base):
    __tablename__ = "kitchen_tickets"
    __table_args__ = (
        UniqueConstraint("organization_id", "order_id", name="uq_kitchen_ticket_order"),
        CheckConstraint(
            "status IN ('QUEUED','PREPARING','READY','COMPLETED','CANCELLED')",
            name="ck_kitchen_ticket_status",
        ),
        CheckConstraint("version > 0", name="ck_kitchen_ticket_version"),
        Index("ix_kitchen_ticket_location_status", "location_id", "status"),
        Index("ix_kitchen_ticket_location_version", "location_id", "version"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    location_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("locations.id", ondelete="RESTRICT"), index=True
    )
    order_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("sales_orders.id", ondelete="RESTRICT"), index=True
    )
    payment_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("payments.id", ondelete="RESTRICT"), unique=True
    )
    shift_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("register_shifts.id", ondelete="RESTRICT"), index=True
    )
    order_number: Mapped[int] = mapped_column(BigInteger)
    order_type: Mapped[str] = mapped_column(String(16))
    order_source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    customer_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    customer_name: Mapped[str | None] = mapped_column(String(201), nullable=True)
    customer_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    table_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    guest_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    fulfillment_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    promised_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    guest_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    ordered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    version: Mapped[int] = mapped_column(BigInteger)
    items: Mapped[list["KitchenTicketItemModel"]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan"
    )
    work_items: Mapped[list["KitchenWorkItemModel"]] = relationship(back_populates="ticket")


class KitchenTicketItemModel(Base):
    __tablename__ = "kitchen_ticket_items"
    __table_args__ = (
        UniqueConstraint("ticket_id", "order_item_id", name="uq_kitchen_ticket_order_item"),
        CheckConstraint("quantity > 0", name="ck_kitchen_ticket_item_quantity"),
        CheckConstraint("sort_order >= 0", name="ck_kitchen_ticket_item_sort"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    ticket_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("kitchen_tickets.id", ondelete="CASCADE"), index=True
    )
    order_item_id: Mapped[UUID] = mapped_column(Uuid)
    product_id: Mapped[UUID] = mapped_column(Uuid)
    variant_id: Mapped[UUID] = mapped_column(Uuid)
    category_id: Mapped[UUID] = mapped_column(Uuid)
    product_name: Mapped[str] = mapped_column(String(200))
    variant_name: Mapped[str] = mapped_column(String(100))
    quantity: Mapped[int] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    ticket: Mapped[KitchenTicketModel] = relationship(back_populates="items")
    modifiers: Mapped[list["KitchenTicketItemModifierModel"]] = relationship(
        back_populates="ticket_item", cascade="all, delete-orphan"
    )
    work_items: Mapped[list["KitchenWorkItemModel"]] = relationship(
        back_populates="ticket_item", cascade="all, delete-orphan"
    )


class KitchenTicketItemModifierModel(Base):
    __tablename__ = "kitchen_ticket_item_modifiers"
    __table_args__ = (
        UniqueConstraint(
            "ticket_item_id", "modifier_option_id", name="uq_kitchen_ticket_modifier_option"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    ticket_item_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("kitchen_ticket_items.id", ondelete="CASCADE"), index=True
    )
    modifier_group_id: Mapped[UUID] = mapped_column(Uuid)
    modifier_group_name: Mapped[str] = mapped_column(String(150))
    modifier_option_id: Mapped[UUID] = mapped_column(Uuid)
    modifier_option_name: Mapped[str] = mapped_column(String(150))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    ticket_item: Mapped[KitchenTicketItemModel] = relationship(back_populates="modifiers")


class KitchenWorkItemModel(Base):
    __tablename__ = "kitchen_work_items"
    __table_args__ = (
        UniqueConstraint("ticket_item_id", "station_id", name="uq_kitchen_work_item_route"),
        CheckConstraint(
            "status IN ('QUEUED','PREPARING','READY','CANCELLED')",
            name="ck_kitchen_work_status",
        ),
        Index("ix_kitchen_work_station_status", "station_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    location_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    ticket_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("kitchen_tickets.id", ondelete="CASCADE"), index=True
    )
    ticket_item_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("kitchen_ticket_items.id", ondelete="CASCADE"), index=True
    )
    station_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("kitchen_stations.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    ticket: Mapped[KitchenTicketModel] = relationship(back_populates="work_items")
    ticket_item: Mapped[KitchenTicketItemModel] = relationship(back_populates="work_items")


class KitchenActionModel(Base):
    __tablename__ = "kitchen_actions"
    __table_args__ = (
        UniqueConstraint("organization_id", "client_action_id", name="uq_kitchen_action_client"),
        CheckConstraint(
            "action_type IN ('START','READY','COMPLETE','RECALL')",
            name="ck_kitchen_action_type",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    location_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    client_action_id: Mapped[UUID] = mapped_column(Uuid)
    action_type: Mapped[str] = mapped_column(String(16))
    resource_id: Mapped[UUID] = mapped_column(Uuid)
    payload_hash: Mapped[str] = mapped_column(String(64))
    result_payload: Mapped[dict] = mapped_column(JSON_DOCUMENT)
    actor_user_id: Mapped[UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
