from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from beanly.modules.dashboard.application.dto import PaymentMixRow
from beanly.modules.payments.application.reporting_service import (
    PaymentsReportingService,
)


class PaymentsDashboardGateway:
    def __init__(self, reporting: PaymentsReportingService) -> None:
        self.reporting = reporting

    async def mix(
        self,
        organization_id: UUID,
        location_ids: tuple[UUID, ...],
        date_from: datetime,
        date_to: datetime,
    ) -> tuple[PaymentMixRow, ...]:
        values = await self.reporting.payment_mix(
            organization_id, location_ids, date_from, date_to
        )
        total = sum((value.amount for value in values), Decimal(0))
        return tuple(
            PaymentMixRow(
                value.method,
                value.amount,
                (
                    (value.amount * 100 / total).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )
                    if total
                    else Decimal(0)
                ),
            )
            for value in values
        )
