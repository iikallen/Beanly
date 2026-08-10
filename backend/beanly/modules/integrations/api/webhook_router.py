from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status

from beanly.modules.integrations.api.dependencies import WebhookServiceDep
from beanly.modules.integrations.api.schemas import WebhookAcceptedResponse
from beanly.modules.integrations.domain.exceptions import (
    IntegrationNotFound,
    InvalidWebhookSignature,
    UnknownProvider,
)

router = APIRouter(prefix="/integrations/webhooks", tags=["integration-webhooks"])


@router.post(
    "/{provider_code}/{connection_id}",
    response_model=WebhookAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def webhook(
    provider_code: str,
    connection_id: UUID,
    request: Request,
    service: WebhookServiceDep,
) -> WebhookAcceptedResponse:
    raw_body = await request.body()
    if len(raw_body) > 1_000_000:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Payload too large")
    try:
        inbox_id = await service.receive(
            provider_code,
            connection_id,
            raw_body,
            {key.lower(): value for key, value in request.headers.items()},
        )
    except (InvalidWebhookSignature, UnknownProvider) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid webhook") from exc
    except IntegrationNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Connection not found") from exc
    except Exception as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "Webhook could not be accepted"
        ) from exc
    return WebhookAcceptedResponse(inbox_event_id=inbox_id)
