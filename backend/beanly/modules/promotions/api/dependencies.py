from typing import Annotated

from fastapi import Depends, HTTPException, status

from beanly.modules.identity.api.dependencies import SessionDep
from beanly.modules.organizations.api.dependencies import TenantContextDep
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.organizations.domain.permissions import Permission
from beanly.modules.promotions.infrastructure.pricing_service import OrderDiscountService
from beanly.modules.promotions.infrastructure.promotion_service import PromotionService


def promotion_service(session: SessionDep) -> PromotionService:
    return PromotionService(session)


PromotionServiceDep = Annotated[PromotionService, Depends(promotion_service)]


def order_discount_service(session: SessionDep) -> OrderDiscountService:
    return OrderDiscountService(session)


OrderDiscountServiceDep = Annotated[OrderDiscountService, Depends(order_discount_service)]


def _permission(permission: Permission):
    async def dependency(context: TenantContextDep) -> TenantContext:
        if permission not in context.permissions:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Permission denied")
        return context

    return dependency


PromotionsReadDep = Annotated[TenantContext, Depends(_permission(Permission.PROMOTIONS_READ))]
PromotionsWriteDep = Annotated[TenantContext, Depends(_permission(Permission.PROMOTIONS_WRITE))]
DiscountApplyDep = Annotated[TenantContext, Depends(_permission(Permission.DISCOUNTS_APPLY))]
DiscountOverrideDep = Annotated[TenantContext, Depends(_permission(Permission.DISCOUNTS_OVERRIDE))]
