from datetime import datetime
from uuid import UUID

from beanly.modules.organizations.application.queries.list_locations import ListLocationsQuery
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.payments.application.ports import PayableOrderSnapshot
from beanly.modules.payments.domain.exceptions import OrderAlreadyPaid, PaymentNotFound
from beanly.modules.sales.domain.enums import RegisterShiftStatus
from beanly.modules.sales.domain.exceptions import OrderImmutable
from beanly.modules.sales.domain.repositories import SalesRepository


class SalesSettlementGateway:
    def __init__(
        self,
        repository: SalesRepository,
        organizations: OrganizationService,
    ) -> None:
        self.repository = repository
        self.organizations = organizations

    async def lock_order_for_payment(
        self, context: TenantContext, order_id: UUID
    ) -> PayableOrderSnapshot:
        order = await self.repository.get_order(
            context.organization_id, order_id, lock=True
        )
        if order is None:
            raise PaymentNotFound("Order not found")
        await self.organizations.ensure_location_access(context, order.location_id)
        shift = await self.repository.get_shift(context.organization_id, order.shift_id)
        return PayableOrderSnapshot(
            order.id,
            order.organization_id,
            order.location_id,
            order.shift_id,
            order.warehouse_id,
            order.status,
            order.currency_code,
            order.total_minor,
            order.created_by_user_id,
            bool(order.items),
            shift is not None and shift.status == RegisterShiftStatus.OPEN,
        )

    async def mark_order_paid(
        self, order_id: UUID, paid_by_user_id: UUID, paid_at: datetime
    ) -> None:
        try:
            await self.repository.mark_order_paid(order_id, paid_by_user_id, paid_at)
        except OrderImmutable as exc:
            raise OrderAlreadyPaid("Order is already paid") from exc

    async def ensure_location_access(
        self, context: TenantContext, location_id: UUID
    ) -> None:
        await self.organizations.ensure_location_access(context, location_id)

    async def accessible_location_ids(
        self, context: TenantContext
    ) -> tuple[UUID, ...]:
        values = await self.organizations.list_locations(
            ListLocationsQuery(context.user_id, context.organization_id)
        )
        return tuple(value.id for value in values)

    async def ensure_shift_access(
        self, context: TenantContext, shift_id: UUID
    ) -> None:
        shift = await self.repository.get_shift(context.organization_id, shift_id)
        if shift is None:
            raise PaymentNotFound("Shift not found")
        await self.organizations.ensure_location_access(context, shift.location_id)
