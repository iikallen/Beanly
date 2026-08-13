from datetime import date
from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from beanly.modules.promotions.api.dependencies import (
    PromotionServiceDep,
    PromotionsReadDep,
    PromotionsWriteDep,
)
from beanly.modules.promotions.api.schemas import (
    CodeCreate,
    PromotionPerformanceResponse,
    PromotionPreviewRequest,
    PromotionPreviewResponse,
    PromotionResponse,
    PromotionWrite,
)
from beanly.modules.promotions.domain.enums import PromotionStatus
from beanly.modules.promotions.domain.exceptions import PromotionConflict, PromotionNotFound

router = APIRouter(prefix="/promotions", tags=["promotions"])


@router.get("", response_model=list[PromotionResponse])
async def list_promotions(context: PromotionsReadDep, service: PromotionServiceDep):
    return [PromotionResponse.from_entity(value) for value in await service.list(context)]


@router.get("/performance", response_model=list[PromotionPerformanceResponse])
async def promotion_performance(
    date_from: date,
    date_to: date,
    context: PromotionsReadDep,
    service: PromotionServiceDep,
    location_id: UUID | None = None,
):
    if date_to < date_from:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "date_to precedes date_from")
    try:
        rows = await service.performance(context, date_from, date_to, location_id)
    except PromotionNotFound as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, {"code": exc.code, "message": str(exc)}
        ) from exc
    return [
        PromotionPerformanceResponse(
            promotion_id=row[0],
            promotion_name=row[1],
            orders_count=int(row[2] or 0),
            applications_count=int(row[3] or 0),
            items_count=int(row[4] or 0),
            gross_eligible_amount=str(row[5] or 0),
            discount_amount=str(row[6] or 0),
            net_revenue_amount=str(row[7] or 0),
            refund_amount=str(row[8] or 0),
        )
        for row in rows
    ]


@router.post("", response_model=PromotionResponse, status_code=status.HTTP_201_CREATED)
async def create_promotion(
    payload: PromotionWrite, context: PromotionsWriteDep, service: PromotionServiceDep
):
    return await _call(service.create(context, payload))


@router.get("/{promotion_id}", response_model=PromotionResponse)
async def get_promotion(
    promotion_id: UUID, context: PromotionsReadDep, service: PromotionServiceDep
):
    return await _call(service.get(context, promotion_id))


@router.patch("/{promotion_id}", response_model=PromotionResponse)
async def update_promotion(
    promotion_id: UUID,
    payload: PromotionWrite,
    context: PromotionsWriteDep,
    service: PromotionServiceDep,
):
    return await _call(service.update(context, promotion_id, payload))


@router.post("/{promotion_id}/activate", response_model=PromotionResponse)
async def activate_promotion(
    promotion_id: UUID, context: PromotionsWriteDep, service: PromotionServiceDep
):
    return await _call(service.set_status(context, promotion_id, PromotionStatus.ACTIVE))


@router.post("/{promotion_id}/archive", response_model=PromotionResponse)
async def archive_promotion(
    promotion_id: UUID, context: PromotionsWriteDep, service: PromotionServiceDep
):
    return await _call(service.set_status(context, promotion_id, PromotionStatus.ARCHIVED))


@router.post("/{promotion_id}/preview", response_model=PromotionPreviewResponse)
async def preview_promotion(
    promotion_id: UUID,
    payload: PromotionPreviewRequest,
    context: PromotionsReadDep,
    service: PromotionServiceDep,
):
    try:
        result = await service.preview(context, promotion_id, payload)
    except PromotionNotFound as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, {"code": exc.code, "message": str(exc)}
        ) from exc
    except PromotionConflict as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, {"code": exc.code, "message": str(exc)}
        ) from exc
    return PromotionPreviewResponse(
        subtotal_minor=str(result.subtotal_minor),
        discount_total_minor=str(result.discount_total_minor),
        total_minor=str(result.total_minor),
        item_discount_minor={key: str(value) for key, value in result.item_discount_minor.items()},
    )


@router.post(
    "/{promotion_id}/codes", response_model=PromotionResponse, status_code=status.HTTP_201_CREATED
)
async def add_code(
    promotion_id: UUID,
    payload: CodeCreate,
    context: PromotionsWriteDep,
    service: PromotionServiceDep,
):
    return await _call(service.add_code(context, promotion_id, payload))


@router.delete("/{promotion_id}/codes/{code_id}", response_model=PromotionResponse)
async def delete_code(
    promotion_id: UUID, code_id: UUID, context: PromotionsWriteDep, service: PromotionServiceDep
):
    return await _call(service.delete_code(context, promotion_id, code_id))


async def _call(operation):
    try:
        value = await operation
        return PromotionResponse.from_entity(value)
    except PromotionNotFound as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, {"code": exc.code, "message": str(exc)}
        ) from exc
    except PromotionConflict as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, {"code": exc.code, "message": str(exc)}
        ) from exc
