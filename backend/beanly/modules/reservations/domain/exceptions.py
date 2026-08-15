class ReservationError(Exception):
    code = "RESERVATION_ERROR"


class ReservationNotFound(ReservationError):
    code = "RESERVATION_NOT_FOUND"


class InvalidGuestToken(ReservationNotFound):
    code = "INVALID_GUEST_TOKEN"


class ReservationConflict(ReservationError):
    code = "RESERVATION_CONFLICT"


class SlotUnavailable(ReservationConflict):
    code = "SLOT_UNAVAILABLE"


class TableOccupied(ReservationConflict):
    code = "TABLE_OCCUPIED"


class InvalidReservationTransition(ReservationConflict):
    code = "INVALID_RESERVATION_TRANSITION"


class ReservationIdempotencyConflict(ReservationConflict):
    code = "IDEMPOTENCY_CONFLICT"


class ReservationsDisabled(ReservationError):
    code = "RESERVATIONS_DISABLED"


class InvalidPartySize(ReservationError):
    code = "INVALID_PARTY_SIZE"


class OutsideBookingHorizon(ReservationError):
    code = "OUTSIDE_BOOKING_HORIZON"


class BelowLeadTime(ReservationError):
    code = "BELOW_LEAD_TIME"


class LocationClosed(ReservationError):
    code = "LOCATION_CLOSED"


class NoMatchingTable(ReservationError):
    code = "NO_MATCHING_TABLE"
