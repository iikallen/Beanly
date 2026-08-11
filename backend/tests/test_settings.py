import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from beanly.core.config.settings import Settings


def _production_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "production",
        "database_url": "postgresql+asyncpg://beanly:secret@postgres:5432/beanly",
        "redis_url": "redis://redis:6379/0",
        "celery_broker_url": "redis://redis:6379/1",
        "jwt_secret": "production-jwt-secret-with-at-least-32-characters",
        "frontend_url": "https://app.beanly.example",
        "cors_origins": ["https://app.beanly.example"],
        "cookie_secure": True,
        "trusted_hosts": ["api.beanly.example"],
        "forwarded_allow_ips": "172.20.0.0/16",
        "enforce_https": True,
        "rate_limit_enabled": True,
        "audit_enabled": True,
        "audit_ip_hash_secret": "production-audit-hash-secret-at-least-32-characters",
        "otel_enabled": True,
        "otel_exporter_otlp_endpoint": "http://otel-collector:4317",
        "git_sha": "0123456789abcdef",
        "integration_encryption_keys": Fernet.generate_key().decode(),
        "integration_oauth_public_base_url": "https://api.beanly.example",
    }
    values.update(overrides)
    return Settings(**values)


def test_production_rejects_documented_placeholder_secret() -> None:
    with pytest.raises(ValidationError, match="JWT_SECRET must be replaced"):
        Settings(
            environment="production",
            jwt_secret="replace-with-at-least-32-random-characters",
            cookie_secure=True,
        )


def test_production_requires_secure_cookie() -> None:
    with pytest.raises(ValidationError, match="COOKIE_SECURE must be true"):
        Settings(
            environment="production",
            jwt_secret="a-unique-production-secret-that-is-long-enough",
            cookie_secure=False,
        )


def test_environment_name_is_strict() -> None:
    with pytest.raises(ValidationError, match="development.*test.*production"):
        Settings(environment="Production")


def test_valid_production_settings_are_explicit_and_capacity_safe() -> None:
    settings = _production_settings()

    assert settings.trusted_hosts == ["api.beanly.example"]
    assert settings.forwarded_allow_ips == "172.20.0.0/16"
    assert settings.db_connection_budget >= (
        (settings.db_pool_size + settings.db_max_overflow)
        * settings.db_process_count
        + settings.db_admin_reserve
    )


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"trusted_hosts": ["*"]}, "TRUSTED_HOSTS must be explicit"),
        ({"forwarded_allow_ips": "*"}, "cannot trust every address"),
        ({"cors_origins": ["http://app.beanly.example"]}, "explicit HTTPS origins"),
        ({"frontend_url": "http://app.beanly.example"}, "FRONTEND_URL must use HTTPS"),
        ({"enforce_https": False}, "ENFORCE_HTTPS must be true"),
        ({"rate_limit_enabled": False}, "RATE_LIMIT_ENABLED must be true"),
        ({"audit_enabled": False}, "AUDIT_ENABLED must be true"),
        ({"otel_enabled": False}, "OTEL_ENABLED must be true"),
        ({"git_sha": "development"}, "GIT_SHA must identify"),
    ],
)
def test_production_rejects_unsafe_operational_configuration(
    override: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        _production_settings(**override)


def test_connection_budget_cannot_exceed_postgres_capacity() -> None:
    with pytest.raises(ValidationError, match="connection budget"):
        Settings(
            environment="test",
            db_pool_size=10,
            db_max_overflow=5,
            db_process_count=4,
            db_admin_reserve=10,
            db_connection_budget=50,
        )


def test_provider_timeout_budget_must_fit_inside_job_lease() -> None:
    with pytest.raises(ValidationError, match="timeout budget.*shorter.*job lease"):
        Settings(
            environment="test",
            integration_http_connect_timeout_seconds=3,
            integration_http_read_timeout_seconds=10,
            integration_job_lease_safety_margin_seconds=5,
            integration_job_lease_seconds=18,
        )
