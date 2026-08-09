from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from beanly.modules.sales.domain.entities import (
    OrderItem,
    PosRegister,
    RegisterShift,
    SalesOrder,
)
from beanly.modules.sales.domain.enums import OrderStatus, RegisterShiftStatus
from beanly.modules.sales.domain.exceptions import (
    InvalidSalesOperation,
    OrderImmutable,
    SalesConflict,
)
from beanly.modules.sales.infrastructure.db.mappers import (
    to_item,
    to_order,
    to_register,
    to_shift,
)
from beanly.modules.sales.infrastructure.db.models import (
    PosRegisterModel,
    RegisterShiftModel,
    SalesOrderItemComponentModel,
    SalesOrderItemModel,
    SalesOrderItemModifierModel,
    SalesOrderModel,
)


class SqlAlchemySalesRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_register(self, value: PosRegister) -> PosRegister:
        model = PosRegisterModel(**_register_values(value))
        self.session.add(model)
        await self.session.flush()
        return to_register(model)

    async def get_register(
        self, organization_id: UUID, register_id: UUID
    ) -> PosRegister | None:
        model = await self.session.scalar(
            select(PosRegisterModel).where(
                PosRegisterModel.organization_id == organization_id,
                PosRegisterModel.id == register_id,
            )
        )
        return to_register(model) if model else None

    async def list_registers(
        self, organization_id: UUID, location_id: UUID | None
    ) -> list[PosRegister]:
        statement = select(PosRegisterModel).where(
            PosRegisterModel.organization_id == organization_id
        )
        if location_id is not None:
            statement = statement.where(PosRegisterModel.location_id == location_id)
        models = await self.session.scalars(
            statement.order_by(PosRegisterModel.name, PosRegisterModel.id)
        )
        return [to_register(model) for model in models]

    async def update_register(self, value: PosRegister) -> PosRegister:
        current = await self.session.scalar(
            select(PosRegisterModel)
            .where(
                PosRegisterModel.organization_id == value.organization_id,
                PosRegisterModel.id == value.id,
            )
            .with_for_update()
        )
        if current is None:
            raise LookupError("Register disappeared while updating")
        if not current.is_active:
            raise InvalidSalesOperation("Inactive registers cannot be updated")
        if not value.is_active:
            open_shift = await self.session.scalar(
                select(RegisterShiftModel.id).where(
                    RegisterShiftModel.organization_id == value.organization_id,
                    RegisterShiftModel.register_id == value.id,
                    RegisterShiftModel.status == RegisterShiftStatus.OPEN.value,
                )
            )
            if open_shift is not None:
                raise InvalidSalesOperation(
                    "Register with an OPEN shift cannot be deactivated"
                )
        await self.session.execute(
            update(PosRegisterModel)
            .where(PosRegisterModel.id == value.id)
            .values(**_register_values(value))
        )
        await self.session.flush()
        return value

    async def add_shift(self, value: RegisterShift) -> RegisterShift:
        register = await self.session.scalar(
            select(PosRegisterModel)
            .where(
                PosRegisterModel.organization_id == value.organization_id,
                PosRegisterModel.id == value.register_id,
            )
            .with_for_update()
        )
        if register is None:
            raise LookupError("Register disappeared while opening shift")
        if not register.is_active:
            raise InvalidSalesOperation("Inactive register cannot open a shift")
        open_shift = await self.session.scalar(
            select(RegisterShiftModel.id).where(
                RegisterShiftModel.organization_id == value.organization_id,
                RegisterShiftModel.register_id == value.register_id,
                RegisterShiftModel.status == RegisterShiftStatus.OPEN.value,
            )
        )
        if open_shift is not None:
            raise SalesConflict("Register already has an OPEN shift")
        model = RegisterShiftModel(**_shift_values(value))
        self.session.add(model)
        await self.session.flush()
        return to_shift(model)

    async def get_shift(
        self, organization_id: UUID, shift_id: UUID, *, lock: bool = False
    ) -> RegisterShift | None:
        statement = select(RegisterShiftModel).where(
            RegisterShiftModel.organization_id == organization_id,
            RegisterShiftModel.id == shift_id,
        )
        if lock:
            statement = statement.with_for_update()
        model = await self.session.scalar(statement)
        return to_shift(model) if model else None

    async def get_current_shift(
        self, organization_id: UUID, register_id: UUID
    ) -> RegisterShift | None:
        model = await self.session.scalar(
            select(RegisterShiftModel).where(
                RegisterShiftModel.organization_id == organization_id,
                RegisterShiftModel.register_id == register_id,
                RegisterShiftModel.status == RegisterShiftStatus.OPEN.value,
            )
        )
        return to_shift(model) if model else None

    async def update_shift(self, value: RegisterShift) -> RegisterShift:
        current = await self.session.scalar(
            select(RegisterShiftModel)
            .where(
                RegisterShiftModel.organization_id == value.organization_id,
                RegisterShiftModel.id == value.id,
            )
            .with_for_update()
        )
        if current is None:
            raise LookupError("Shift disappeared while updating")
        if current.status != RegisterShiftStatus.OPEN.value:
            raise InvalidSalesOperation("Shift is already closed")
        await self.session.execute(
            update(RegisterShiftModel)
            .where(RegisterShiftModel.id == value.id)
            .values(**_shift_values(value))
        )
        await self.session.flush()
        return value

    async def count_open_orders(self, organization_id: UUID, shift_id: UUID) -> int:
        value = await self.session.scalar(
            select(func.count())
            .select_from(SalesOrderModel)
            .where(
                SalesOrderModel.organization_id == organization_id,
                SalesOrderModel.shift_id == shift_id,
                SalesOrderModel.status == OrderStatus.OPEN.value,
            )
        )
        return int(value or 0)

    async def next_order_number(self) -> int:
        if self.session.get_bind().dialect.name == "postgresql":
            value = await self.session.scalar(select(func.nextval("sales_order_number_seq")))
        else:
            count = await self.session.scalar(
                select(func.count()).select_from(SalesOrderModel)
            )
            value = count + 1
        if value is None:
            raise RuntimeError("Order sequence did not return a value")
        return int(value)

    async def add_order(self, value: SalesOrder) -> SalesOrder:
        model = SalesOrderModel(**_order_values(value))
        self.session.add(model)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise SalesConflict("Order client id already exists") from exc
        return await self._order(value.organization_id, value.id)

    async def get_order(
        self, organization_id: UUID, order_id: UUID, *, lock: bool = False
    ) -> SalesOrder | None:
        return await self._order(organization_id, order_id, lock=lock)

    async def get_order_by_client_id(
        self, organization_id: UUID, client_order_id: UUID
    ) -> SalesOrder | None:
        model = await self.session.scalar(
            _order_query(organization_id)
            .where(SalesOrderModel.client_order_id == client_order_id)
            .execution_options(populate_existing=True)
        )
        return to_order(model) if model else None

    async def list_orders(
        self,
        organization_id: UUID,
        location_ids: tuple[UUID, ...],
        shift_id: UUID | None,
        status: OrderStatus | None,
        created_by_user_id: UUID | None,
    ) -> list[SalesOrder]:
        if not location_ids:
            return []
        statement = _order_query(organization_id).where(
            SalesOrderModel.location_id.in_(location_ids)
        )
        if shift_id is not None:
            statement = statement.where(SalesOrderModel.shift_id == shift_id)
        if status is not None:
            statement = statement.where(SalesOrderModel.status == status.value)
        if created_by_user_id is not None:
            statement = statement.where(
                SalesOrderModel.created_by_user_id == created_by_user_id
            )
        models = await self.session.scalars(
            statement.order_by(SalesOrderModel.created_at.desc(), SalesOrderModel.id)
        )
        return [to_order(model) for model in models]

    async def update_order(self, value: SalesOrder) -> SalesOrder:
        current_status = await self.session.scalar(
            select(SalesOrderModel.status).where(
                SalesOrderModel.organization_id == value.organization_id,
                SalesOrderModel.id == value.id,
            )
        )
        if current_status is None:
            raise LookupError("Order disappeared while updating")
        if current_status != OrderStatus.OPEN.value:
            raise OrderImmutable("Only OPEN orders can be changed")
        await self.session.execute(
            update(SalesOrderModel)
            .where(
                SalesOrderModel.organization_id == value.organization_id,
                SalesOrderModel.id == value.id,
            )
            .values(**_order_values(value))
        )
        await self.session.flush()
        saved = await self._order(value.organization_id, value.id)
        if saved is None:
            raise LookupError("Order disappeared while updating")
        return saved

    async def mark_order_paid(
        self, order_id: UUID, paid_by_user_id: UUID, paid_at: datetime
    ) -> None:
        result = await self.session.execute(
            update(SalesOrderModel)
            .where(
                SalesOrderModel.id == order_id,
                SalesOrderModel.status == OrderStatus.OPEN.value,
            )
            .values(
                status=OrderStatus.PAID.value,
                paid_by_user_id=paid_by_user_id,
                paid_at=paid_at,
                updated_at=paid_at,
            )
        )
        if result.rowcount != 1:
            raise OrderImmutable("Only OPEN orders can be paid")
        await self.session.flush()

    async def get_item_by_client_id(
        self, order_id: UUID, client_item_id: UUID
    ) -> OrderItem | None:
        model = await self.session.scalar(
            _item_query().where(
                SalesOrderItemModel.order_id == order_id,
                SalesOrderItemModel.client_item_id == client_item_id,
            )
        )
        return to_item(model) if model else None

    async def add_item(self, value: OrderItem) -> OrderItem:
        model = SalesOrderItemModel(**_item_values(value))
        model.modifiers = [
            SalesOrderItemModifierModel(**_modifier_values(item)) for item in value.modifiers
        ]
        model.components = [
            SalesOrderItemComponentModel(**_component_values(item)) for item in value.components
        ]
        self.session.add(model)
        await self.session.flush()
        saved = await self.session.scalar(
            _item_query()
            .where(SalesOrderItemModel.id == value.id)
            .execution_options(populate_existing=True)
        )
        return to_item(saved)

    async def update_item(self, value: OrderItem) -> OrderItem:
        await self.session.execute(
            update(SalesOrderItemModel)
            .where(
                SalesOrderItemModel.order_id == value.order_id,
                SalesOrderItemModel.id == value.id,
            )
            .values(**_item_values(value))
        )
        await self.session.flush()
        return value

    async def replace_item_configuration(self, value: OrderItem) -> OrderItem:
        locked = await self.session.scalar(
            select(SalesOrderItemModel.id)
            .where(
                SalesOrderItemModel.order_id == value.order_id,
                SalesOrderItemModel.id == value.id,
            )
            .with_for_update()
        )
        if locked is None:
            raise LookupError("Order item disappeared while replacing configuration")
        await self.session.execute(
            SalesOrderItemModifierModel.__table__.delete().where(
                SalesOrderItemModifierModel.order_item_id == value.id
            )
        )
        await self.session.execute(
            SalesOrderItemComponentModel.__table__.delete().where(
                SalesOrderItemComponentModel.order_item_id == value.id
            )
        )
        await self.session.execute(
            update(SalesOrderItemModel)
            .where(SalesOrderItemModel.id == value.id)
            .values(**_item_values(value))
        )
        self.session.add_all(
            SalesOrderItemModifierModel(**_modifier_values(item)) for item in value.modifiers
        )
        self.session.add_all(
            SalesOrderItemComponentModel(**_component_values(item)) for item in value.components
        )
        await self.session.flush()
        saved = await self.session.scalar(
            _item_query()
            .where(SalesOrderItemModel.id == value.id)
            .execution_options(populate_existing=True)
        )
        return to_item(saved)

    async def delete_item(self, order_id: UUID, item_id: UUID) -> None:
        await self.session.execute(
            SalesOrderItemModel.__table__.delete().where(
                SalesOrderItemModel.order_id == order_id,
                SalesOrderItemModel.id == item_id,
            )
        )
        await self.session.flush()

    async def recalculate_order_totals(
        self, organization_id: UUID, order_id: UUID
    ) -> SalesOrder:
        total = int(
            await self.session.scalar(
                select(func.coalesce(func.sum(SalesOrderItemModel.line_total_minor), 0)).where(
                    SalesOrderItemModel.order_id == order_id
                )
            )
        )
        if total > 9223372036854775807:
            raise ValueError("Order total is outside BIGINT")
        await self.session.execute(
            update(SalesOrderModel)
            .where(
                SalesOrderModel.organization_id == organization_id,
                SalesOrderModel.id == order_id,
                SalesOrderModel.status == OrderStatus.OPEN.value,
            )
            .values(subtotal_minor=total, total_minor=total, updated_at=datetime.now(UTC))
        )
        await self.session.flush()
        saved = await self._order(organization_id, order_id)
        if saved is None:
            raise LookupError("Order disappeared while recalculating totals")
        return saved

    async def _order(
        self, organization_id: UUID, order_id: UUID, *, lock: bool = False
    ) -> SalesOrder | None:
        statement = _order_query(organization_id).where(SalesOrderModel.id == order_id)
        if lock:
            statement = statement.with_for_update()
        model = await self.session.scalar(
            statement.execution_options(populate_existing=True)
        )
        return to_order(model) if model else None

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()


def _register_values(value: PosRegister) -> dict[str, object]:
    return {
        "id": value.id,
        "organization_id": value.organization_id,
        "location_id": value.location_id,
        "name": value.name,
        "is_active": value.is_active,
        "created_by_user_id": value.created_by_user_id,
        "created_at": value.created_at,
        "updated_at": value.updated_at,
    }


def _shift_values(value: RegisterShift) -> dict[str, object]:
    return {
        "id": value.id,
        "organization_id": value.organization_id,
        "location_id": value.location_id,
        "register_id": value.register_id,
        "warehouse_id": value.warehouse_id,
        "status": value.status.value,
        "opened_by_user_id": value.opened_by_user_id,
        "closed_by_user_id": value.closed_by_user_id,
        "opened_at": value.opened_at,
        "closed_at": value.closed_at,
        "created_at": value.created_at,
        "updated_at": value.updated_at,
    }


def _order_values(value: SalesOrder) -> dict[str, object]:
    return {
        "id": value.id,
        "organization_id": value.organization_id,
        "location_id": value.location_id,
        "shift_id": value.shift_id,
        "warehouse_id": value.warehouse_id,
        "number": value.number,
        "client_order_id": value.client_order_id,
        "order_type": value.order_type.value,
        "status": value.status.value,
        "currency_code": value.currency_code,
        "guest_count": value.guest_count,
        "table_label": value.table_label,
        "note": value.note,
        "subtotal_minor": value.subtotal_minor,
        "total_minor": value.total_minor,
        "created_by_user_id": value.created_by_user_id,
        "cancelled_by_user_id": value.cancelled_by_user_id,
        "cancelled_at": value.cancelled_at,
        "cancel_reason": value.cancel_reason,
        "paid_by_user_id": value.paid_by_user_id,
        "paid_at": value.paid_at,
        "created_at": value.created_at,
        "updated_at": value.updated_at,
    }


def _item_values(value: OrderItem) -> dict[str, object]:
    return {
        "id": value.id,
        "order_id": value.order_id,
        "client_item_id": value.client_item_id,
        "product_id": value.product_id,
        "product_variant_id": value.product_variant_id,
        "product_name": value.product_name,
        "variant_name": value.variant_name,
        "quantity": value.quantity,
        "base_price_minor": value.base_price_minor,
        "modifier_price_minor": value.modifier_price_minor,
        "unit_price_minor": value.unit_price_minor,
        "line_total_minor": value.line_total_minor,
        "note": value.note,
        "created_at": value.created_at,
        "updated_at": value.updated_at,
    }


def _modifier_values(value) -> dict[str, object]:
    return {
        "id": value.id,
        "order_item_id": value.order_item_id,
        "modifier_group_id": value.modifier_group_id,
        "modifier_group_name": value.modifier_group_name,
        "modifier_option_id": value.modifier_option_id,
        "modifier_option_name": value.modifier_option_name,
        "price_delta_minor": value.price_delta_minor,
        "sort_order": value.sort_order,
    }


def _component_values(value) -> dict[str, object]:
    return {
        "id": value.id,
        "order_item_id": value.order_item_id,
        "inventory_item_id": value.inventory_item_id,
        "inventory_item_name": value.inventory_item_name,
        "base_unit": value.base_unit.value,
        "quantity_per_unit": value.quantity_per_unit,
        "created_at": value.created_at,
    }


def _item_query():
    return select(SalesOrderItemModel).options(
        selectinload(SalesOrderItemModel.modifiers),
        selectinload(SalesOrderItemModel.components),
    )


def _order_query(organization_id: UUID):
    items = selectinload(SalesOrderModel.items)
    return (
        select(SalesOrderModel)
        .where(SalesOrderModel.organization_id == organization_id)
        .options(
            items.selectinload(SalesOrderItemModel.modifiers),
            items.selectinload(SalesOrderItemModel.components),
        )
    )
