from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from beanly.modules.payments.domain.repositories import PaymentRepository

MINOR = Decimal(100)


@dataclass(frozen=True, slots=True)
class PaymentSummary:
    revenue: Decimal
    paid_orders: int


@dataclass(frozen=True, slots=True)
class PaymentTrendRow:
    revenue: Decimal
    orders: int


@dataclass(frozen=True, slots=True)
class PaymentLocationSummary:
    location_id: UUID
    revenue: Decimal
    paid_orders: int


@dataclass(frozen=True, slots=True)
class PaymentMix:
    method: str
    amount: Decimal


class PaymentsReportingService:
    def __init__(self, repository: PaymentRepository) -> None:
        self.repository = repository

    async def sales_summary(
        self,
        organization_id: UUID,
        location_ids: tuple[UUID, ...],
        date_from: datetime,
        date_to: datetime,
    ) -> PaymentSummary:
        amount_minor, orders = await self.repository.dashboard_summary(
            organization_id, location_ids, date_from, date_to
        )
        return PaymentSummary(Decimal(amount_minor) / MINOR, orders)

    async def sales_trend(
        self,
        organization_id: UUID,
        location_ids: tuple[UUID, ...],
        buckets: tuple[tuple[datetime, datetime], ...],
    ) -> tuple[PaymentTrendRow, ...]:
        rows = await self.repository.dashboard_trend(
            organization_id, location_ids, buckets
        )
        return tuple(
            PaymentTrendRow(Decimal(amount_minor) / MINOR, orders)
            for amount_minor, orders in rows
        )

    async def location_sales_summary(
        self,
        organization_id: UUID,
        location_ids: tuple[UUID, ...],
        date_from: datetime,
        date_to: datetime,
    ) -> tuple[PaymentLocationSummary, ...]:
        rows = await self.repository.dashboard_locations(
            organization_id, location_ids, date_from, date_to
        )
        return tuple(
            PaymentLocationSummary(location_id, Decimal(amount_minor) / MINOR, orders)
            for location_id, amount_minor, orders in rows
        )

    async def payment_mix(
        self,
        organization_id: UUID,
        location_ids: tuple[UUID, ...],
        date_from: datetime,
        date_to: datetime,
    ) -> tuple[PaymentMix, ...]:
        rows = await self.repository.dashboard_mix(
            organization_id, location_ids, date_from, date_to
        )
        return tuple(
            PaymentMix(method, Decimal(amount_minor) / MINOR)
            for method, amount_minor in rows
        )
