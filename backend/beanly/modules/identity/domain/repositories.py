from datetime import datetime
from typing import Protocol
from uuid import UUID

from beanly.modules.identity.domain.entities import AuthSession, User


class IdentityRepository(Protocol):
    async def get_user_by_email(self, email: str) -> User | None: ...

    async def get_user_by_id(self, user_id: UUID) -> User | None: ...

    async def add_user(self, user: User) -> User: ...

    async def add_session(self, session: AuthSession) -> AuthSession: ...

    async def rotate_session(
        self,
        session_id: UUID,
        old_hash: str,
        new_hash: str,
        now: datetime,
    ) -> AuthSession | None: ...

    async def revoke_session(
        self,
        session_id: UUID,
        refresh_hash: str,
        now: datetime,
    ) -> None: ...

    async def get_active_session(
        self,
        session_id: UUID,
        user_id: UUID,
        now: datetime,
    ) -> AuthSession | None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
