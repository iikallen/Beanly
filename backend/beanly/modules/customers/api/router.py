from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status

from beanly.modules.customers.api.dependencies import (
    CustomerServiceDep,
    CustomersReadDep,
    CustomersWriteDep,
    LoyaltyAdjustDep,
    LoyaltyConfigureDep,
    LoyaltyReadDep,
    LoyaltyRedeemDep,
)
from beanly.modules.customers.api.schemas import (
    CustomerAttachRequest,
    CustomerCreate,
    CustomerOrderResponse,
    CustomerPatch,
    CustomerResponse,
    LoyaltyAdjustmentRequest,
    LoyaltyProgramPatch,
    LoyaltyProgramResponse,
    LoyaltyQuoteRequest,
    LoyaltyQuoteResponse,
    LoyaltyRedeemRequest,
    LoyaltyResponse,
    LoyaltyTierResponse,
    LoyaltyTierWrite,
    PromotionAudienceResponse,
    PromotionAudienceWrite,
)
from beanly.modules.customers.domain.exceptions import (
    CustomerError,
    CustomerInvalid,
    CustomerNotFound,
    CustomerPhoneConflict,
    LoyaltyIdempotencyConflict,
    LoyaltyInsufficientBalance,
    LoyaltyInvalid,
    LoyaltyOrderImmutable,
)
from beanly.modules.organizations.domain.exceptions import OrganizationAccessDenied
from beanly.modules.sales.api.dependencies import OrderServiceDep
from beanly.modules.sales.api.schemas import OrderResponse

router = APIRouter(prefix="/customers", tags=["customers"])
loyalty_router = APIRouter(prefix="/loyalty", tags=["loyalty"])
sales_loyalty_router = APIRouter(prefix="/sales", tags=["loyalty"])
promotion_audience_router = APIRouter(prefix="/promotions", tags=["promotions"])


@router.get("", response_model=list[CustomerResponse])
async def list_customers(
    context: CustomersReadDep,
    service: CustomerServiceDep,
    search: str | None = Query(None, max_length=150),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return await _call(service.list(context, search, limit, offset))


@router.post("", response_model=CustomerResponse, status_code=status.HTTP_201_CREATED)
async def create_customer(
    payload: CustomerCreate, context: CustomersWriteDep, service: CustomerServiceDep
):
    return await _call(service.create(context, payload))


@router.get("/{customer_id}", response_model=CustomerResponse)
async def get_customer(customer_id: UUID, context: CustomersReadDep, service: CustomerServiceDep):
    return await _call(service.get(context, customer_id))


@router.patch("/{customer_id}", response_model=CustomerResponse)
async def update_customer(
    customer_id: UUID,
    payload: CustomerPatch,
    context: CustomersWriteDep,
    service: CustomerServiceDep,
):
    return await _call(service.update(context, customer_id, payload))


@router.delete("/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_customer(
    customer_id: UUID,
    context: CustomersWriteDep,
    service: CustomerServiceDep,
):
    await _call(service.soft_delete(context, customer_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{customer_id}/orders", response_model=list[CustomerOrderResponse])
async def customer_orders(
    customer_id: UUID,
    context: CustomersReadDep,
    service: CustomerServiceDep,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return await _call(service.orders(context, customer_id, limit, offset))


@router.get("/{customer_id}/loyalty", response_model=LoyaltyResponse)
async def customer_loyalty(customer_id: UUID, context: LoyaltyReadDep, service: CustomerServiceDep):
    return await _call(service.loyalty(context, customer_id))


@router.post("/{customer_id}/loyalty/adjustments", response_model=LoyaltyResponse)
async def adjust_loyalty(
    customer_id: UUID,
    payload: LoyaltyAdjustmentRequest,
    context: LoyaltyAdjustDep,
    service: CustomerServiceDep,
):
    return await _call(service.adjust(context, customer_id, payload))


@loyalty_router.get("/program", response_model=LoyaltyProgramResponse)
async def get_program(context: LoyaltyReadDep, service: CustomerServiceDep):
    return await _call(service.program(context))


@loyalty_router.patch("/program", response_model=LoyaltyProgramResponse)
async def configure_program(
    payload: LoyaltyProgramPatch,
    context: LoyaltyConfigureDep,
    service: CustomerServiceDep,
):
    return await _call(service.configure_program(context, payload))


@loyalty_router.get("/tiers", response_model=list[LoyaltyTierResponse])
async def list_tiers(context: LoyaltyReadDep, service: CustomerServiceDep):
    return await _call(service.tiers(context))


@loyalty_router.post(
    "/tiers", response_model=LoyaltyTierResponse, status_code=status.HTTP_201_CREATED
)
async def create_tier(
    payload: LoyaltyTierWrite,
    context: LoyaltyConfigureDep,
    service: CustomerServiceDep,
):
    return await _call(service.create_tier(context, payload))


@loyalty_router.patch("/tiers/{tier_id}", response_model=LoyaltyTierResponse)
async def update_tier(
    tier_id: UUID,
    payload: LoyaltyTierWrite,
    context: LoyaltyConfigureDep,
    service: CustomerServiceDep,
):
    return await _call(service.update_tier(context, tier_id, payload))


@sales_loyalty_router.put("/orders/{order_id}/customer", response_model=OrderResponse)
async def attach_customer(
    order_id: UUID,
    payload: CustomerAttachRequest,
    context: CustomersWriteDep,
    service: CustomerServiceDep,
    orders: OrderServiceDep,
):
    await _call(service.attach(context, order_id, payload.customer_id))
    return OrderResponse.from_entity(await orders.get(context, order_id))


@sales_loyalty_router.post("/orders/{order_id}/loyalty/quote", response_model=LoyaltyQuoteResponse)
async def quote_redemption(
    order_id: UUID,
    payload: LoyaltyQuoteRequest,
    context: LoyaltyRedeemDep,
    service: CustomerServiceDep,
):
    return await _call(service.quote(context, order_id, payload.points))


@sales_loyalty_router.post("/orders/{order_id}/loyalty/redeem", response_model=OrderResponse)
async def redeem_points(
    order_id: UUID,
    payload: LoyaltyRedeemRequest,
    context: LoyaltyRedeemDep,
    service: CustomerServiceDep,
    orders: OrderServiceDep,
):
    await _call(service.redeem(context, order_id, payload))
    return OrderResponse.from_entity(await orders.get(context, order_id))


@sales_loyalty_router.delete("/orders/{order_id}/loyalty/redemption", response_model=OrderResponse)
async def release_redemption(
    order_id: UUID,
    context: LoyaltyRedeemDep,
    service: CustomerServiceDep,
    orders: OrderServiceDep,
):
    await _call(service.release(context, order_id))
    return OrderResponse.from_entity(await orders.get(context, order_id))


@promotion_audience_router.get("/{promotion_id}/audience", response_model=PromotionAudienceResponse)
async def get_promotion_audience(
    promotion_id: UUID,
    context: LoyaltyReadDep,
    service: CustomerServiceDep,
):
    return await _call(service.get_audience(context, promotion_id))


@promotion_audience_router.put("/{promotion_id}/audience", response_model=PromotionAudienceResponse)
async def set_promotion_audience(
    promotion_id: UUID,
    payload: PromotionAudienceWrite,
    context: LoyaltyConfigureDep,
    service: CustomerServiceDep,
):
    return await _call(service.set_audience(context, promotion_id, payload))


async def _call(operation):
    try:
        return await operation
    except CustomerNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _detail(exc)) from exc
    except OrganizationAccessDenied as exc:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            {"code": "CUSTOMER_ACCESS_DENIED", "message": str(exc)},
        ) from exc
    except (
        CustomerPhoneConflict,
        LoyaltyIdempotencyConflict,
        LoyaltyInsufficientBalance,
        LoyaltyOrderImmutable,
    ) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, _detail(exc)) from exc
    except LoyaltyInvalid as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, _detail(exc)) from exc
    except CustomerInvalid as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, _detail(exc)) from exc


def _detail(exc: CustomerError) -> dict[str, str]:
    return {"code": exc.code, "message": str(exc)}
