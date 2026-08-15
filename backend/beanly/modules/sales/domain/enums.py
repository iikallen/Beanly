from enum import StrEnum


class RegisterShiftStatus(StrEnum):
    OPEN = "OPEN"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"


class OrderType(StrEnum):
    DINE_IN = "DINE_IN"
    TAKEAWAY = "TAKEAWAY"
    DELIVERY = "DELIVERY"


class OrderSource(StrEnum):
    POS = "POS"
    ONLINE = "ONLINE"
    QR = "QR"


class OrderStatus(StrEnum):
    OPEN = "OPEN"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class SaleCostStatus(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    ESTIMATED = "ESTIMATED"
