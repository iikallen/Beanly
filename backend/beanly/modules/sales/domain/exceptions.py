class SalesError(Exception):
    code = "SALES_ERROR"


class SalesNotFound(SalesError):
    code = "SALES_NOT_FOUND"


class SalesConflict(SalesError):
    code = "SALES_CONFLICT"


class InvalidSalesOperation(SalesError):
    code = "INVALID_SALES_OPERATION"


class SalesAccessDenied(SalesError):
    code = "SALES_ACCESS_DENIED"


class ProductUnavailable(InvalidSalesOperation):
    code = "PRODUCT_UNAVAILABLE"


class ShiftHasOpenOrders(SalesConflict):
    code = "SHIFT_HAS_OPEN_ORDERS"


class OrderImmutable(SalesConflict):
    code = "ORDER_IMMUTABLE"


class InvalidModifierSelection(InvalidSalesOperation):
    code = "INVALID_MODIFIER_SELECTION"


class InvalidModifierRecipe(InvalidSalesOperation):
    code = "INVALID_MODIFIER_RECIPE"
