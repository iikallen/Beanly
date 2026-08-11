class FiscalError(Exception):
    code = "FISCAL_ERROR"


class TaxProfileNotFound(FiscalError):
    code = "TAX_PROFILE_NOT_FOUND"


class InvalidTaxProfile(FiscalError):
    code = "INVALID_TAX_PROFILE"


class FiscalVariantNotFound(FiscalError):
    code = "FISCAL_VARIANT_NOT_FOUND"


class InvalidFiscalVariantProfile(FiscalError):
    code = "INVALID_FISCAL_VARIANT_PROFILE"


class NktProductNotFound(FiscalError):
    code = "NKT_PRODUCT_NOT_FOUND"


class NktUnavailable(FiscalError):
    code = "NKT_UNAVAILABLE"


class NktRateLimited(NktUnavailable):
    code = "NKT_RATE_LIMITED"


class NktInvalidResponse(NktUnavailable):
    code = "NKT_INVALID_RESPONSE"


class FiscalReceiptNotFound(FiscalError):
    code = "FISCAL_RECEIPT_NOT_FOUND"


class FiscalReceiptStateConflict(FiscalError):
    code = "FISCAL_RECEIPT_STATE_CONFLICT"


class FiscalReconciliationUnavailable(FiscalError):
    code = "FISCAL_RECONCILIATION_UNAVAILABLE"


class FiscalRouteAlreadyConfigured(FiscalError):
    code = "FISCAL_ROUTE_ALREADY_CONFIGURED"


class FiscalRouteNotFound(FiscalError):
    code = "FISCAL_ROUTE_NOT_FOUND"


class FiscalNotReady(FiscalError):
    code = "FISCAL_NOT_READY"
