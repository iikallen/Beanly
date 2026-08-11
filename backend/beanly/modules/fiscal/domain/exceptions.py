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
