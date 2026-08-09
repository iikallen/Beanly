from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class User:
    id: UUID
    email: str
    password_hash: str
    first_name: str
    last_name: str
    is_active: bool
    email_verified: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class AuthSession:
    id: UUID
    user_id: UUID
    refresh_token_hash: str
    expires_at: datetime
    created_at: datetime
    revoked_at: datetime | None
