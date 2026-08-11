import logging
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status

from beanly.modules.identity.api.dependencies import SessionDep
from beanly.modules.integrations.api.dependencies import (
    ConnectionServiceDep,
    IntegrationsReadDep,
    IntegrationsWriteDep,
    RegistryDep,
)
from beanly.modules.integrations.api.schemas import (
    ConnectionCreateRequest,
    ConnectionPatchRequest,
    ConnectionResponse,
    JobAttemptResponse,
    JobListResponse,
    JobResponse,
    LocationBindingRequest,
    LocationBindingResponse,
    ProviderDescriptorResponse,
)
from beanly.modules.integrations.domain.entities import IntegrationConnection, IntegrationJob
from beanly.modules.integrations.domain.enums import (
    IntegrationCapability,
    IntegrationJobStatus,
)
from beanly.modules.integrations.domain.exceptions import (
    IntegrationError,
    IntegrationNotFound,
)
from beanly.modules.integrations.infrastructure.db.models import IntegrationJobAttemptModel
from beanly.modules.integrations.infrastructure.db.repositories import (
    SqlAlchemyIntegrationRepository,
)
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.organizations.domain.permissions import Permission

router = APIRouter(prefix="/integrations", tags=["integrations"])
logger = logging.getLogger(__name__)


@router.get("/providers", response_model=list[ProviderDescriptorResponse])
async def providers(
    _: IntegrationsReadDep, registry: RegistryDep
) -> list[ProviderDescriptorResponse]:
    return [
        ProviderDescriptorResponse(
            code=value.code,
            name=value.name,
            capabilities=sorted(value.capabilities),
            auth_type=value.auth_type,
            supports_webhooks=value.supports_webhooks,
            supports_health_check=value.supports_health_check,
            location_scoped=value.location_scoped,
        )
        for value in registry.descriptors()
    ]


@router.get("/connections", response_model=list[ConnectionResponse])
async def connections(
    context: IntegrationsReadDep, service: ConnectionServiceDep
) -> list[ConnectionResponse]:
    return [await _connection(service, context, value) for value in await service.list(context)]


@router.post(
    "/connections",
    response_model=ConnectionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_connection(
    payload: ConnectionCreateRequest,
    context: IntegrationsWriteDep,
    service: ConnectionServiceDep,
) -> ConnectionResponse:
    try:
        value = await service.create(
            context,
            payload.provider_code,
            payload.display_name,
            payload.config,
            payload.credentials,
        )
        return await _connection(service, context, value)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/connections/{connection_id}", response_model=ConnectionResponse)
async def get_connection(
    connection_id: UUID,
    context: IntegrationsReadDep,
    service: ConnectionServiceDep,
) -> ConnectionResponse:
    try:
        return await _connection(service, context, await service.get(context, connection_id))
    except Exception as exc:
        raise _http_error(exc) from exc


@router.patch("/connections/{connection_id}", response_model=ConnectionResponse)
async def update_connection(
    connection_id: UUID,
    payload: ConnectionPatchRequest,
    context: IntegrationsWriteDep,
    service: ConnectionServiceDep,
) -> ConnectionResponse:
    try:
        value = await service.update(
            context,
            connection_id,
            display_name=payload.display_name,
            config=payload.config,
            credentials=payload.credentials,
        )
        return await _connection(service, context, value)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/connections/{connection_id}/test", response_model=ConnectionResponse)
async def test_connection(
    connection_id: UUID,
    context: IntegrationsWriteDep,
    service: ConnectionServiceDep,
) -> ConnectionResponse:
    try:
        return await _connection(
            service, context, await service.test(context, connection_id)
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/connections/{connection_id}/disconnect", response_model=ConnectionResponse)
async def disconnect_connection(
    connection_id: UUID,
    context: IntegrationsWriteDep,
    service: ConnectionServiceDep,
) -> ConnectionResponse:
    try:
        value = await service.disconnect(context, connection_id)
        return await _connection(service, context, value)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.put(
    "/connections/{connection_id}/locations/{location_id}",
    response_model=LocationBindingResponse,
)
async def bind_location(
    connection_id: UUID,
    location_id: UUID,
    payload: LocationBindingRequest,
    context: IntegrationsWriteDep,
    service: ConnectionServiceDep,
) -> LocationBindingResponse:
    try:
        value = await service.bind_location(
            context,
            connection_id,
            location_id,
            payload.capability,
            payload.external_location_id,
            payload.settings,
            payload.is_active,
        )
        return LocationBindingResponse.model_validate(value, from_attributes=True)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/connections/{connection_id}/locations/{location_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unbind_location(
    connection_id: UUID,
    location_id: UUID,
    capability: IntegrationCapability,
    context: IntegrationsWriteDep,
    service: ConnectionServiceDep,
) -> Response:
    try:
        await service.unbind_location(context, connection_id, location_id, capability)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/jobs", response_model=JobListResponse)
async def jobs(
    context: IntegrationsWriteDep,
    session: SessionDep,
    connection_id: UUID | None = None,
    job_status: Annotated[
        IntegrationJobStatus | None, Query(alias="status")
    ] = None,
    job_type: Annotated[str | None, Query(max_length=100)] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> JobListResponse:
    repository = SqlAlchemyIntegrationRepository(session)
    values, total = await repository.list_jobs(
        context.organization_id,
        connection_id=connection_id,
        status=job_status,
        job_type=job_type,
        date_from=(datetime.combine(date_from, time.min, UTC) if date_from else None),
        date_to=(
            datetime.combine(date_to + timedelta(days=1), time.min, UTC)
            if date_to
            else None
        ),
        limit=limit,
        offset=offset,
    )
    attempts = await repository.list_attempts([value.id for value in values])
    return JobListResponse(
        items=[_job(value, attempts.get(value.id, [])) for value in values],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/jobs/{job_id}/retry", response_model=JobResponse)
async def retry_job(
    job_id: UUID, context: IntegrationsWriteDep, session: SessionDep
) -> JobResponse:
    repository = SqlAlchemyIntegrationRepository(session)
    try:
        value = await repository.retry_job(context.organization_id, job_id)
        await repository.commit()
    except Exception as exc:
        await repository.rollback()
        raise _http_error(exc) from exc
    attempts = await repository.list_attempts([job_id])
    return _job(value, attempts.get(job_id, []))


async def _connection(
    service: ConnectionServiceDep,
    context: TenantContext,
    value: IntegrationConnection,
) -> ConnectionResponse:
    bindings = await service.repository.list_bindings(context.organization_id, value.id)
    return ConnectionResponse(
        id=value.id,
        provider_code=value.provider_code,
        display_name=value.display_name,
        status=value.status,
        auth_type=value.auth_type,
        config=value.config,
        has_credentials=value.credentials_ciphertext is not None,
        external_account_id=value.external_account_id,
        connected_at=value.connected_at,
        last_health_check_at=value.last_health_check_at,
        last_success_at=value.last_success_at,
        last_error_code=value.last_error_code,
        last_error_message=value.last_error_message,
        created_at=value.created_at,
        updated_at=value.updated_at,
        can_manage=Permission.INTEGRATIONS_WRITE in context.permissions,
        bindings=[
            LocationBindingResponse.model_validate(binding, from_attributes=True)
            for binding in bindings
        ],
    )


def _job(value: IntegrationJob, attempts: list[IntegrationJobAttemptModel]) -> JobResponse:
    data = {
        field: getattr(value, field)
        for field in JobResponse.model_fields
        if field != "attempt_history"
    }
    return JobResponse(
        **data,
        attempt_history=[
            JobAttemptResponse.model_validate(attempt, from_attributes=True)
            for attempt in attempts
        ],
    )


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, IntegrationNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    if isinstance(exc, (IntegrationError, ValueError)):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    logger.warning(
        "Integration operation failed: error_type=%s", type(exc).__name__
    )
    return HTTPException(
        status.HTTP_500_INTERNAL_SERVER_ERROR, "Integration operation failed"
    )
