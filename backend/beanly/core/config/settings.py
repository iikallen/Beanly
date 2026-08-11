import base64
import binascii
import ipaddress
from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    environment: Literal["development", "test", "staging", "production"] = "development"
    database_url: str = "postgresql+asyncpg://beanly:beanly@localhost:5432/beanly"
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    jwt_secret: str = Field(default="dev-only-change-me-before-production", min_length=32)
    jwt_issuer: str = "beanly"
    jwt_audience: str = "beanly-api"
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    invitation_days: int = 7
    frontend_url: str = "http://localhost:3000"
    cors_origins: list[str] = ["http://localhost:3000"]
    cookie_secure: bool = False
    trusted_hosts: list[str] = ["localhost", "127.0.0.1", "test", "testserver"]
    forwarded_allow_ips: str = "127.0.0.1"
    enforce_https: bool = False
    service_name: str = "beanly-api"
    app_version: str = "0.1.0"
    git_sha: str = "development"
    build_time: str = "development"
    db_pool_size: int = Field(default=10, ge=1, le=100)
    db_max_overflow: int = Field(default=10, ge=0, le=100)
    db_pool_timeout_seconds: float = Field(default=5, gt=0, le=120)
    db_pool_recycle_seconds: int = Field(default=1800, ge=30, le=86400)
    db_statement_timeout_ms: int = Field(default=10_000, ge=100, le=300_000)
    db_worker_statement_timeout_ms: int = Field(default=60_000, ge=1000, le=900_000)
    db_lock_timeout_ms: int = Field(default=3_000, ge=100, le=60_000)
    db_connection_budget: int = Field(default=100, ge=10, le=10_000)
    db_process_count: int = Field(default=4, ge=1, le=100)
    db_admin_reserve: int = Field(default=10, ge=1, le=1000)
    rate_limit_enabled: bool = False
    audit_enabled: bool = False
    audit_ip_hash_secret: str = "dev-only-audit-ip-hash-secret"
    otel_enabled: bool = False
    otel_exporter_otlp_endpoint: str | None = None
    outbox_batch_size: int = Field(default=50, ge=1, le=1000)
    outbox_poll_interval_seconds: float = Field(default=1, gt=0, le=60)
    outbox_lease_seconds: int = Field(default=30, ge=1, le=3600)
    outbox_max_attempts: int = Field(default=12, ge=1, le=1000)
    integration_encryption_keys: str = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
    integration_http_connect_timeout_seconds: float = Field(default=3, gt=0, le=120)
    integration_http_read_timeout_seconds: float = Field(default=10, gt=0, le=300)
    integration_http_max_connections: int = Field(default=50, ge=1, le=1000)
    integration_oauth_public_base_url: str = "http://localhost:8000"
    integration_job_batch_size: int = Field(default=25, ge=1, le=1000)
    integration_job_lease_seconds: int = Field(default=60, ge=1, le=3600)
    integration_job_lease_safety_margin_seconds: int = Field(default=5, ge=1, le=300)
    integration_job_max_attempts: int = Field(default=10, ge=1, le=1000)
    integration_poll_interval_seconds: float = Field(default=1, gt=0, le=60)

    @model_validator(mode="after")
    def reject_development_secret_in_production(self) -> "Settings":
        self._validate_proxy_networks()
        if (
            self.integration_http_connect_timeout_seconds
            + self.integration_http_read_timeout_seconds
            + self.integration_job_lease_safety_margin_seconds
            >= self.integration_job_lease_seconds
        ):
            raise ValueError(
                "Integration provider timeout budget must be shorter than the job lease"
            )
        required_connections = (
            (self.db_pool_size + self.db_max_overflow) * self.db_process_count
            + self.db_admin_reserve
        )
        if required_connections > self.db_connection_budget:
            raise ValueError(
                "Database connection budget is smaller than configured process pools"
            )
        if self.environment in {"staging", "production"}:
            placeholders = {
                "dev-only-change-me-before-production",
                "replace-with-at-least-32-random-characters",
            }
            if self.jwt_secret in placeholders or self.jwt_secret.startswith("dev-only"):
                raise ValueError("JWT_SECRET must be replaced in production")
            if not self.cookie_secure:
                raise ValueError("COOKIE_SECURE must be true in production")
            if not self.enforce_https:
                raise ValueError("ENFORCE_HTTPS must be true in production")
            if not self.rate_limit_enabled:
                raise ValueError("RATE_LIMIT_ENABLED must be true in production")
            if not self.audit_enabled:
                raise ValueError("AUDIT_ENABLED must be true in production")
            if not self.otel_enabled:
                raise ValueError("OTEL_ENABLED must be true in production")
            if not self.otel_exporter_otlp_endpoint:
                raise ValueError("OTEL_EXPORTER_OTLP_ENDPOINT must be set in production")
            if len(self.audit_ip_hash_secret) < 32 or self.audit_ip_hash_secret.startswith(
                "dev-only"
            ):
                raise ValueError("AUDIT_IP_HASH_SECRET must be replaced in production")
            if "*" in self.trusted_hosts or not self.trusted_hosts:
                raise ValueError("TRUSTED_HOSTS must be explicit in production")
            if self.forwarded_allow_ips.strip() == "*":
                raise ValueError("FORWARDED_ALLOW_IPS cannot trust every address")
            if not self.cors_origins or any(
                origin == "*" or urlparse(origin).scheme != "https"
                for origin in self.cors_origins
            ):
                raise ValueError("CORS_ORIGINS must contain only explicit HTTPS origins")
            if not self.frontend_url.startswith("https://"):
                raise ValueError("FRONTEND_URL must use HTTPS in production")
            if self.git_sha in {"", "development", "unknown"}:
                raise ValueError("GIT_SHA must identify the production release")
            keys = self.integration_encryption_key_list
            if (
                not keys
                or "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=" in keys
            ):
                raise ValueError("INTEGRATION_ENCRYPTION_KEYS must be set in production")
            if not self.integration_oauth_public_base_url.startswith("https://"):
                raise ValueError(
                    "INTEGRATION_OAUTH_PUBLIC_BASE_URL must use HTTPS in production"
                )
        for key in self.integration_encryption_key_list:
            try:
                decoded = base64.b64decode(key, altchars=b"-_", validate=True)
            except (ValueError, binascii.Error) as exc:
                raise ValueError(
                    "INTEGRATION_ENCRYPTION_KEYS contains an invalid Fernet key"
                ) from exc
            if len(decoded) != 32:
                raise ValueError("INTEGRATION_ENCRYPTION_KEYS contains an invalid Fernet key")
        return self

    def _validate_proxy_networks(self) -> None:
        values = [value.strip() for value in self.forwarded_allow_ips.split(",")]
        if any(not value for value in values):
            raise ValueError("FORWARDED_ALLOW_IPS contains an empty value")
        if "*" in values:
            return
        for value in values:
            try:
                ipaddress.ip_network(value, strict=False)
            except ValueError as exc:
                raise ValueError("FORWARDED_ALLOW_IPS contains an invalid network") from exc

    @property
    def integration_encryption_key_list(self) -> tuple[str, ...]:
        return tuple(
            key.strip() for key in self.integration_encryption_keys.split(",") if key.strip()
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
