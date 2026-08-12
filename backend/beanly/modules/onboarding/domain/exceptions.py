class OnboardingError(Exception):
    code = "ONBOARDING_ERROR"


class ImportNotFound(OnboardingError):
    code = "IMPORT_NOT_FOUND"


class ImportIdempotencyConflict(OnboardingError):
    code = "IMPORT_IDEMPOTENCY_CONFLICT"


class ImportStateConflict(OnboardingError):
    code = "IMPORT_STATE_CONFLICT"


class ImportValidationFailed(OnboardingError):
    code = "IMPORT_VALIDATION_FAILED"


class ImportEntityNotFound(OnboardingError):
    code = "IMPORT_ENTITY_NOT_FOUND"


class ImportLocationNotFound(OnboardingError):
    code = "IMPORT_LOCATION_NOT_FOUND"


class ImportFileTooLarge(OnboardingError):
    code = "IMPORT_FILE_TOO_LARGE"


class ImportFileTypeInvalid(OnboardingError):
    code = "IMPORT_FILE_TYPE_INVALID"


class ImportParseFailed(OnboardingError):
    code = "IMPORT_PARSE_FAILED"


class TemplateNotFound(OnboardingError):
    code = "TEMPLATE_NOT_FOUND"


class AiExtractionUnavailable(OnboardingError):
    code = "AI_EXTRACTION_UNAVAILABLE"


class ActivationNotReady(OnboardingError):
    code = "ACTIVATION_NOT_READY"
