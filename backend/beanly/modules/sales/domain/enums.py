from enum import StrEnum


class RegisterShiftStatus(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class OrderType(StrEnum):
    DINE_IN = "DINE_IN"
    TAKEAWAY = "TAKEAWAY"
    DELIVERY = "DELIVERY"


class OrderStatus(StrEnum):
    OPEN = "OPEN"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class SaleCostStatus(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    ESTIMATED = "ESTIMATED"
