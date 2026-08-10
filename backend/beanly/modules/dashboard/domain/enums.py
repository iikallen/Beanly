from enum import StrEnum


class DashboardPeriod(StrEnum):
    TODAY = "TODAY"
    YESTERDAY = "YESTERDAY"
    LAST_7_DAYS = "LAST_7_DAYS"
    THIS_MONTH = "THIS_MONTH"
    CUSTOM = "CUSTOM"


class TrendBucket(StrEnum):
    HOUR = "HOUR"
    DAY = "DAY"
    WEEK = "WEEK"


class MetricDirection(StrEnum):
    UP = "UP"
    DOWN = "DOWN"
    FLAT = "FLAT"


class AlertSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
