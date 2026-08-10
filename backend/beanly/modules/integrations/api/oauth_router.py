from fastapi import APIRouter, HTTPException, status
from fastapi.responses import RedirectResponse

from beanly.modules.identity.api.dependencies import SettingsDep
from beanly.modules.integrations.api.dependencies import (
    IntegrationsWriteDep,
    OAuthServiceDep,
)
from beanly.modules.integrations.api.schemas import OAuthStartResponse
from beanly.modules.integrations.domain.exceptions import IntegrationError

router = APIRouter(prefix="/integrations", tags=["integration-oauth"])


@router.post(
    "/providers/{provider_code}/oauth/start", response_model=OAuthStartResponse
)
async def oauth_start(
    provider_code: str,
    context: IntegrationsWriteDep,
    service: OAuthServiceDep,
) -> OAuthStartResponse:
    try:
        result = await service.start(context, provider_code)
    except IntegrationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return OAuthStartResponse(authorization_url=result.authorization_url)


@router.get("/oauth/{provider_code}/callback")
async def oauth_callback(
    provider_code: str,
    state: str,
    code: str,
    service: OAuthServiceDep,
    settings: SettingsDep,
) -> RedirectResponse:
    try:
        connection_id, _ = await service.consume(provider_code, state, code)
    except IntegrationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "OAuth callback failed") from exc
    return RedirectResponse(
        f"{settings.frontend_url.rstrip('/')}/app/settings/integrations/{connection_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
