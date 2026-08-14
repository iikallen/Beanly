class CustomerError(Exception):
    code = "CUSTOMER_ERROR"


class CustomerNotFound(CustomerError):
    code = "CUSTOMER_NOT_FOUND"


class CustomerPhoneConflict(CustomerError):
    code = "CUSTOMER_PHONE_CONFLICT"


class CustomerInvalid(CustomerError):
    code = "CUSTOMER_INVALID"


class LoyaltyInvalid(CustomerError):
    code = "LOYALTY_INVALID"


class LoyaltyOrderImmutable(CustomerError):
    code = "ORDER_IMMUTABLE"


class LoyaltyInsufficientBalance(CustomerError):
    code = "LOYALTY_INSUFFICIENT_BALANCE"


class LoyaltyIdempotencyConflict(CustomerError):
    code = "LOYALTY_IDEMPOTENCY_CONFLICT"
