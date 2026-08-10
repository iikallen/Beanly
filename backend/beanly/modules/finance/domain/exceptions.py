class FinanceError(ValueError):
    pass


class FinanceNotFound(FinanceError):
    pass


class InvalidFinanceOperation(FinanceError):
    pass


class DuplicateFinanceResource(FinanceError):
    pass
