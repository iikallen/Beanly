from dataclasses import dataclass
from uuid import UUID

from beanly.modules.sales.domain.enums import OrderType


@dataclass(frozen=True, slots=True)
class CreateOrderInput:
    client_order_id: UUID
    shift_id: UUID
    order_type: OrderType
    guest_count: int | None
    table_label: str | None
    note: str | None


@dataclass(frozen=True, slots=True)
class AddOrderItemInput:
    client_item_id: UUID
    variant_id: UUID
    selected_option_ids: tuple[UUID, ...]
    quantity: int
    note: str | None
