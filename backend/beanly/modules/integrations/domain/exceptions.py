class IntegrationError(ValueError):
    pass


class IntegrationNotFound(IntegrationError):
    pass


class UnknownProvider(IntegrationError):
    pass


class InvalidCredentials(IntegrationError):
    pass


class InvalidWebhookSignature(IntegrationError):
    pass


class OAuthSessionInvalid(IntegrationError):
    pass


class TemporaryProviderError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "TEMPORARY_FAILURE",
        http_status: int | None = None,
        public_message: str = "Provider is temporarily unavailable",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.public_message = public_message


class PermanentProviderError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "PERMANENT_FAILURE",
        http_status: int | None = None,
        public_message: str = "Provider rejected the request",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.public_message = public_message
