from enum import StrEnum


class OnlineOrderSource(StrEnum):
    ONLINE = "ONLINE"
    QR = "QR"


class OnlineOrderStatus(StrEnum):
    PENDING = "PENDING"
    AWAITING_PAYMENT = "AWAITING_PAYMENT"
    PAID = "PAID"
    PREPARING = "PREPARING"
    READY = "READY"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class OrderingStationKind(StrEnum):
    TABLE = "TABLE"
    COUNTER = "COUNTER"
    PICKUP_SPOT = "PICKUP_SPOT"
