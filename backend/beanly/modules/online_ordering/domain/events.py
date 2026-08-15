from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class OnlineOrderSubmitted:
    organization_id: UUID
    online_order_id: UUID
    sales_order_id: UUID


@dataclass(frozen=True, slots=True)
class OnlineOrderAccepted:
    organization_id: UUID
    online_order_id: UUID
    sales_order_id: UUID


@dataclass(frozen=True, slots=True)
class OnlineOrderRejected:
    organization_id: UUID
    online_order_id: UUID
    sales_order_id: UUID


@dataclass(frozen=True, slots=True)
class OnlineOrderCancelled:
    organization_id: UUID
    online_order_id: UUID
    sales_order_id: UUID
