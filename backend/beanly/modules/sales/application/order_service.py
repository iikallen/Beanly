import logging
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from beanly.modules.organizations.application.queries.get_organization import (
    GetOrganizationQuery,
)
from beanly.modules.organizations.application.queries.list_locations import ListLocationsQuery
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.organizations.domain.permissions import Permission
from beanly.modules.sales.application.commands import AddOrderItemInput, CreateOrderInput
from beanly.modules.sales.application.ports import (
    MenuSalesPort,
    NullSalesEventPublisher,
    NullSalesPricingPort,
    SalesEventPublisher,
    SalesPricingPort,
    SellableItemSnapshot,
)
from beanly.modules.sales.domain.entities import (
    OrderItem,
    OrderItemComponent,
    OrderItemModifier,
    SalesOrder,
)
from beanly.modules.sales.domain.enums import OrderStatus, OrderType, RegisterShiftStatus
from beanly.modules.sales.domain.events import (
    OrderCancelled,
    OrderCreated,
    OrderItemAdded,
    OrderItemRemoved,
    OrderItemUpdated,
    OrderUpdated,
)
from beanly.modules.sales.domain.exceptions import (
    InvalidSalesOperation,
    OrderImmutable,
    SalesAccessDenied,
    SalesConflict,
    SalesNotFound,
)
from beanly.modules.sales.domain.repositories import SalesRepository

logger = logging.getLogger(__name__)
_MAX_BIGINT = 9223372036854775807


class OrderService:
    def __init__(
        self,
        repository: SalesRepository,
        organizations: OrganizationService,
        menu: MenuSalesPort,
        publisher: SalesEventPublisher | None = None,
        pricing: SalesPricingPort | None = None,
    ) -> None:
        self.repository = repository
        self.organizations = organizations
        self.menu = menu
        self.pricing = pricing or NullSalesPricingPort()
        self.publisher = publisher or NullSalesEventPublisher()

    async def create(self, context: TenantContext, value: CreateOrderInput) -> SalesOrder:
        existing = await self.repository.get_order_by_client_id(
            context.organization_id, value.client_order_id
        )
        if existing is not None:
            await self._assert_access(context, existing)
            return existing
        try:
            saved, created = await self._create_staged(context, value)
            await self.repository.commit()
            if created:
                await self._publish((OrderCreated(saved.id),))
            return saved
        except SalesConflict:
            await self.repository.rollback()
            existing = await self.repository.get_order_by_client_id(
                context.organization_id, value.client_order_id
            )
            if existing is None:
                raise
            await self._assert_access(context, existing)
            return existing
        except Exception:
            await self.repository.rollback()
            raise

    async def create_staged(self, context: TenantContext, value: CreateOrderInput) -> SalesOrder:
        """Create an order inside the caller's transaction without committing it."""
        result, _ = await self._create_staged(context, value)
        return result

    async def _create_staged(
        self, context: TenantContext, value: CreateOrderInput
    ) -> tuple[SalesOrder, bool]:
        existing = await self.repository.get_order_by_client_id(
            context.organization_id, value.client_order_id
        )
        if existing is not None:
            await self._assert_access(context, existing)
            return existing, False
        shift = await self.repository.get_shift(context.organization_id, value.shift_id, lock=True)
        if shift is None:
            raise SalesNotFound("Shift not found")
        await self.organizations.ensure_location_access(context, shift.location_id)
        if shift.status != RegisterShiftStatus.OPEN:
            raise InvalidSalesOperation("Orders require an OPEN shift")
        existing = await self.repository.get_order_by_client_id(
            context.organization_id, value.client_order_id
        )
        if existing is not None:
            await self._assert_access(context, existing)
            return existing, False
        organization = await self.organizations.get_organization(
            GetOrganizationQuery(context.user_id, context.organization_id)
        )
        now = datetime.now(UTC)
        order = SalesOrder(
            uuid4(),
            context.organization_id,
            shift.location_id,
            shift.id,
            shift.warehouse_id,
            await self.repository.next_order_number(),
            value.client_order_id,
            value.order_type,
            OrderStatus.OPEN,
            organization.currency_code,
            _guest_count(value.guest_count),
            _optional(value.table_label, 100),
            _optional(value.note, 4000),
            0,
            0,
            context.user_id,
            None,
            None,
            None,
            None,
            None,
            now,
            now,
        )
        return await self.repository.add_order(order), True

    async def list(
        self,
        context: TenantContext,
        *,
        location_id: UUID | None,
        shift_id: UUID | None,
        status: OrderStatus | None,
    ) -> list[SalesOrder]:
        locations = await self.organizations.list_locations(
            ListLocationsQuery(context.user_id, context.organization_id)
        )
        allowed = {value.id for value in locations}
        if location_id is not None:
            if location_id not in allowed:
                raise SalesAccessDenied("Location access denied")
            location_ids = (location_id,)
        else:
            location_ids = tuple(allowed)
        own_only = Permission.SALES_READ not in context.permissions
        return await self.repository.list_orders(
            context.organization_id,
            location_ids,
            shift_id,
            status,
            context.user_id if own_only else None,
        )

    async def get(self, context: TenantContext, order_id: UUID) -> SalesOrder:
        value = await self._order(context.organization_id, order_id)
        await self._assert_access(context, value)
        return value

    async def update(
        self,
        context: TenantContext,
        order_id: UUID,
        *,
        order_type: OrderType | None,
        guest_count: int | None,
        guest_count_set: bool,
        table_label: str | None,
        table_label_set: bool,
        note: str | None,
        note_set: bool,
    ) -> SalesOrder:
        try:
            order = await self._mutable_order(context, order_id)
            updated = replace(
                order,
                order_type=order_type or order.order_type,
                guest_count=(_guest_count(guest_count) if guest_count_set else order.guest_count),
                table_label=(_optional(table_label, 100) if table_label_set else order.table_label),
                note=_optional(note, 4000) if note_set else order.note,
                version=order.version + 1,
                updated_at=datetime.now(UTC),
            )
            saved = await self.repository.update_order(updated)
            await self.repository.commit()
            await self._publish((OrderUpdated(order.id),))
            return saved
        except Exception:
            await self.repository.rollback()
            raise

    async def cancel(self, context: TenantContext, order_id: UUID, reason: str) -> SalesOrder:
        try:
            order = await self._mutable_order(context, order_id)
            now = datetime.now(UTC)
            saved = await self.repository.update_order(
                replace(
                    order,
                    status=OrderStatus.CANCELLED,
                    cancelled_by_user_id=context.user_id,
                    cancelled_at=now,
                    cancel_reason=_required(reason, 1000, "Cancel reason"),
                    version=order.version + 1,
                    updated_at=now,
                )
            )
            await self.repository.commit()
            await self._publish((OrderCancelled(order.id),))
            return saved
        except Exception:
            await self.repository.rollback()
            raise

    async def add_item(
        self, context: TenantContext, order_id: UUID, value: AddOrderItemInput
    ) -> SalesOrder:
        try:
            order = await self._mutable_order(context, order_id)
            if await self.repository.get_item_by_client_id(order.id, value.client_item_id):
                await self.repository.commit()
                return await self._order(context.organization_id, order.id)
            snapshot = await self.menu.resolve_order_item(
                context,
                variant_id=value.variant_id,
                warehouse_id=order.warehouse_id,
                location_id=order.location_id,
                selected_option_ids=value.selected_option_ids,
            )
            now = datetime.now(UTC)
            item = _snapshot_item(
                order.id,
                value.client_item_id,
                snapshot,
                _quantity(value.quantity),
                _optional(value.note, 1000),
                now,
            )
            await self.repository.add_item(item)
            saved = await self.repository.recalculate_order_totals(
                context.organization_id, order.id
            )
            await self.pricing.reprice(context.organization_id, order.id)
            saved = await self._order(context.organization_id, order.id)
            await self.repository.commit()
            await self._publish((OrderItemAdded(order.id, item.id),))
            return saved
        except Exception:
            await self.repository.rollback()
            raise

    async def update_item(
        self,
        context: TenantContext,
        order_id: UUID,
        item_id: UUID,
        *,
        quantity: int | None,
        note: str | None,
        note_set: bool,
    ) -> SalesOrder:
        try:
            order = await self._mutable_order(context, order_id)
            item = _item(order, item_id)
            next_quantity = _quantity(quantity) if quantity is not None else item.quantity
            line_total = _line_total(item.unit_price_minor, next_quantity)
            updated = replace(
                item,
                quantity=next_quantity,
                line_total_minor=line_total,
                discount_amount_minor=0,
                net_line_total_minor=line_total,
                note=_optional(note, 1000) if note_set else item.note,
                updated_at=datetime.now(UTC),
            )
            await self.repository.update_item(updated)
            saved = await self.repository.recalculate_order_totals(
                context.organization_id, order.id
            )
            await self.pricing.reprice(context.organization_id, order.id)
            saved = await self._order(context.organization_id, order.id)
            await self.repository.commit()
            await self._publish((OrderItemUpdated(order.id, item.id),))
            return saved
        except Exception:
            await self.repository.rollback()
            raise

    async def reconfigure_item(
        self,
        context: TenantContext,
        order_id: UUID,
        item_id: UUID,
        selected_option_ids: tuple[UUID, ...],
    ) -> SalesOrder:
        try:
            order = await self._mutable_order(context, order_id)
            item = _item(order, item_id)
            snapshot = await self.menu.resolve_order_item(
                context,
                variant_id=item.product_variant_id,
                warehouse_id=order.warehouse_id,
                location_id=order.location_id,
                selected_option_ids=selected_option_ids,
            )
            updated = _snapshot_item(
                order.id,
                item.client_item_id,
                snapshot,
                item.quantity,
                item.note,
                datetime.now(UTC),
                item_id=item.id,
                created_at=item.created_at,
            )
            await self.repository.replace_item_configuration(updated)
            saved = await self.repository.recalculate_order_totals(
                context.organization_id, order.id
            )
            await self.pricing.reprice(context.organization_id, order.id)
            saved = await self._order(context.organization_id, order.id)
            await self.repository.commit()
            await self._publish((OrderItemUpdated(order.id, item.id),))
            return saved
        except Exception:
            await self.repository.rollback()
            raise

    async def remove_item(
        self, context: TenantContext, order_id: UUID, item_id: UUID
    ) -> SalesOrder:
        try:
            order = await self._mutable_order(context, order_id)
            _item(order, item_id)
            await self.repository.delete_item(order.id, item_id)
            saved = await self.repository.recalculate_order_totals(
                context.organization_id, order.id
            )
            await self.pricing.reprice(context.organization_id, order.id)
            saved = await self._order(context.organization_id, order.id)
            await self.repository.commit()
            await self._publish((OrderItemRemoved(order.id, item_id),))
            return saved
        except Exception:
            await self.repository.rollback()
            raise

    async def _mutable_order(self, context: TenantContext, order_id: UUID) -> SalesOrder:
        order = await self.repository.get_order(context.organization_id, order_id, lock=True)
        if order is None:
            raise SalesNotFound("Order not found")
        await self._assert_access(context, order)
        if order.status != OrderStatus.OPEN:
            raise OrderImmutable("Only OPEN orders can be changed")
        await self.pricing.ensure_mutable(context.organization_id, order.id)
        shift = await self.repository.get_shift(context.organization_id, order.shift_id)
        if shift is None or shift.status != RegisterShiftStatus.OPEN:
            raise InvalidSalesOperation("Order shift is not OPEN")
        return order

    async def _assert_access(self, context: TenantContext, order: SalesOrder) -> None:
        await self.organizations.ensure_location_access(context, order.location_id)
        if (
            Permission.SALES_READ not in context.permissions
            and order.created_by_user_id != context.user_id
        ):
            raise SalesAccessDenied("Order access denied")

    async def _order(self, organization_id: UUID, order_id: UUID) -> SalesOrder:
        value = await self.repository.get_order(organization_id, order_id)
        if value is None:
            raise SalesNotFound("Order not found")
        return value

    async def _publish(self, events: tuple[object, ...]) -> None:
        for event in events:
            try:
                await self.publisher.publish(event)
            except Exception:
                logger.exception("Sales event publish failed")


def _snapshot_item(
    order_id: UUID,
    client_item_id: UUID,
    snapshot: SellableItemSnapshot,
    quantity: int,
    note: str | None,
    now: datetime,
    *,
    item_id: UUID | None = None,
    created_at: datetime | None = None,
) -> OrderItem:
    order_item_id = item_id or uuid4()
    return OrderItem(
        order_item_id,
        order_id,
        client_item_id,
        snapshot.product_id,
        snapshot.variant_id,
        snapshot.product_name,
        snapshot.variant_name,
        quantity,
        snapshot.base_price_minor,
        snapshot.modifier_price_minor,
        snapshot.unit_price_minor,
        _line_total(snapshot.unit_price_minor, quantity),
        note,
        created_at or now,
        now,
        tuple(
            OrderItemModifier(
                uuid4(),
                order_item_id,
                value.group_id,
                value.group_name,
                value.option_id,
                value.option_name,
                value.price_delta_minor,
                value.sort_order,
            )
            for value in snapshot.modifiers
        ),
        tuple(
            OrderItemComponent(
                uuid4(),
                order_item_id,
                value.inventory_item_id,
                value.inventory_item_name,
                value.base_unit,
                value.quantity_per_unit,
                now,
            )
            for value in snapshot.components
        ),
    )


def _item(order: SalesOrder, item_id: UUID) -> OrderItem:
    value = next((value for value in order.items if value.id == item_id), None)
    if value is None:
        raise SalesNotFound("Order item not found")
    return value


def _quantity(value: int | None) -> int:
    if value is None or not 1 <= value <= 1_000_000:
        raise ValueError("Quantity must be between 1 and 1000000")
    return value


def _line_total(unit_price_minor: int, quantity: int) -> int:
    value = unit_price_minor * quantity
    if value > _MAX_BIGINT:
        raise ValueError("Line total is outside BIGINT")
    return value


def _guest_count(value: int | None) -> int | None:
    if value is not None and not 1 <= value <= 1_000_000:
        raise ValueError("Guest count must be positive")
    return value


def _required(value: str, limit: int, label: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > limit:
        raise ValueError(f"{label} must contain between 1 and {limit} characters")
    return normalized


def _optional(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if len(normalized) > limit:
        raise ValueError(f"Text cannot exceed {limit} characters")
    return normalized or None
