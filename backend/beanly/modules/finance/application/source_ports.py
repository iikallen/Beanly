from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class FinancePaymentLineSnapshot:
    id: UUID
    method: str
    amount_minor: int


@dataclass(frozen=True, slots=True)
class FinancePaymentSnapshot:
    payment_id: UUID
    order_id: UUID
    organization_id: UUID
    location_id: UUID
    currency_code: str
    amount_minor: int
    completed_at: datetime
    lines: tuple[FinancePaymentLineSnapshot, ...]


@dataclass(frozen=True, slots=True)
class FinanceRefundPaymentLineSnapshot:
    id: UUID
    method: str
    amount_minor: int


@dataclass(frozen=True, slots=True)
class FinanceRefundSnapshot:
    refund_id: UUID
    organization_id: UUID
    location_id: UUID
    currency_code: str
    amount_minor: int
    cogs_reversal_amount: Decimal
    cogs_quality_status: str | None
    completed_at: datetime
    payment_lines: tuple[FinanceRefundPaymentLineSnapshot, ...]


@dataclass(frozen=True, slots=True)
class FinanceSaleSnapshot:
    order_id: UUID
    organization_id: UUID
    location_id: UUID
    currency_code: str
    cogs_amount: Decimal
    cogs_status: str
    paid_at: datetime
    gross_amount_minor: int = 0
    discount_amount_minor: int = 0


@dataclass(frozen=True, slots=True)
class FinanceWriteOffSnapshot:
    writeoff_id: UUID
    organization_id: UUID
    location_id: UUID
    total_cost_amount: Decimal
    posted_at: datetime
    status: str
    reversed_at: datetime | None


@dataclass(frozen=True, slots=True)
class FinanceCountSnapshot:
    inventory_count_id: UUID
    organization_id: UUID
    location_id: UUID
    posted_at: datetime
    loss_amount: Decimal
    gain_amount: Decimal


@dataclass(frozen=True, slots=True)
class FinanceCashDrawerSnapshot:
    drawer_id: UUID
    organization_id: UUID
    location_id: UUID
    currency_code: str
    variance_minor: int
    closed_at: datetime


class FinanceSourceReader(Protocol):
    async def cash_drawer(
        self, organization_id: UUID, drawer_id: UUID
    ) -> FinanceCashDrawerSnapshot: ...
    async def payment(self, organization_id: UUID, payment_id: UUID) -> FinancePaymentSnapshot: ...

    async def refund(self, organization_id: UUID, refund_id: UUID) -> FinanceRefundSnapshot: ...

    async def sale(self, organization_id: UUID, order_id: UUID) -> FinanceSaleSnapshot: ...

    async def writeoff(
        self, organization_id: UUID, writeoff_id: UUID
    ) -> FinanceWriteOffSnapshot: ...

    async def count(
        self, organization_id: UUID, inventory_count_id: UUID
    ) -> FinanceCountSnapshot: ...

    async def paid_payment_ids(self) -> tuple[tuple[UUID, UUID], ...]: ...

    async def posted_writeoff_ids(self) -> tuple[tuple[UUID, UUID], ...]: ...

    async def posted_count_ids(self) -> tuple[tuple[UUID, UUID], ...]: ...
