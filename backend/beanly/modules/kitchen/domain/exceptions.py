class KitchenError(Exception):
    code = "KITCHEN_ERROR"


class KitchenNotFound(KitchenError):
    code = "KITCHEN_NOT_FOUND"


class KitchenInvalid(KitchenError):
    code = "INVALID_KITCHEN_OPERATION"


class KitchenActionIdempotencyConflict(KitchenError):
    code = "KITCHEN_ACTION_IDEMPOTENCY_CONFLICT"


class KitchenWorkNotReady(KitchenError):
    code = "KITCHEN_WORK_NOT_READY"
