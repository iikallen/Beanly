import pytest
from pydantic import ValidationError

from beanly.core.config.settings import Settings


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
