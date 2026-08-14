import logging
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.sales.application.ports import (
    CashDrawerOpenPort,
    NullSalesEventPublisher,
    SalesEventPublisher,
    SalesWarehouse,
    SalesWarehousePort,
)
from beanly.modules.sales.domain.entities import RegisterShift
from beanly.modules.sales.domain.enums import RegisterShiftStatus
from beanly.modules.sales.domain.events import RegisterShiftClosed, RegisterShiftOpened
from beanly.modules.sales.domain.exceptions import (
    InvalidSalesOperation,
    SalesConflict,
    SalesNotFound,
    ShiftHasOpenOrders,
)
from beanly.modules.sales.domain.repositories import SalesRepository

logger = logging.getLogger(__name__)


class ShiftService:
    def __init__(
        self,
        repository: SalesRepository,
        organizations: OrganizationService,
        inventory: SalesWarehousePort,
        publisher: SalesEventPublisher | None = None,
        cash_drawers: CashDrawerOpenPort | None = None,
    ) -> None:
        self.repository = repository
        self.organizations = organizations
        self.inventory = inventory
        self.publisher = publisher or NullSalesEventPublisher()
        self.cash_drawers = cash_drawers

    async def list_warehouses(
        self, context: TenantContext, location_id: UUID
    ) -> tuple[SalesWarehouse, ...]:
        await self.organizations.ensure_location_access(context, location_id)
        values = await self.inventory.list_warehouses(context.organization_id)
        return tuple(value for value in values if value.location_id == location_id)

    async def open(
        self,
        context: TenantContext,
        register_id: UUID,
        warehouse_id: UUID,
        starting_cash_minor: int = 0,
        client_open_id: UUID | None = None,
    ) -> RegisterShift:
        if self.cash_drawers is not None and client_open_id is not None:
            existing_shift_id = await self.cash_drawers.existing_shift_id(context, client_open_id)
            if existing_shift_id is not None:
                existing = await self.repository.get_shift(
                    context.organization_id, existing_shift_id
                )
                if existing is not None:
                    if existing.register_id != register_id or existing.warehouse_id != warehouse_id:
                        raise SalesConflict("Opening id already has another payload")
                    drawer = await self.cash_drawers.open_for_shift(
                        context, existing, starting_cash_minor, client_open_id
                    )
                    return replace(existing, drawer_session_id=drawer.id)
        register = await self.repository.get_register(context.organization_id, register_id)
        if register is None:
            raise SalesNotFound("Register not found")
        await self.organizations.ensure_location_access(context, register.location_id)
        if not register.is_active:
            raise InvalidSalesOperation("Inactive register cannot open a shift")
        warehouse = await self.inventory.get_warehouse(context.organization_id, warehouse_id)
        if warehouse is None:
            raise SalesNotFound("Warehouse not found")
        if warehouse.location_id != register.location_id:
            raise InvalidSalesOperation("Warehouse does not belong to register location")
        if await self.repository.get_current_shift(context.organization_id, register_id):
            raise SalesConflict("Register already has an OPEN shift")
        now = datetime.now(UTC)
        value = RegisterShift(
            uuid4(),
            context.organization_id,
            register.location_id,
            register.id,
            warehouse.id,
            RegisterShiftStatus.OPEN,
            context.user_id,
            None,
            now,
            None,
            now,
            now,
        )
        try:
            opened = await self.repository.add_shift(value)
            drawer = (
                await self.cash_drawers.open_for_shift(
                    context, opened, starting_cash_minor, client_open_id or uuid4()
                )
                if self.cash_drawers is not None
                else None
            )
            await self.repository.commit()
            await self._publish((RegisterShiftOpened(value.id),))
            return replace(opened, drawer_session_id=drawer.id if drawer else None)
        except SalesConflict:
            await self.repository.rollback()
            if self.cash_drawers is not None and client_open_id is not None:
                existing_shift_id = await self.cash_drawers.existing_shift_id(
                    context, client_open_id
                )
                existing = (
                    await self.repository.get_shift(context.organization_id, existing_shift_id)
                    if existing_shift_id is not None
                    else None
                )
                if existing is not None:
                    drawer = await self.cash_drawers.open_for_shift(
                        context, existing, starting_cash_minor, client_open_id
                    )
                    return replace(existing, drawer_session_id=drawer.id)
            raise
        except Exception:
            await self.repository.rollback()
            raise

    async def current(self, context: TenantContext, register_id: UUID) -> RegisterShift | None:
        register = await self.repository.get_register(context.organization_id, register_id)
        if register is None:
            raise SalesNotFound("Register not found")
        await self.organizations.ensure_location_access(context, register.location_id)
        return await self.repository.get_current_shift(context.organization_id, register_id)

    async def close(self, context: TenantContext, shift_id: UUID) -> RegisterShift:
        if self.cash_drawers is not None:
            raise InvalidSalesOperation("Use the cash drawer close workflow")
        try:
            value = await self.repository.get_shift(context.organization_id, shift_id, lock=True)
            if value is None:
                raise SalesNotFound("Shift not found")
            await self.organizations.ensure_location_access(context, value.location_id)
            if value.status != RegisterShiftStatus.OPEN:
                raise InvalidSalesOperation("Shift is already closed")
            if await self.repository.count_open_orders(context.organization_id, value.id):
                raise ShiftHasOpenOrders("Shift has OPEN orders")
            now = datetime.now(UTC)
            closed = await self.repository.update_shift(
                replace(
                    value,
                    status=RegisterShiftStatus.CLOSED,
                    closed_by_user_id=context.user_id,
                    closed_at=now,
                    updated_at=now,
                )
            )
            await self.repository.commit()
            await self._publish((RegisterShiftClosed(value.id),))
            return closed
        except Exception:
            await self.repository.rollback()
            raise

    async def _write(self, operation, events: tuple[object, ...] = ()):
        try:
            result = await operation
            await self.repository.commit()
            await self._publish(events)
            return result
        except Exception:
            await self.repository.rollback()
            raise

    async def _publish(self, events: tuple[object, ...]) -> None:
        for event in events:
            try:
                await self.publisher.publish(event)
            except Exception:
                logger.exception("Sales event publish failed")
