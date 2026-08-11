from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class PosDevicePaired:
    organization_id: UUID
    device_id: UUID


@dataclass(frozen=True, slots=True)
class PosDeviceRevoked:
    organization_id: UUID
    device_id: UUID


@dataclass(frozen=True, slots=True)
class OfflineSessionStarted:
    organization_id: UUID
    session_id: UUID


@dataclass(frozen=True, slots=True)
class OfflineSessionClosed:
    organization_id: UUID
    session_id: UUID


@dataclass(frozen=True, slots=True)
class OfflineOrderSynced:
    organization_id: UUID
    session_id: UUID
    order_id: UUID


@dataclass(frozen=True, slots=True)
class OfflineSyncConflict:
    organization_id: UUID
    session_id: UUID
    client_order_id: UUID
    code: str
