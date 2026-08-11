from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path, Query, status

from beanly.modules.fiscal.api.dependencies import (
    FiscalLiveServiceDep,
    FiscalReadDep,
    FiscalServiceDep,
    FiscalWriteDep,
    NktServiceDep,
)
from beanly.modules.fiscal.api.schemas import (
    FiscalEnforcementRequest,
    FiscalEnforcementResponse,
    FiscalOperationsResponse,
    FiscalReadinessResponse,
    FiscalReceiptListResponse,
    FiscalReceiptResponse,
    FiscalRouteCreateRequest,
    FiscalRoutePatchRequest,
    FiscalRouteResponse,
    FiscalVariantResponse,
    FiscalVariantUpsertRequest,
    GoLiveReadinessResponse,
    NktProductResponse,
    NktVariantLinkRequest,
    TaxProfileResponse,
    TaxProfileUpsertRequest,
)
from beanly.modules.fiscal.domain.enums import FiscalReceiptStatus
from beanly.modules.fiscal.domain.exceptions import (
    FiscalError,
    FiscalNotReady,
    FiscalReceiptNotFound,
    FiscalReceiptStateConflict,
    FiscalReconciliationUnavailable,
    FiscalRouteAlreadyConfigured,
    FiscalRouteNotFound,
    FiscalVariantNotFound,
    NktInvalidResponse,
    NktProductNotFound,
    NktRateLimited,
    NktUnavailable,
    TaxProfileNotFound,
)

router = APIRouter(prefix="/fiscal", tags=["fiscal"])


@router.get("/nkt/search", response_model=list[NktProductResponse])
async def search_nkt(
    _: FiscalReadDep,
    service: NktServiceDep,
    query: str = Query(min_length=2, max_length=200),
    limit: int = Query(default=20, ge=1, le=50),
) -> list[NktProductResponse]:
    try:
        values = await service.search(query, limit=limit)
    except FiscalError as exc:
        raise _http_error(exc) from exc
    return [_nkt(value) for value in values]


@router.get("/nkt/ntin/{ntin}", response_model=NktProductResponse)
async def nkt_by_ntin(
    ntin: Annotated[str, Path(pattern=r"^[0-9]{13}$")],
    _: FiscalReadDep,
    service: NktServiceDep,
) -> NktProductResponse:
    try:
        return _nkt(await service.by_ntin(ntin))
    except FiscalError as exc:
        raise _http_error(exc) from exc


@router.get("/nkt/gtin/{gtin}", response_model=list[NktProductResponse])
async def nkt_by_gtin(
    gtin: Annotated[str, Path(pattern=r"^[0-9]{13}$")],
    _: FiscalReadDep,
    service: NktServiceDep,
) -> list[NktProductResponse]:
    try:
        return [_nkt(value) for value in await service.by_gtin(gtin)]
    except FiscalError as exc:
        raise _http_error(exc) from exc


@router.put("/variants/{variant_id}/nkt", response_model=FiscalVariantResponse)
async def link_variant_nkt(
    variant_id: UUID,
    payload: NktVariantLinkRequest,
    context: FiscalWriteDep,
    service: NktServiceDep,
) -> FiscalVariantResponse:
    try:
        return FiscalVariantResponse.model_validate(
            await service.link(context, variant_id, payload.ntin)
        )
    except FiscalError as exc:
        raise _http_error(exc) from exc


@router.post("/variants/{variant_id}/nkt/refresh", response_model=FiscalVariantResponse)
async def refresh_variant_nkt(
    variant_id: UUID, context: FiscalWriteDep, service: NktServiceDep
) -> FiscalVariantResponse:
    try:
        return FiscalVariantResponse.model_validate(await service.refresh(context, variant_id))
    except FiscalError as exc:
        raise _http_error(exc) from exc


@router.get("/operations", response_model=FiscalOperationsResponse)
async def fiscal_operations(
    location_id: UUID, context: FiscalReadDep, service: FiscalLiveServiceDep
) -> FiscalOperationsResponse:
    try:
        return FiscalOperationsResponse.model_validate(
            await service.operations(context, location_id)
        )
    except FiscalError as exc:
        raise _http_error(exc) from exc


@router.get("/receipts", response_model=FiscalReceiptListResponse)
async def list_fiscal_receipts(
    context: FiscalReadDep,
    service: FiscalLiveServiceDep,
    location_id: UUID | None = None,
    receipt_status: Annotated[
        FiscalReceiptStatus | None, Query(alias="status")
    ] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> FiscalReceiptListResponse:
    values, total = await service.list_receipts(
        context,
        location_id=location_id,
        status=receipt_status,
        limit=limit,
        offset=offset,
    )
    return FiscalReceiptListResponse(
        items=[FiscalReceiptResponse.model_validate(value) for value in values],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/receipts/{receipt_id}", response_model=FiscalReceiptResponse)
async def get_fiscal_receipt(
    receipt_id: UUID, context: FiscalReadDep, service: FiscalLiveServiceDep
) -> FiscalReceiptResponse:
    try:
        return FiscalReceiptResponse.model_validate(await service.get_receipt(context, receipt_id))
    except FiscalError as exc:
        raise _http_error(exc) from exc


@router.post("/receipts/{receipt_id}/retry", response_model=FiscalReceiptResponse)
async def retry_fiscal_receipt(
    receipt_id: UUID, context: FiscalWriteDep, service: FiscalLiveServiceDep
) -> FiscalReceiptResponse:
    try:
        return FiscalReceiptResponse.model_validate(await service.retry(context, receipt_id))
    except FiscalError as exc:
        raise _http_error(exc) from exc


@router.post("/receipts/{receipt_id}/reconcile", response_model=FiscalReceiptResponse)
async def reconcile_fiscal_receipt(
    receipt_id: UUID, context: FiscalWriteDep, service: FiscalLiveServiceDep
) -> FiscalReceiptResponse:
    try:
        return FiscalReceiptResponse.model_validate(await service.reconcile(context, receipt_id))
    except FiscalError as exc:
        raise _http_error(exc) from exc


@router.get(
    "/locations/{location_id}/enforcement", response_model=FiscalEnforcementResponse
)
async def get_fiscal_enforcement(
    location_id: UUID, context: FiscalReadDep, service: FiscalLiveServiceDep
) -> FiscalEnforcementResponse:
    try:
        value = await service.enforcement(context, location_id)
        return FiscalEnforcementResponse(
            location_id=value.id, mode=value.fiscal_enforcement_mode
        )
    except FiscalError as exc:
        raise _http_error(exc) from exc


@router.put(
    "/locations/{location_id}/enforcement", response_model=FiscalEnforcementResponse
)
async def set_fiscal_enforcement(
    location_id: UUID,
    payload: FiscalEnforcementRequest,
    context: FiscalWriteDep,
    service: FiscalLiveServiceDep,
) -> FiscalEnforcementResponse:
    try:
        value = await service.set_enforcement(context, location_id, payload.mode)
        return FiscalEnforcementResponse(
            location_id=value.id, mode=value.fiscal_enforcement_mode
        )
    except FiscalError as exc:
        raise _http_error(exc) from exc


@router.get(
    "/locations/{location_id}/go-live-readiness",
    response_model=GoLiveReadinessResponse,
)
async def go_live_readiness(
    location_id: UUID, context: FiscalReadDep, service: FiscalLiveServiceDep
) -> GoLiveReadinessResponse:
    try:
        return GoLiveReadinessResponse.model_validate(
            await service.go_live_readiness(context, location_id)
        )
    except FiscalError as exc:
        raise _http_error(exc) from exc


@router.get("/routes", response_model=list[FiscalRouteResponse])
async def list_fiscal_routes(
    context: FiscalReadDep,
    service: FiscalLiveServiceDep,
    location_id: UUID | None = None,
) -> list[FiscalRouteResponse]:
    try:
        return [
            FiscalRouteResponse.model_validate(value)
            for value in await service.routes(context, location_id)
        ]
    except FiscalError as exc:
        raise _http_error(exc) from exc


@router.post(
    "/routes", response_model=FiscalRouteResponse, status_code=status.HTTP_201_CREATED
)
async def create_fiscal_route(
    payload: FiscalRouteCreateRequest,
    context: FiscalWriteDep,
    service: FiscalLiveServiceDep,
) -> FiscalRouteResponse:
    try:
        return FiscalRouteResponse.model_validate(
            await service.create_route(context, **payload.model_dump())
        )
    except FiscalError as exc:
        raise _http_error(exc) from exc


@router.patch("/routes/{route_id}", response_model=FiscalRouteResponse)
async def patch_fiscal_route(
    route_id: UUID,
    payload: FiscalRoutePatchRequest,
    context: FiscalWriteDep,
    service: FiscalLiveServiceDep,
) -> FiscalRouteResponse:
    try:
        return FiscalRouteResponse.model_validate(
            await service.set_route_active(context, route_id, payload.is_active)
        )
    except FiscalError as exc:
        raise _http_error(exc) from exc


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
    if isinstance(exc, (TaxProfileNotFound, FiscalVariantNotFound, NktProductNotFound)):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail)
    if isinstance(exc, NktRateLimited):
        return HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail)
    if isinstance(exc, NktInvalidResponse):
        return HTTPException(status.HTTP_502_BAD_GATEWAY, detail)
    if isinstance(exc, NktUnavailable):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail)
    if isinstance(exc, (FiscalReceiptNotFound, FiscalRouteNotFound)):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail)
    if isinstance(
        exc,
        (
            FiscalNotReady,
            FiscalReceiptStateConflict,
            FiscalReconciliationUnavailable,
            FiscalRouteAlreadyConfigured,
        ),
    ):
        return HTTPException(status.HTTP_409_CONFLICT, detail)
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail)


def _nkt(value) -> NktProductResponse:
    return NktProductResponse(
        external_id=value.external_id,
        ntin=value.ntin,
        gtins=list(value.gtins),
        name_ru=value.name_ru,
        name_kk=value.name_kk,
        category_code=value.category_code,
        unit_code=value.unit_code,
        status=value.status,
        updated_at=value.updated_at,
    )
