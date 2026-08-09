from beanly.modules.inventory.domain.value_objects import UnitCode
from beanly.modules.sales.domain.entities import (
    OrderItem,
    OrderItemComponent,
    OrderItemModifier,
    PosRegister,
    RegisterShift,
    SalesOrder,
)
from beanly.modules.sales.domain.enums import OrderStatus, OrderType, RegisterShiftStatus
from beanly.modules.sales.infrastructure.db.models import (
    PosRegisterModel,
    RegisterShiftModel,
    SalesOrderItemComponentModel,
    SalesOrderItemModel,
    SalesOrderItemModifierModel,
    SalesOrderModel,
)


def to_register(model: PosRegisterModel) -> PosRegister:
    return PosRegister(
        model.id,
        model.organization_id,
        model.location_id,
        model.name,
        model.is_active,
        model.created_by_user_id,
        model.created_at,
        model.updated_at,
    )


def to_shift(model: RegisterShiftModel) -> RegisterShift:
    return RegisterShift(
        model.id,
        model.organization_id,
        model.location_id,
        model.register_id,
        model.warehouse_id,
        RegisterShiftStatus(model.status),
        model.opened_by_user_id,
        model.closed_by_user_id,
        model.opened_at,
        model.closed_at,
        model.created_at,
        model.updated_at,
    )


def to_modifier(model: SalesOrderItemModifierModel) -> OrderItemModifier:
    return OrderItemModifier(
        model.id,
        model.order_item_id,
        model.modifier_group_id,
        model.modifier_group_name,
        model.modifier_option_id,
        model.modifier_option_name,
        model.price_delta_minor,
        model.sort_order,
    )


def to_component(model: SalesOrderItemComponentModel) -> OrderItemComponent:
    return OrderItemComponent(
        model.id,
        model.order_item_id,
        model.inventory_item_id,
        model.inventory_item_name,
        UnitCode(model.base_unit),
        model.quantity_per_unit,
        model.created_at,
    )


def to_item(model: SalesOrderItemModel) -> OrderItem:
    return OrderItem(
        model.id,
        model.order_id,
        model.client_item_id,
        model.product_id,
        model.product_variant_id,
        model.product_name,
        model.variant_name,
        model.quantity,
        model.base_price_minor,
        model.modifier_price_minor,
        model.unit_price_minor,
        model.line_total_minor,
        model.note,
        model.created_at,
        model.updated_at,
        tuple(
            to_modifier(value)
            for value in sorted(
                model.__dict__.get("modifiers", ()), key=lambda item: (item.sort_order, item.id)
            )
        ),
        tuple(
            to_component(value)
            for value in sorted(
                model.__dict__.get("components", ()),
                key=lambda item: (item.inventory_item_name, item.id),
            )
        ),
    )


def to_order(model: SalesOrderModel) -> SalesOrder:
    return SalesOrder(
        model.id,
        model.organization_id,
        model.location_id,
        model.shift_id,
        model.warehouse_id,
        model.number,
        model.client_order_id,
        OrderType(model.order_type),
        OrderStatus(model.status),
        model.currency_code,
        model.guest_count,
        model.table_label,
        model.note,
        model.subtotal_minor,
        model.total_minor,
        model.created_by_user_id,
        model.cancelled_by_user_id,
        model.cancelled_at,
        model.cancel_reason,
        model.paid_by_user_id,
        model.paid_at,
        model.created_at,
        model.updated_at,
        tuple(
            to_item(value)
            for value in sorted(
                model.__dict__.get("items", ()), key=lambda item: (item.created_at, item.id)
            )
        ),
    )
