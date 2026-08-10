import hashlib
import hmac
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from beanly.core.config.settings import Settings
from beanly.modules.integrations.application.connection_service import _validate_config
from beanly.modules.integrations.application.dto import (
    FiscalItem,
    FiscalPaymentLine,
    FiscalSaleCommand,
)
from beanly.modules.integrations.domain.exceptions import (
    InvalidCredentials,
    InvalidWebhookSignature,
    UnknownProvider,
)
from beanly.modules.integrations.infrastructure.crypto.fernet_cipher import (
    FernetSecretCipher,
)
from beanly.modules.integrations.infrastructure.http.client import (
    ProviderHttpClientFactory,
)
from beanly.modules.integrations.infrastructure.providers.mock import (
    MockFiscalProvider,
)
from beanly.modules.integrations.infrastructure.providers.registry import (
    build_provider_registry,
)


def _production_settings(key: str) -> Settings:
    return Settings(
        environment="production",
        jwt_secret="a-unique-production-secret-that-is-long-enough",
        cookie_secure=True,
        integration_encryption_keys=key,
        integration_oauth_public_base_url="https://beanly.example",
    )


def _sale() -> FiscalSaleCommand:
    return FiscalSaleCommand(
        payment_id=uuid4(),
        order_number=1042,
        occurred_at=datetime(2026, 8, 10, tzinfo=UTC),
        currency="KZT",
        items=(FiscalItem("Flat white", 1, 170_000, 170_000),),
        payment_lines=(FiscalPaymentLine("CARD", 170_000),),
        total_minor=170_000,
    )


def test_production_requires_non_default_integration_encryption_key() -> None:
    for keys in ("", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="):
        with pytest.raises(
            ValidationError, match="INTEGRATION_ENCRYPTION_KEYS must be set"
        ):
            _production_settings(keys)

    with pytest.raises(ValidationError, match="invalid Fernet key"):
        Settings(environment="test", integration_encryption_keys="not-a-fernet-key")
    with pytest.raises(ValidationError, match="must use HTTPS"):
        Settings(
            environment="production",
            jwt_secret="a-unique-production-secret-that-is-long-enough",
            cookie_secure=True,
            integration_encryption_keys=Fernet.generate_key().decode(),
            integration_oauth_public_base_url="http://beanly.example",
        )


def test_credentials_are_authenticated_encrypted_and_rotation_is_backward_compatible() -> None:
    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()
    plaintext = b'{"api_key":"stage18-super-secret"}'
    old_cipher = FernetSecretCipher([old_key])
    ciphertext = old_cipher.encrypt(plaintext)

    assert "stage18-super-secret" not in ciphertext
    with pytest.raises(InvalidCredentials):
        FernetSecretCipher([new_key]).decrypt(ciphertext)

    rotating_cipher = FernetSecretCipher([new_key, old_key])
    assert rotating_cipher.decrypt(ciphertext) == plaintext
    rotated = rotating_cipher.rotate(ciphertext)
    assert rotating_cipher.decrypt(rotated) == plaintext
    assert FernetSecretCipher([new_key]).decrypt(rotated) == plaintext
    with pytest.raises(InvalidCredentials):
        FernetSecretCipher([old_key]).decrypt(rotated)


def test_provider_registry_is_code_owned_and_mock_is_not_in_production() -> None:
    development = build_provider_registry(Settings(environment="test"))
    assert [descriptor.code for descriptor in development.descriptors()] == [
        "mock_fiscal"
    ]
    assert development.descriptor("mock_fiscal").location_scoped
    with pytest.raises(UnknownProvider):
        development.adapter("database_inserted_provider")

    production = build_provider_registry(
        _production_settings(Fernet.generate_key().decode())
    )
    assert production.descriptors() == ()
    with pytest.raises(UnknownProvider):
        production.adapter("mock_fiscal")


@pytest.mark.parametrize(
    "config",
    [
        {"api_key": "plaintext"},
        {"nested": {"refresh_token": "plaintext"}},
        {"items": [{"webhook_secret": "plaintext"}]},
        {"provider_url": "http://127.0.0.1"},
        {"nested": {"base_url": "http://169.254.169.254"}},
    ],
)
def test_config_recursively_rejects_secrets_and_provider_urls(
    config: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        _validate_config(config)


@pytest.mark.anyio
async def test_http_client_factory_sets_every_timeout_and_pool_limit() -> None:
    settings = Settings(
        environment="test",
        integration_http_connect_timeout_seconds=2.5,
        integration_http_read_timeout_seconds=7.5,
        integration_http_max_connections=17,
    )
    client = ProviderHttpClientFactory(settings).create(
        base_url="https://provider.invalid"
    )
    try:
        assert client.timeout.connect == 2.5
        assert client.timeout.read == 7.5
        assert client.timeout.write == 7.5
        assert client.timeout.pool == 2.5
        pool = client._transport._pool  # type: ignore[attr-defined]
        assert pool._max_connections == 17
        assert pool._max_keepalive_connections == 17
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_mock_fiscal_is_idempotent_and_webhook_verification_sanitizes_payload() -> None:
    provider = MockFiscalProvider()
    credentials = {"api_key": "mock-secret"}
    first = await provider.fiscalize_sale(
        _sale(), credentials=credentials, idempotency_key="fiscalize:payment:42"
    )
    duplicate = await provider.fiscalize_sale(
        _sale(), credentials=credentials, idempotency_key="fiscalize:payment:42"
    )
    assert duplicate == first

    raw = json.dumps(
        {
            "id": "evt_42",
            "type": "receipt.ready",
            "data": {
                "receipt_id": "receipt_42",
                "status": "ready",
                "access_token": "must-not-be-persisted",
            },
        },
        separators=(",", ":"),
    ).encode()
    signature = hmac.new(b"mock-secret", raw, hashlib.sha256).hexdigest()
    normalized = provider.verify_webhook(
        raw, {"x-mock-signature": signature}, credentials
    )
    assert normalized.external_event_id == "evt_42"
    assert normalized.payload == {"receipt_id": "receipt_42", "status": "ready"}
    assert "access_token" not in repr(normalized)

    with pytest.raises(InvalidWebhookSignature):
        provider.verify_webhook(
            raw, {"x-mock-signature": "invalid"}, credentials
        )
