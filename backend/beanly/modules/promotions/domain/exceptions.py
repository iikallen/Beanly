class PromotionError(Exception):
    code = "INVALID_PROMOTION"


class PromotionNotFound(PromotionError):
    code = "PROMOTION_NOT_FOUND"


class PromotionConflict(PromotionError):
    code = "PROMOTION_CONFLICT"


class DiscountIdempotencyConflict(PromotionConflict):
    code = "DISCOUNT_IDEMPOTENCY_CONFLICT"


class PromotionCodeUnavailable(PromotionConflict):
    code = "PROMOTION_CODE_UNAVAILABLE"
