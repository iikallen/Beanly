from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from beanly.modules.identity.domain.entities import AuthSession, User
from beanly.modules.identity.domain.exceptions import DuplicateEmailError
from beanly.modules.identity.infrastructure.db.models import AuthSessionModel, UserModel


def to_user(model: UserModel) -> User:
    return User(
        id=model.id,
        email=model.email,
        password_hash=model.password_hash,
        first_name=model.first_name,
        last_name=model.last_name,
        is_active=model.is_active,
        email_verified=model.email_verified,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def to_session(model: AuthSessionModel) -> AuthSession:
    return AuthSession(
        id=model.id,
        user_id=model.user_id,
        refresh_token_hash=model.refresh_token_hash,
        expires_at=model.expires_at,
        created_at=model.created_at,
        revoked_at=model.revoked_at,
    )


class SqlAlchemyIdentityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_user_by_email(self, email: str) -> User | None:
        model = await self.session.scalar(select(UserModel).where(UserModel.email == email))
        return to_user(model) if model else None

    async def get_user_by_id(self, user_id: UUID) -> User | None:
        model = await self.session.get(UserModel, user_id)
        return to_user(model) if model else None

    async def add_user(self, user: User) -> User:
        model = UserModel(
            id=user.id,
            email=user.email,
            password_hash=user.password_hash,
            first_name=user.first_name,
            last_name=user.last_name,
            is_active=user.is_active,
            email_verified=user.email_verified,
            created_at=user.created_at,
            updated_at=user.updated_at,
        )
        self.session.add(model)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise DuplicateEmailError from exc
        return to_user(model)

    async def add_session(self, session: AuthSession) -> AuthSession:
        model = AuthSessionModel(
            id=session.id,
            user_id=session.user_id,
            refresh_token_hash=session.refresh_token_hash,
            expires_at=session.expires_at,
            created_at=session.created_at,
            revoked_at=session.revoked_at,
        )
        self.session.add(model)
        await self.session.flush()
        return to_session(model)

    async def rotate_session(
        self,
        session_id: UUID,
        old_hash: str,
        new_hash: str,
        now: datetime,
    ) -> AuthSession | None:
        statement = (
            update(AuthSessionModel)
            .where(
                AuthSessionModel.id == session_id,
                AuthSessionModel.refresh_token_hash == old_hash,
                AuthSessionModel.revoked_at.is_(None),
                AuthSessionModel.expires_at > now,
            )
            .values(refresh_token_hash=new_hash)
            .returning(AuthSessionModel)
        )
        model = await self.session.scalar(statement)
        return to_session(model) if model else None

    async def revoke_session(
        self,
        session_id: UUID,
        refresh_hash: str,
        now: datetime,
    ) -> None:
        await self.session.execute(
            update(AuthSessionModel)
            .where(
                AuthSessionModel.id == session_id,
                AuthSessionModel.refresh_token_hash == refresh_hash,
                AuthSessionModel.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )

    async def get_active_session(
        self,
        session_id: UUID,
        user_id: UUID,
        now: datetime,
    ) -> AuthSession | None:
        model = await self.session.scalar(
            select(AuthSessionModel).where(
                AuthSessionModel.id == session_id,
                AuthSessionModel.user_id == user_id,
                AuthSessionModel.revoked_at.is_(None),
                AuthSessionModel.expires_at > now,
            )
        )
        return to_session(model) if model else None

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()
