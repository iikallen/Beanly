from enum import StrEnum


class ReservationStatus(StrEnum):
    BOOKED = "BOOKED"
    SEATED = "SEATED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class ReservationSource(StrEnum):
    GUEST = "GUEST"
    STAFF = "STAFF"
    POS = "POS"


class WaitlistStatus(StrEnum):
    WAITING = "WAITING"
    SEATED = "SEATED"
    CANCELLED = "CANCELLED"


class DiningTableState(StrEnum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    OCCUPIED = "OCCUPIED"
    UNAVAILABLE = "UNAVAILABLE"
