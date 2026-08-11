from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RefundCompleted:
    refund_id: UUID
    organization_id: UUID
    location_id: UUID
    order_id: UUID
    payment_id: UUID
    amount_minor: int
    cogs_reversal_amount: Decimal
    cogs_quality_status: str | None
    completed_at: datetime
