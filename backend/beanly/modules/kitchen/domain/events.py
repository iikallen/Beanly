from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class KitchenTicketCreated:
    organization_id: UUID
    ticket_id: UUID
    order_id: UUID
    payment_id: UUID


@dataclass(frozen=True, slots=True)
class KitchenWorkStarted:
    organization_id: UUID
    ticket_id: UUID
    work_item_id: UUID
    station_id: UUID


@dataclass(frozen=True, slots=True)
class KitchenWorkReady:
    organization_id: UUID
    ticket_id: UUID
    work_item_id: UUID
    station_id: UUID


@dataclass(frozen=True, slots=True)
class KitchenTicketReady:
    organization_id: UUID
    ticket_id: UUID
    order_id: UUID


@dataclass(frozen=True, slots=True)
class KitchenTicketCompleted:
    organization_id: UUID
    ticket_id: UUID
    order_id: UUID


@dataclass(frozen=True, slots=True)
class KitchenTicketRecalled:
    organization_id: UUID
    ticket_id: UUID
    order_id: UUID
