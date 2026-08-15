class OnlineOrderingError(Exception):
    code = "ONLINE_ORDERING_INVALID"


class OnlineOrderingNotFound(OnlineOrderingError):
    code = "ONLINE_ORDERING_NOT_FOUND"


class OnlineOrderingUnavailable(OnlineOrderingError):
    code = "ONLINE_ORDERING_UNAVAILABLE"


class OnlineOrderQuoteChanged(OnlineOrderingError):
    code = "ONLINE_ORDER_QUOTE_CHANGED"

    def __init__(self, message: str, quote=None) -> None:
        super().__init__(message)
        self.quote = quote


class OnlineOrderIdempotencyConflict(OnlineOrderingError):
    code = "ONLINE_ORDER_IDEMPOTENCY_CONFLICT"


class OnlineOrderAlreadyAccepted(OnlineOrderingError):
    code = "ONLINE_ORDER_ALREADY_ACCEPTED"


class OnlineOrderInvalidState(OnlineOrderingError):
    code = "ONLINE_ORDER_INVALID_STATE"


class OnlineOrderInvalidStation(OnlineOrderingError):
    code = "ONLINE_ORDER_INVALID_STATION"


class OnlineOrderCartInvalid(OnlineOrderingError):
    code = "ONLINE_ORDER_CART_INVALID"


class OnlineFulfillmentUnavailable(OnlineOrderingError):
    code = "ONLINE_FULFILLMENT_UNAVAILABLE"


class OnlineFulfillmentSlotUnavailable(OnlineOrderingError):
    code = "ONLINE_FULFILLMENT_SLOT_UNAVAILABLE"


class OnlineOrderCancellationForbidden(OnlineOrderingError):
    code = "ONLINE_ORDER_CANCELLATION_FORBIDDEN"
