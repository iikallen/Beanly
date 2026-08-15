from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ReservationCreated:
    reservation_id: UUID
    organization_id: UUID
    location_id: UUID


@dataclass(frozen=True, slots=True)
class ReservationCancelled(ReservationCreated):
    pass


@dataclass(frozen=True, slots=True)
class ReservationSeated(ReservationCreated):
    visit_id: UUID


@dataclass(frozen=True, slots=True)
class ReservationNoShow(ReservationCreated):
    pass


@dataclass(frozen=True, slots=True)
class ReservationCompleted(ReservationCreated):
    visit_id: UUID


@dataclass(frozen=True, slots=True)
class WaitlistCreated:
    waitlist_entry_id: UUID
    organization_id: UUID
    location_id: UUID


@dataclass(frozen=True, slots=True)
class WaitlistCancelled(WaitlistCreated):
    pass


@dataclass(frozen=True, slots=True)
class WaitlistSeated(WaitlistCreated):
    visit_id: UUID


@dataclass(frozen=True, slots=True)
class DiningVisitOpened:
    visit_id: UUID
    organization_id: UUID
    location_id: UUID


@dataclass(frozen=True, slots=True)
class DiningVisitClosed(DiningVisitOpened):
    pass
