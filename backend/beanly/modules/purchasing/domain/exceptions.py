class PurchasingError(Exception):
    pass


class PurchasingNotFound(PurchasingError):
    pass


class InvalidPurchasingOperation(PurchasingError):
    pass


class DuplicatePurchasingResource(PurchasingError):
    pass


class OverReceiptConfirmationRequired(PurchasingError):
    code = "RECEIVED_QUANTITY_EXCEEDS_ORDER"


class InvalidPurchaseQuantity(PurchasingError):
    pass
