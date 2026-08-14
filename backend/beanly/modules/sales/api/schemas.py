from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from beanly.modules.inventory.domain.value_objects import UnitCode, decimal_string
from beanly.modules.sales.domain.entities import (
    OrderDiscount,
    OrderItem,
    OrderItemComponent,
    OrderItemModifier,
    SalesOrder,
)
from beanly.modules.sales.domain.enums import OrderStatus, OrderType, RegisterShiftStatus


class RegisterCreateRequest(BaseModel):
    location_id: UUID
    name: Annotated[str, Field(min_length=1, max_length=150)]


class RegisterPatchRequest(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=150)]


class RegisterResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    location_id: UUID
    name: str
    is_active: bool
    created_by_user_id: UUID
    created_at: datetime
    updated_at: datetime


class WarehouseChoiceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    location_id: UUID
    name: str


class ShiftOpenRequest(BaseModel):
    register_id: UUID
    warehouse_id: UUID


class ShiftResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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


class OrderCreateRequest(BaseModel):
    client_order_id: UUID
    shift_id: UUID
    order_type: OrderType
    guest_count: Annotated[int | None, Field(gt=0, le=1_000_000)] = None
    table_label: Annotated[str | None, Field(max_length=100)] = None
    note: Annotated[str | None, Field(max_length=4000)] = None


class OrderPatchRequest(BaseModel):
    order_type: OrderType | None = None
    guest_count: Annotated[int | None, Field(gt=0, le=1_000_000)] = None
    table_label: Annotated[str | None, Field(max_length=100)] = None
    note: Annotated[str | None, Field(max_length=4000)] = None


class OrderCancelRequest(BaseModel):
    reason: Annotated[str, Field(min_length=1, max_length=1000)]


class OrderItemCreateRequest(BaseModel):
    client_item_id: UUID
    variant_id: UUID
    selected_option_ids: Annotated[list[UUID], Field(max_length=500)] = []
    quantity: Annotated[int, Field(gt=0, le=1_000_000)] = 1
    note: Annotated[str | None, Field(max_length=1000)] = None


class OrderItemPatchRequest(BaseModel):
    quantity: Annotated[int | None, Field(gt=0, le=1_000_000)] = None
    note: Annotated[str | None, Field(max_length=1000)] = None


class OrderItemConfigurationRequest(BaseModel):
    selected_option_ids: Annotated[list[UUID], Field(max_length=500)] = []


class OrderItemModifierResponse(BaseModel):
    id: UUID
    order_item_id: UUID
    modifier_group_id: UUID
    modifier_group_name: str
    modifier_option_id: UUID
    modifier_option_name: str
    price_delta_minor: str
    sort_order: int

    @classmethod
    def from_entity(cls, value: OrderItemModifier) -> "OrderItemModifierResponse":
        return cls(
            id=value.id,
            order_item_id=value.order_item_id,
            modifier_group_id=value.modifier_group_id,
            modifier_group_name=value.modifier_group_name,
            modifier_option_id=value.modifier_option_id,
            modifier_option_name=value.modifier_option_name,
            price_delta_minor=str(value.price_delta_minor),
            sort_order=value.sort_order,
        )


class OrderItemComponentResponse(BaseModel):
    id: UUID
    order_item_id: UUID
    inventory_item_id: UUID
    inventory_item_name: str
    base_unit: UnitCode
    quantity_per_unit: Decimal
    created_at: datetime

    @field_serializer("quantity_per_unit")
    def serialize_quantity(self, value: Decimal) -> str:
        return decimal_string(value)

    @classmethod
    def from_entity(cls, value: OrderItemComponent) -> "OrderItemComponentResponse":
        return cls(**{field: getattr(value, field) for field in cls.model_fields})


class OrderItemResponse(BaseModel):
    id: UUID
    order_id: UUID
    client_item_id: UUID
    product_id: UUID
    product_variant_id: UUID
    product_name: str
    variant_name: str
    quantity: int
    base_price_minor: str
    modifier_price_minor: str
    unit_price_minor: str
    line_total_minor: str
    discount_amount_minor: str
    net_line_total_minor: str
    note: str | None
    created_at: datetime
    updated_at: datetime
    modifiers: list[OrderItemModifierResponse]
    components: list[OrderItemComponentResponse]

    @classmethod
    def from_entity(cls, value: OrderItem) -> "OrderItemResponse":
        return cls(
            id=value.id,
            order_id=value.order_id,
            client_item_id=value.client_item_id,
            product_id=value.product_id,
            product_variant_id=value.product_variant_id,
            product_name=value.product_name,
            variant_name=value.variant_name,
            quantity=value.quantity,
            base_price_minor=str(value.base_price_minor),
            modifier_price_minor=str(value.modifier_price_minor),
            unit_price_minor=str(value.unit_price_minor),
            line_total_minor=str(value.line_total_minor),
            discount_amount_minor=str(value.discount_amount_minor),
            net_line_total_minor=str(value.net_line_total_minor),
            note=value.note,
            created_at=value.created_at,
            updated_at=value.updated_at,
            modifiers=[OrderItemModifierResponse.from_entity(item) for item in value.modifiers],
            components=[OrderItemComponentResponse.from_entity(item) for item in value.components],
        )


class OrderDiscountResponse(BaseModel):
    id: UUID
    client_discount_id: UUID | None
    promotion_id: UUID | None
    source: str
    promotion_name: str
    discount_kind: str
    scope: str
    percent_rate: Decimal | None
    configured_amount_minor: str | None
    promo_code_snapshot: str | None
    reason: str | None
    applied_by_user_id: UUID | None
    applied_at: datetime
    discount_total_minor: str
    sort_order: int
    allocations: list[dict[str, object]]
    audience_kind: str | None

    @classmethod
    def from_entity(cls, value: OrderDiscount) -> "OrderDiscountResponse":
        return cls(
            id=value.id,
            client_discount_id=value.client_discount_id,
            promotion_id=value.promotion_id,
            source=value.source,
            promotion_name=value.promotion_name,
            discount_kind=value.discount_kind,
            scope=value.scope,
            percent_rate=value.percent_rate,
            configured_amount_minor=(
                str(value.configured_amount_minor)
                if value.configured_amount_minor is not None
                else None
            ),
            promo_code_snapshot=value.promo_code_snapshot,
            reason=value.reason,
            applied_by_user_id=value.applied_by_user_id,
            applied_at=value.applied_at,
            discount_total_minor=str(value.discount_total_minor),
            sort_order=value.sort_order,
            allocations=[
                {
                    "order_item_id": item.order_item_id,
                    "eligible_amount_minor": str(item.eligible_amount_minor),
                    "discount_amount_minor": str(item.discount_amount_minor),
                    "sort_order": item.sort_order,
                }
                for item in value.allocations
            ],
            audience_kind=value.audience_kind,
        )


class OrderResponse(BaseModel):
    id: UUID
    organization_id: UUID
    location_id: UUID
    shift_id: UUID
    warehouse_id: UUID
    customer_id: UUID | None
    customer_name_snapshot: str | None
    customer_phone_snapshot: str | None
    number: str
    client_order_id: UUID
    version: int
    order_type: OrderType
    status: OrderStatus
    currency_code: str
    guest_count: int | None
    table_label: str | None
    note: str | None
    subtotal_minor: str
    discount_total_minor: str
    total_minor: str
    pricing_revision: int
    priced_at: datetime | None
    created_by_user_id: UUID
    cancelled_by_user_id: UUID | None
    cancelled_at: datetime | None
    cancel_reason: str | None
    paid_by_user_id: UUID | None
    paid_at: datetime | None
    created_at: datetime
    updated_at: datetime
    pos_device_id: UUID | None
    offline_session_id: UUID | None
    client_created_at: datetime | None
    offline_display_number: int | None
    items: list[OrderItemResponse]
    discounts: list[OrderDiscountResponse]

    @classmethod
    def from_entity(cls, value: SalesOrder) -> "OrderResponse":
        return cls(
            id=value.id,
            organization_id=value.organization_id,
            location_id=value.location_id,
            shift_id=value.shift_id,
            warehouse_id=value.warehouse_id,
            customer_id=value.customer_id,
            customer_name_snapshot=value.customer_name_snapshot,
            customer_phone_snapshot=value.customer_phone_snapshot,
            number=str(value.number),
            client_order_id=value.client_order_id,
            version=value.version,
            order_type=value.order_type,
            status=value.status,
            currency_code=value.currency_code,
            guest_count=value.guest_count,
            table_label=value.table_label,
            note=value.note,
            subtotal_minor=str(value.subtotal_minor),
            discount_total_minor=str(value.discount_total_minor),
            total_minor=str(value.total_minor),
            pricing_revision=value.pricing_revision,
            priced_at=value.priced_at,
            created_by_user_id=value.created_by_user_id,
            cancelled_by_user_id=value.cancelled_by_user_id,
            cancelled_at=value.cancelled_at,
            cancel_reason=value.cancel_reason,
            paid_by_user_id=value.paid_by_user_id,
            paid_at=value.paid_at,
            created_at=value.created_at,
            updated_at=value.updated_at,
            pos_device_id=value.pos_device_id,
            offline_session_id=value.offline_session_id,
            client_created_at=value.client_created_at,
            offline_display_number=value.offline_display_number,
            items=[OrderItemResponse.from_entity(item) for item in value.items],
            discounts=[OrderDiscountResponse.from_entity(item) for item in value.discounts],
        )
