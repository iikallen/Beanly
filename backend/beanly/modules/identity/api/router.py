from typing import Annotated

from fastapi import APIRouter, Cookie, HTTPException, Response, status

from beanly.modules.identity.api.dependencies import AuthServiceDep, CurrentUserDep, OriginDep
from beanly.modules.identity.api.schemas import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from beanly.modules.identity.domain.exceptions import (
    DuplicateEmailError,
    InvalidCredentialsError,
    InvalidSessionError,
)

router = APIRouter(prefix="/auth", tags=["auth"])
RefreshCookie = Annotated[str | None, Cookie(alias="beanly_refresh")]


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, service: AuthServiceDep) -> UserResponse:
    try:
        user = await service.register(
            str(payload.email), payload.password, payload.first_name, payload.last_name
        )
    except DuplicateEmailError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        ) from exc
    return UserResponse.model_validate(user)


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    response: Response,
    service: AuthServiceDep,
    _: OriginDep,
) -> TokenResponse:
    try:
        tokens = await service.login(str(payload.email), payload.password)
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    _set_refresh_cookie(response, tokens.refresh_token, service)
    return TokenResponse(access_token=tokens.access_token, expires_in=tokens.expires_in)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    response: Response,
    service: AuthServiceDep,
    _: OriginDep,
    refresh_token: RefreshCookie = None,
) -> TokenResponse:
    if refresh_token is None:
        raise _invalid_session()
    try:
        tokens = await service.refresh(refresh_token)
    except InvalidSessionError as exc:
        raise _invalid_session() from exc
    _set_refresh_cookie(response, tokens.refresh_token, service)
    return TokenResponse(access_token=tokens.access_token, expires_in=tokens.expires_in)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    service: AuthServiceDep,
    _: OriginDep,
    refresh_token: RefreshCookie = None,
) -> None:
    await service.logout(refresh_token)
    response.delete_cookie(
        "beanly_refresh",
        path="/api/v1/auth",
        secure=service.settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )


@router.get("/me", response_model=UserResponse)
async def me(user: CurrentUserDep) -> UserResponse:
    return UserResponse.model_validate(user)


def _set_refresh_cookie(response: Response, token: str, service: AuthServiceDep) -> None:
    response.set_cookie(
        "beanly_refresh",
        token,
        max_age=service.settings.refresh_token_days * 24 * 60 * 60,
        path="/api/v1/auth",
        secure=service.settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )


def _invalid_session() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired session",
        headers={"WWW-Authenticate": "Bearer"},
    )
