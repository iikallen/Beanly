from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class PaymentCompleted:
    payment_id: UUID
    order_id: UUID
    organization_id: UUID
    location_id: UUID
    amount_minor: int
