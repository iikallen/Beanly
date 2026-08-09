import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
from jwt.exceptions import InvalidTokenError

from beanly.core.config.settings import Settings


@dataclass(frozen=True, slots=True)
class AccessClaims:
    user_id: UUID
    session_id: UUID


def create_access_token(user_id: UUID, session_id: UUID, settings: Settings) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(user_id),
            "sid": str(session_id),
            "typ": "access",
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "iat": now,
            "exp": now + timedelta(minutes=settings.access_token_minutes),
            "jti": str(uuid4()),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )


def decode_access_token(token: str, settings: Settings) -> AccessClaims | None:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            options={"require": ["sub", "sid", "typ", "iss", "aud", "iat", "exp", "jti"]},
        )
        if payload["typ"] != "access":
            return None
        return AccessClaims(user_id=UUID(payload["sub"]), session_id=UUID(payload["sid"]))
    except (InvalidTokenError, KeyError, TypeError, ValueError):
        return None


def create_refresh_token(session_id: UUID) -> tuple[str, str]:
    secret = secrets.token_urlsafe(48)
    return f"{session_id}.{secret}", hash_refresh_secret(secret)


def parse_refresh_token(token: str) -> tuple[UUID, str] | None:
    try:
        raw_session_id, secret = token.split(".", 1)
        if len(secret) < 48:
            return None
        return UUID(raw_session_id), hash_refresh_secret(secret)
    except (ValueError, AttributeError):
        return None


def hash_refresh_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def create_invitation_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    return token, hash_invitation_token(token)


def hash_invitation_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
