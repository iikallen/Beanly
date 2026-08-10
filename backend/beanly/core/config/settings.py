import base64
import binascii
from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
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
    integration_job_max_attempts: int = Field(default=10, ge=1, le=1000)
    integration_poll_interval_seconds: float = Field(default=1, gt=0, le=60)

    @model_validator(mode="after")
    def reject_development_secret_in_production(self) -> "Settings":
        if self.environment == "production":
            placeholders = {
                "dev-only-change-me-before-production",
                "replace-with-at-least-32-random-characters",
            }
            if self.jwt_secret in placeholders or self.jwt_secret.startswith("dev-only"):
                raise ValueError("JWT_SECRET must be replaced in production")
            if not self.cookie_secure:
                raise ValueError("COOKIE_SECURE must be true in production")
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

    @property
    def integration_encryption_key_list(self) -> tuple[str, ...]:
        return tuple(
            key.strip() for key in self.integration_encryption_keys.split(",") if key.strip()
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
