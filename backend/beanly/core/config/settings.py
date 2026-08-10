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
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
