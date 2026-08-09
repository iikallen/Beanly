from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class PosRegisterCreated:
    register_id: UUID


@dataclass(frozen=True, slots=True)
class RegisterShiftOpened:
    shift_id: UUID


@dataclass(frozen=True, slots=True)
class RegisterShiftClosed:
    shift_id: UUID


@dataclass(frozen=True, slots=True)
class OrderCreated:
    order_id: UUID


@dataclass(frozen=True, slots=True)
class OrderUpdated:
    order_id: UUID


@dataclass(frozen=True, slots=True)
class OrderItemAdded:
    order_id: UUID
    item_id: UUID


@dataclass(frozen=True, slots=True)
class OrderItemUpdated:
    order_id: UUID
    item_id: UUID


@dataclass(frozen=True, slots=True)
class OrderItemRemoved:
    order_id: UUID
    item_id: UUID


@dataclass(frozen=True, slots=True)
class OrderCancelled:
    order_id: UUID
