from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from beanly.core.config.settings import Settings, get_settings
from beanly.core.database.session import get_session
from beanly.core.logging.context import set_user_id
from beanly.core.security.tokens import decode_access_token
from beanly.modules.identity.application.services import AuthService
from beanly.modules.identity.domain.entities import User
from beanly.modules.identity.domain.exceptions import AuthenticationRequiredError
from beanly.modules.identity.infrastructure.db.repositories import SqlAlchemyIdentityRepository

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
bearer = HTTPBearer(auto_error=False)


def auth_service(session: SessionDep, settings: SettingsDep) -> AuthService:
    return AuthService(SqlAlchemyIdentityRepository(session), settings)


AuthServiceDep = Annotated[AuthService, Depends(auth_service)]


def require_allowed_origin(request: Request, settings: SettingsDep) -> None:
    origin = request.headers.get("origin")
    if origin is not None and origin not in settings.cors_origins:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Origin not allowed")


OriginDep = Annotated[None, Depends(require_allowed_origin)]


async def current_user(
    request: Request,
    service: AuthServiceDep,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> User:
    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise _unauthorized()
    claims = decode_access_token(credentials.credentials, settings)
    if claims is None:
        raise _unauthorized()
    try:
        user = await service.current_user(claims)
        request.state.actor_user_id = str(user.id)
        set_user_id(user.id)
        return user
    except AuthenticationRequiredError as exc:
        raise _unauthorized() from exc


CurrentUserDep = Annotated[User, Depends(current_user)]


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )
