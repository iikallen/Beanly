from enum import StrEnum


class KitchenStationRole(StrEnum):
    PREP = "PREP"
    EXPO = "EXPO"
    PREP_EXPO = "PREP_EXPO"


class KitchenRoutingScope(StrEnum):
    CATEGORY = "CATEGORY"
    VARIANT = "VARIANT"


class KitchenWorkStatus(StrEnum):
    QUEUED = "QUEUED"
    PREPARING = "PREPARING"
    READY = "READY"
    CANCELLED = "CANCELLED"


class KitchenTicketStatus(StrEnum):
    QUEUED = "QUEUED"
    PREPARING = "PREPARING"
    READY = "READY"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
