import hashlib
import hmac
import json
from collections.abc import Mapping
from uuid import NAMESPACE_URL, uuid5

from beanly.modules.integrations.application.dto import (
    FiscalReceiptResult,
    FiscalSaleCommand,
    NormalizedWebhookEvent,
)
from beanly.modules.integrations.domain.exceptions import (
    InvalidWebhookSignature,
    PermanentProviderError,
    TemporaryProviderError,
)


class MockFiscalProvider:
    """Development/test adapter proving retries, idempotency and webhook verification."""

    async def health_check(self, credentials: Mapping[str, object]) -> None:
        self._validate(credentials)

    async def fiscalize_sale(
        self,
        command: FiscalSaleCommand,
        *,
        credentials: Mapping[str, object],
        idempotency_key: str,
    ) -> FiscalReceiptResult:
        self._validate(credentials)
        if credentials.get("simulate") == "temporary_failure":
            raise TemporaryProviderError("Mock temporary failure", code="MOCK_TEMPORARY")
        if credentials.get("simulate") == "permanent_failure":
            raise PermanentProviderError("Mock permanent failure", code="MOCK_PERMANENT")
        suffix = hashlib.sha256(idempotency_key.encode()).hexdigest()[:12]
        return FiscalReceiptResult(
            external_receipt_id=f"mock-receipt-{suffix}",
            receipt_number=f"M-{command.order_number}",
            receipt_url=None,
            provider_request_id=str(uuid5(NAMESPACE_URL, f"beanly:{idempotency_key}")),
        )

    def verify_webhook(
        self,
        raw_body: bytes,
        headers: Mapping[str, str],
        credentials: Mapping[str, object],
    ) -> NormalizedWebhookEvent:
        secret = str(credentials.get("webhook_secret") or credentials.get("api_key") or "")
        expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        if not secret or not hmac.compare_digest(headers.get("x-mock-signature", ""), expected):
            raise InvalidWebhookSignature("Invalid webhook signature")
        try:
            value = json.loads(raw_body)
            external_id = str(value["id"])
            event_type = str(value["type"])
            data = value.get("data", {})
            if not isinstance(data, dict):
                raise ValueError
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise InvalidWebhookSignature("Invalid webhook payload") from exc
        allowed = {key: data[key] for key in ("receipt_id", "status") if key in data}
        return NormalizedWebhookEvent(external_id, event_type, allowed)

    @staticmethod
    def _validate(credentials: Mapping[str, object]) -> None:
        if not credentials.get("api_key"):
            raise PermanentProviderError("API key is required", code="INVALID_CREDENTIALS")
