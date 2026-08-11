from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from beanly.modules.fiscal.api.dependencies import FiscalReadDep, FiscalServiceDep, FiscalWriteDep
from beanly.modules.fiscal.api.schemas import (
    FiscalReadinessResponse,
    FiscalVariantResponse,
    FiscalVariantUpsertRequest,
    TaxProfileResponse,
    TaxProfileUpsertRequest,
)
from beanly.modules.fiscal.domain.exceptions import (
    FiscalError,
    FiscalVariantNotFound,
    TaxProfileNotFound,
)

router = APIRouter(prefix="/fiscal", tags=["fiscal"])


@router.get("/tax-profile", response_model=TaxProfileResponse)
async def get_tax_profile(context: FiscalReadDep, service: FiscalServiceDep) -> TaxProfileResponse:
    try:
        return TaxProfileResponse.model_validate(
            await service.get_tax_profile(context.organization_id)
        )
    except FiscalError as exc:
        raise _http_error(exc) from exc


@router.put("/tax-profile", response_model=TaxProfileResponse)
async def set_tax_profile(
    payload: TaxProfileUpsertRequest, context: FiscalWriteDep, service: FiscalServiceDep
) -> TaxProfileResponse:
    try:
        value = await service.set_tax_profile(context, **payload.model_dump())
        return TaxProfileResponse.model_validate(value)
    except FiscalError as exc:
        raise _http_error(exc) from exc


@router.get("/variants/{variant_id}", response_model=FiscalVariantResponse)
async def get_variant(
    variant_id: UUID, context: FiscalReadDep, service: FiscalServiceDep
) -> FiscalVariantResponse:
    try:
        return FiscalVariantResponse.model_validate(
            await service.get_variant(context.organization_id, variant_id)
        )
    except FiscalError as exc:
        raise _http_error(exc) from exc


@router.put("/variants/{variant_id}", response_model=FiscalVariantResponse)
async def set_variant(
    variant_id: UUID,
    payload: FiscalVariantUpsertRequest,
    context: FiscalWriteDep,
    service: FiscalServiceDep,
) -> FiscalVariantResponse:
    try:
        value = await service.set_variant(context, variant_id, **payload.model_dump())
        return FiscalVariantResponse.model_validate(value)
    except FiscalError as exc:
        raise _http_error(exc) from exc


@router.get("/readiness", response_model=FiscalReadinessResponse)
async def readiness(context: FiscalReadDep, service: FiscalServiceDep) -> FiscalReadinessResponse:
    return FiscalReadinessResponse.model_validate(await service.readiness(context.organization_id))


def _http_error(exc: FiscalError) -> HTTPException:
    detail = {"code": exc.code, "message": str(exc)}
    if isinstance(exc, (TaxProfileNotFound, FiscalVariantNotFound)):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail)
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail)
