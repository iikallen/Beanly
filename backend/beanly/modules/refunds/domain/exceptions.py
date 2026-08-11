class RefundError(Exception):
    code = "REFUND_ERROR"


class InvalidRefund(RefundError):
    code = "INVALID_REFUND"


class RefundNotFound(RefundError):
    code = "REFUND_NOT_FOUND"


class RefundIdempotencyConflict(RefundError):
    code = "REFUND_IDEMPOTENCY_CONFLICT"


class RefundConflict(RefundError):
    code = "REFUND_CONFLICT"


class RefundQuantityExceeded(RefundError):
    code = "REFUND_QUANTITY_EXCEEDED"


class RefundPaymentAmountExceeded(RefundError):
    code = "REFUND_PAYMENT_AMOUNT_EXCEEDED"


class OrderNotRefundable(RefundError):
    code = "ORDER_NOT_REFUNDABLE"


class ExternalRefundNotConfirmed(RefundError):
    code = "EXTERNAL_REFUND_NOT_CONFIRMED"


class RefundTotalMismatch(RefundError):
    code = "REFUND_TOTAL_MISMATCH"
