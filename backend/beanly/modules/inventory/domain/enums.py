from enum import StrEnum


class InventoryTransactionType(StrEnum):
    PURCHASE = "PURCHASE"
    SALE = "SALE"
    WRITE_OFF = "WRITE_OFF"
    ADJUSTMENT = "ADJUSTMENT"
    TRANSFER_IN = "TRANSFER_IN"
    TRANSFER_OUT = "TRANSFER_OUT"
    RETURN_IN = "RETURN_IN"
    RETURN_OUT = "RETURN_OUT"
    PRODUCTION = "PRODUCTION"
    OPENING_BALANCE = "OPENING_BALANCE"


class InventoryTransactionStatus(StrEnum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    REVERSED = "REVERSED"
