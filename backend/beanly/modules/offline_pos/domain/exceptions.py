class OfflinePosError(Exception):
    code = "OFFLINE_POS_ERROR"


class OfflinePosUnauthorized(OfflinePosError):
    code = "POS_DEVICE_UNAUTHORIZED"


class OfflinePosNotFound(OfflinePosError):
    code = "OFFLINE_POS_NOT_FOUND"


class OfflinePosConflict(OfflinePosError):
    code = "OFFLINE_POS_CONFLICT"


class ActiveDeviceExists(OfflinePosConflict):
    code = "ACTIVE_POS_DEVICE_EXISTS"


class OfflineSessionExpired(OfflinePosConflict):
    code = "OFFLINE_SESSION_EXPIRED"


class OfflineRevisionConflict(OfflinePosConflict):
    code = "OFFLINE_REVISION_CONFLICT"


class OfflinePermissionDenied(OfflinePosConflict):
    code = "OFFLINE_PERMISSION_DENIED"


class OrderChangedOnServer(OfflinePosConflict):
    code = "ORDER_CHANGED_ON_SERVER"


class CatalogSnapshotInvalid(OfflinePosConflict):
    code = "CATALOG_SNAPSHOT_INVALID"
