from datetime import datetime
from decimal import Decimal
from uuid import UUID

from beanly.modules.inventory.domain.value_objects import UnitCode
from beanly.modules.organizations.application.queries.list_locations import ListLocationsQuery
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.payments.application.ports import (
    PayableOrderSnapshot,
    SaleComponentSnapshot,
)
from beanly.modules.payments.domain.exceptions import (
    InvalidPayment,
    OrderAlreadyPaid,
    PaymentNotFound,
)
from beanly.modules.sales.domain.enums import RegisterShiftStatus, SaleCostStatus
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
        order = await self.repository.get_order(context.organization_id, order_id, lock=True)
        if order is None:
            raise PaymentNotFound("Order not found")
        await self.organizations.ensure_location_access(context, order.location_id)
        from beanly.modules.promotions.infrastructure.pricing_service import reprice_order

        if order.offline_session_id is None:
            await reprice_order(
                self.repository.session,
                context.organization_id,
                order_id,
            )
        order = await self.repository.get_order(context.organization_id, order_id, lock=True)
        assert order is not None
        shift = await self.repository.get_shift(context.organization_id, order.shift_id)
        components: dict[UUID, tuple[UnitCode, Decimal]] = {}
        for item in order.items:
            for component in item.components:
                quantity = component.quantity_per_unit * item.quantity
                current = components.get(component.inventory_item_id)
                if current is None:
                    components[component.inventory_item_id] = (
                        component.base_unit,
                        quantity,
                    )
                elif current[0] != component.base_unit:
                    raise InvalidPayment("Order component units conflict")
                else:
                    components[component.inventory_item_id] = (
                        component.base_unit,
                        current[1] + quantity,
                    )
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
            order.number,
            tuple(
                SaleComponentSnapshot(item_id, base_unit, quantity)
                for item_id, (base_unit, quantity) in sorted(
                    components.items(), key=lambda pair: str(pair[0])
                )
            ),
            order.pricing_revision,
        )

    async def mark_order_paid(
        self,
        order_id: UUID,
        paid_by_user_id: UUID,
        paid_at: datetime,
        inventory_transaction_id: UUID | None,
        cogs_amount: Decimal,
        cogs_status: SaleCostStatus,
    ) -> None:
        try:
            await self.repository.mark_order_paid(
                order_id,
                paid_by_user_id,
                paid_at,
                inventory_transaction_id,
                cogs_amount,
                cogs_status,
            )
        except OrderImmutable as exc:
            raise OrderAlreadyPaid("Order is already paid") from exc

    async def ensure_location_access(self, context: TenantContext, location_id: UUID) -> None:
        await self.organizations.ensure_location_access(context, location_id)

    async def accessible_location_ids(self, context: TenantContext) -> tuple[UUID, ...]:
        values = await self.organizations.list_locations(
            ListLocationsQuery(context.user_id, context.organization_id)
        )
        return tuple(value.id for value in values)

    async def ensure_shift_access(self, context: TenantContext, shift_id: UUID) -> None:
        shift = await self.repository.get_shift(context.organization_id, shift_id)
        if shift is None:
            raise PaymentNotFound("Shift not found")
        await self.organizations.ensure_location_access(context, shift.location_id)
