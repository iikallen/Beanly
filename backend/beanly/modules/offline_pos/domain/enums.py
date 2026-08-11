from enum import StrEnum


class PosDeviceStatus(StrEnum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class OfflineSessionStatus(StrEnum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class OfflineSyncStatus(StrEnum):
    SYNCED = "SYNCED"
    CONFLICT = "CONFLICT"
