from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.sales.domain.enums import OrderStatus


@dataclass(frozen=True, slots=True)
class PayableOrderSnapshot:
    id: UUID
    organization_id: UUID
    location_id: UUID
    shift_id: UUID
    warehouse_id: UUID
    status: OrderStatus
    currency_code: str
    total_minor: int
    created_by_user_id: UUID
    has_items: bool
    shift_is_open: bool


class SalesSettlementPort(Protocol):
    async def lock_order_for_payment(
        self, context: TenantContext, order_id: UUID
    ) -> PayableOrderSnapshot: ...

    async def mark_order_paid(
        self, order_id: UUID, paid_by_user_id: UUID, paid_at: datetime
    ) -> None: ...

    async def ensure_location_access(
        self, context: TenantContext, location_id: UUID
    ) -> None: ...

    async def accessible_location_ids(
        self, context: TenantContext
    ) -> tuple[UUID, ...]: ...

    async def ensure_shift_access(
        self, context: TenantContext, shift_id: UUID
    ) -> None: ...


class PaymentEventPublisher(Protocol):
    async def publish(self, event: object) -> None: ...


class NullPaymentEventPublisher:
    async def publish(self, event: object) -> None:
        pass
