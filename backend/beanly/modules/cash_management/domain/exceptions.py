class CashManagementError(Exception):
    code = "CASH_MANAGEMENT_ERROR"


class CashDrawerNotFound(CashManagementError):
    code = "CASH_DRAWER_NOT_FOUND"


class CashDrawerNotOpen(CashManagementError):
    code = "CASH_DRAWER_NOT_OPEN"


class CashDrawerAlreadyClosed(CashManagementError):
    code = "CASH_DRAWER_ALREADY_CLOSED"


class CashMovementInvalid(CashManagementError):
    code = "CASH_MOVEMENT_INVALID"


class CashMovementIdempotencyConflict(CashManagementError):
    code = "CASH_MOVEMENT_IDEMPOTENCY_CONFLICT"


class CashCloseIdempotencyConflict(CashManagementError):
    code = "CASH_CLOSE_IDEMPOTENCY_CONFLICT"


class CashVarianceApprovalRequired(CashManagementError):
    code = "CASH_VARIANCE_APPROVAL_REQUIRED"


class ShiftCloseSyncPending(CashManagementError):
    code = "SHIFT_CLOSE_SYNC_PENDING"


class FiscalShiftCloseFailed(CashManagementError):
    code = "FISCAL_SHIFT_CLOSE_FAILED"


class FiscalShiftCloseUnknown(CashManagementError):
    code = "FISCAL_SHIFT_CLOSE_UNKNOWN"


class FiscalShiftReconciliationRequired(CashManagementError):
    code = "FISCAL_SHIFT_RECONCILIATION_REQUIRED"
