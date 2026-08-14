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


class LoyaltyReservationInvalid(PaymentConflict):
    code = "LOYALTY_RESERVATION_INVALID"


class ExternalPaymentAttemptNotFound(PaymentError):
    code = "PAYMENT_ATTEMPT_NOT_FOUND"


class ExternalPaymentAttemptConflict(PaymentConflict):
    code = "PAYMENT_ATTEMPT_STATE_CONFLICT"


class ExternalPaymentAttemptUnknown(ExternalPaymentAttemptConflict):
    code = "PAYMENT_ATTEMPT_UNKNOWN"


class ExternalPaymentAttemptIdempotencyConflict(ExternalPaymentAttemptConflict):
    code = "PAYMENT_ATTEMPT_IDEMPOTENCY_CONFLICT"


class ExternalPaymentAttemptAmountMismatch(InvalidPayment):
    code = "PAYMENT_ATTEMPT_AMOUNT_MISMATCH"


class ExternalPaymentUnsupportedCurrency(InvalidPayment):
    code = "PAYMENT_ATTEMPT_UNSUPPORTED_CURRENCY"


class ExternalPaymentUnsupportedAmount(InvalidPayment):
    code = "PAYMENT_ATTEMPT_UNSUPPORTED_AMOUNT"


class ExternalTerminalUnavailable(PaymentError):
    code = "PAYMENT_TERMINAL_UNAVAILABLE"


class TerminalBindingNotFound(PaymentError):
    code = "TERMINAL_BINDING_NOT_FOUND"


class TerminalBindingConflict(PaymentConflict):
    code = "TERMINAL_BINDING_CONFLICT"


class FiscalCheckoutUnavailable(PaymentConflict):
    code = "FISCAL_NOT_READY"
