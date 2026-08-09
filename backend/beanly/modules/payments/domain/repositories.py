from datetime import datetime
from typing import Protocol
from uuid import UUID

from beanly.modules.payments.domain.entities import Payment, ShiftPaymentSummary
from beanly.modules.payments.domain.enums import PaymentMethod


class PaymentRepository(Protocol):
    async def add(self, value: Payment) -> Payment: ...
    async def get(self, organization_id: UUID, payment_id: UUID) -> Payment | None: ...
    async def get_by_order(
        self, organization_id: UUID, order_id: UUID
    ) -> Payment | None: ...
    async def get_by_client_id(
        self, organization_id: UUID, client_payment_id: UUID
    ) -> Payment | None: ...
    async def list(
        self,
        organization_id: UUID,
        location_ids: tuple[UUID, ...],
        *,
        shift_id: UUID | None,
        date_from: datetime | None,
        date_to: datetime | None,
        method: PaymentMethod | None,
    ) -> list[Payment]: ...
    async def shift_summary(
        self, organization_id: UUID, shift_id: UUID
    ) -> ShiftPaymentSummary: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...

