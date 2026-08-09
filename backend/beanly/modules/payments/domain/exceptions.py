class PaymentError(Exception):
    code = "PAYMENT_ERROR"


class PaymentNotFound(PaymentError):
    code = "PAYMENT_NOT_FOUND"


class PaymentConflict(PaymentError):
    code = "PAYMENT_CONFLICT"


class PaymentIdempotencyConflict(PaymentConflict):
    code = "PAYMENT_IDEMPOTENCY_CONFLICT"


class OrderAlreadyPaid(PaymentConflict):
    code = "ORDER_ALREADY_PAID"


class OrderNotPayable(PaymentConflict):
    code = "ORDER_NOT_PAYABLE"


class OrderShiftClosed(PaymentConflict):
    code = "ORDER_SHIFT_CLOSED"


class InvalidPayment(PaymentError):
    code = "INVALID_PAYMENT"


class PaymentAmountMismatch(InvalidPayment):
    code = "PAYMENT_AMOUNT_MISMATCH"
