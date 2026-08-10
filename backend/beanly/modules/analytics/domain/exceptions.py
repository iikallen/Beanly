class AnalyticsError(Exception):
    pass


class AnalyticsProjectionError(AnalyticsError):
    pass


class AnalyticsLocationNotFound(AnalyticsError):
    pass


class InvalidAnalyticsRange(AnalyticsError):
    pass


class AnalyticsFinancialAccessDenied(AnalyticsError):
    pass
