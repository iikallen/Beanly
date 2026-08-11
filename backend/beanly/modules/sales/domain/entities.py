from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from beanly.modules.inventory.domain.value_objects import UnitCode
from beanly.modules.sales.domain.enums import (
    OrderStatus,
    OrderType,
    RegisterShiftStatus,
    SaleCostStatus,
)


@dataclass(frozen=True, slots=True)
class PosRegister:
    id: UUID
    organization_id: UUID
    location_id: UUID
    name: str
    is_active: bool
    created_by_user_id: UUID
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class RegisterShift:
    id: UUID
    organization_id: UUID
    location_id: UUID
    register_id: UUID
    warehouse_id: UUID
    status: RegisterShiftStatus
    opened_by_user_id: UUID
    closed_by_user_id: UUID | None
    opened_at: datetime
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class OrderItemModifier:
    id: UUID
    order_item_id: UUID
    modifier_group_id: UUID
    modifier_group_name: str
    modifier_option_id: UUID
    modifier_option_name: str
    price_delta_minor: int
    sort_order: int


@dataclass(frozen=True, slots=True)
class OrderItemComponent:
    id: UUID
    order_item_id: UUID
    inventory_item_id: UUID
    inventory_item_name: str
    base_unit: UnitCode
    quantity_per_unit: Decimal
    created_at: datetime


@dataclass(frozen=True, slots=True)
class OrderItem:
    id: UUID
    order_id: UUID
    client_item_id: UUID
    product_id: UUID
    product_variant_id: UUID
    product_name: str
    variant_name: str
    quantity: int
    base_price_minor: int
    modifier_price_minor: int
    unit_price_minor: int
    line_total_minor: int
    note: str | None
    created_at: datetime
    updated_at: datetime
    modifiers: tuple[OrderItemModifier, ...] = ()
    components: tuple[OrderItemComponent, ...] = ()


@dataclass(frozen=True, slots=True)
class SalesOrder:
    id: UUID
    organization_id: UUID
    location_id: UUID
    shift_id: UUID
    warehouse_id: UUID
    number: int
    client_order_id: UUID
    order_type: OrderType
    status: OrderStatus
    currency_code: str
    guest_count: int | None
    table_label: str | None
    note: str | None
    subtotal_minor: int
    total_minor: int
    created_by_user_id: UUID
    cancelled_by_user_id: UUID | None
    cancelled_at: datetime | None
    cancel_reason: str | None
    paid_by_user_id: UUID | None
    paid_at: datetime | None
    created_at: datetime
    updated_at: datetime
    items: tuple[OrderItem, ...] = ()
    inventory_transaction_id: UUID | None = None
    cogs_amount: Decimal | None = None
    cogs_status: SaleCostStatus | None = None
    version: int = 1
    pos_device_id: UUID | None = None
    offline_session_id: UUID | None = None
    client_created_at: datetime | None = None
    offline_display_number: int | None = None
