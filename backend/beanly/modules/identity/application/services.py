from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from beanly.core.config.settings import Settings
from beanly.core.security.passwords import dummy_password_hash, hash_password, verify_password
from beanly.core.security.tokens import (
    AccessClaims,
    create_access_token,
    create_refresh_token,
    parse_refresh_token,
)
from beanly.modules.identity.domain.entities import AuthSession, User
from beanly.modules.identity.domain.exceptions import (
    AuthenticationRequiredError,
    DuplicateEmailError,
    InvalidCredentialsError,
    InvalidSessionError,
)
from beanly.modules.identity.domain.repositories import IdentityRepository


@dataclass(frozen=True, slots=True)
class AuthTokens:
    access_token: str
    refresh_token: str
    expires_in: int


class AuthService:
    def __init__(self, repository: IdentityRepository, settings: Settings) -> None:
        self.repository = repository
        self.settings = settings

    async def register(
        self,
        email: str,
        password: str,
        first_name: str,
        last_name: str,
    ) -> User:
        normalized_email = email.strip().casefold()
        if await self.repository.get_user_by_email(normalized_email):
            raise DuplicateEmailError

        now = datetime.now(UTC)
        user = User(
            id=uuid4(),
            email=normalized_email,
            password_hash=hash_password(password),
            first_name=first_name.strip(),
            last_name=last_name.strip(),
            is_active=True,
            email_verified=False,
            created_at=now,
            updated_at=now,
        )
        created = await self.repository.add_user(user)
        await self.repository.commit()
        return created

    async def login(self, email: str, password: str) -> AuthTokens:
        user = await self.repository.get_user_by_email(email.strip().casefold())
        if user is None:
            verify_password(password, dummy_password_hash())
            raise InvalidCredentialsError
        password_valid = verify_password(password, user.password_hash)
        if not password_valid or not user.is_active:
            raise InvalidCredentialsError

        now = datetime.now(UTC)
        session_id = uuid4()
        refresh_token, refresh_hash = create_refresh_token(session_id)
        await self.repository.add_session(
            AuthSession(
                id=session_id,
                user_id=user.id,
                refresh_token_hash=refresh_hash,
                expires_at=now + timedelta(days=self.settings.refresh_token_days),
                created_at=now,
                revoked_at=None,
            )
        )
        await self.repository.commit()
        return self._tokens(user.id, session_id, refresh_token)

    async def refresh(self, refresh_token: str) -> AuthTokens:
        parsed = parse_refresh_token(refresh_token)
        if parsed is None:
            raise InvalidSessionError
        session_id, old_hash = parsed
        new_refresh_token, new_hash = create_refresh_token(session_id)
        now = datetime.now(UTC)
        session = await self.repository.rotate_session(session_id, old_hash, new_hash, now)
        if session is None:
            raise InvalidSessionError
        user = await self.repository.get_user_by_id(session.user_id)
        if user is None or not user.is_active:
            await self.repository.rollback()
            raise InvalidSessionError
        await self.repository.commit()
        return self._tokens(user.id, session.id, new_refresh_token)

    async def logout(self, refresh_token: str | None) -> None:
        if not refresh_token or (parsed := parse_refresh_token(refresh_token)) is None:
            return
        session_id, refresh_hash = parsed
        await self.repository.revoke_session(session_id, refresh_hash, datetime.now(UTC))
        await self.repository.commit()

    async def current_user(self, claims: AccessClaims) -> User:
        now = datetime.now(UTC)
        session = await self.repository.get_active_session(claims.session_id, claims.user_id, now)
        if session is None:
            raise AuthenticationRequiredError
        user = await self.repository.get_user_by_id(claims.user_id)
        if user is None or not user.is_active:
            raise AuthenticationRequiredError
        return user

    def _tokens(self, user_id: UUID, session_id: UUID, refresh_token: str) -> AuthTokens:
        return AuthTokens(
            access_token=create_access_token(user_id, session_id, self.settings),
            refresh_token=refresh_token,
            expires_in=self.settings.access_token_minutes * 60,
        )
