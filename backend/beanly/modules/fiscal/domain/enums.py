from enum import StrEnum


class FiscalComplianceStatus(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"


class FiscalEnforcementMode(StrEnum):
    DISABLED = "DISABLED"
    TEST = "TEST"
    LIVE_REQUIRED = "LIVE_REQUIRED"


class FiscalReceiptSource(StrEnum):
    SALE = "SALE"
    REFUND = "REFUND"


class FiscalReceiptStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SUCCEEDED = "SUCCEEDED"
    RETRYING = "RETRYING"
    UNKNOWN = "UNKNOWN"
    DEAD = "DEAD"


class FiscalRouteSourceMode(StrEnum):
    EXTERNAL_KKM = "EXTERNAL_KKM"
    PAYMENT_TERMINAL_KKM = "PAYMENT_TERMINAL_KKM"
