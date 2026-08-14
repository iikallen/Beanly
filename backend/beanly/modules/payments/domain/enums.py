from enum import StrEnum


class PaymentMethod(StrEnum):
    CASH = "CASH"
    CARD = "CARD"
    OTHER = "OTHER"


class ExternalPaymentMethod(StrEnum):
    CARD = "CARD"
    QR = "QR"


class ExternalPaymentAttemptStatus(StrEnum):
    CREATED = "CREATED"
    TERMINAL_PENDING = "TERMINAL_PENDING"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"
