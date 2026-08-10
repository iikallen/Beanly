from enum import StrEnum


class IntegrationCapability(StrEnum):
    PAYMENT = "PAYMENT"
    FISCAL = "FISCAL"
    DELIVERY = "DELIVERY"
    NOTIFICATION = "NOTIFICATION"


class IntegrationAuthType(StrEnum):
    NONE = "NONE"
    API_KEY = "API_KEY"
    OAUTH2 = "OAUTH2"


class IntegrationConnectionStatus(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    REVOKED = "REVOKED"


class IntegrationJobStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    RETRYING = "RETRYING"
    SUCCESS = "SUCCESS"
    DEAD = "DEAD"


class IntegrationAttemptOutcome(StrEnum):
    SUCCESS = "SUCCESS"
    TEMPORARY_FAILURE = "TEMPORARY_FAILURE"
    PERMANENT_FAILURE = "PERMANENT_FAILURE"
