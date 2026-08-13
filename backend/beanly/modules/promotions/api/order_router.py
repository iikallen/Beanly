from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from beanly.modules.promotions.api.dependencies import (
    DiscountApplyDep,
    DiscountOverrideDep,
    OrderDiscountServiceDep,
)
from beanly.modules.promotions.api.schemas import (
    CodeDiscountRequest,
    CustomDiscountRequest,
    ManualDiscountRequest,
)
from beanly.modules.promotions.domain.exceptions import PromotionConflict, PromotionNotFound
from beanly.modules.sales.api.schemas import OrderResponse
from beanly.modules.sales.infrastructure.db.repositories import SqlAlchemySalesRepository

router = APIRouter(prefix="/sales/orders", tags=["discounts"])


@router.post("/{order_id}/discounts/manual", response_model=OrderResponse)
async def manual(
    order_id: UUID,
    payload: ManualDiscountRequest,
    context: DiscountApplyDep,
    service: OrderDiscountServiceDep,
):
    return await _run(
        service,
        context,
        order_id,
        service.manual(
            context,
            order_id,
            payload.client_discount_id,
            payload.promotion_id,
        ),
    )


@router.post("/{order_id}/discounts/code", response_model=OrderResponse)
async def code(
    order_id: UUID,
    payload: CodeDiscountRequest,
    context: DiscountApplyDep,
    service: OrderDiscountServiceDep,
):
    return await _run(
        service,
        context,
        order_id,
        service.code(
            context,
            order_id,
            payload.client_discount_id,
            payload.code,
        ),
    )


@router.post("/{order_id}/discounts/custom", response_model=OrderResponse)
async def custom(
    order_id: UUID,
    payload: CustomDiscountRequest,
    context: DiscountOverrideDep,
    service: OrderDiscountServiceDep,
):
    return await _run(
        service,
        context,
        order_id,
        service.custom(
            context,
            order_id,
            payload.client_discount_id,
            payload.type,
            payload.percent,
            payload.amount_minor,
            payload.reason,
        ),
    )


@router.delete("/{order_id}/discounts/{discount_id}", response_model=OrderResponse)
async def remove(
    order_id: UUID, discount_id: UUID, context: DiscountApplyDep, service: OrderDiscountServiceDep
):
    return await _run(
        service, context, order_id, service.remove(context, order_id, discount_id)
    )


async def _run(service, context, order_id, operation):
    try:
        await operation
        value = await SqlAlchemySalesRepository(service.session).get_order(
            context.organization_id, order_id
        )
        if value is None:
            raise PromotionNotFound("Order not found")
        return OrderResponse.from_entity(value)
    except PromotionNotFound as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, {"code": exc.code, "message": str(exc)}
        ) from exc
    except PromotionConflict as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, {"code": exc.code, "message": str(exc)}
        ) from exc
