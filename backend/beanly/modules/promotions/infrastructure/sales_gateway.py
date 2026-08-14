from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from beanly.modules.promotions.infrastructure.pricing_service import reprice_order


class PromotionSalesPricingGateway:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def reprice(self, organization_id: UUID, order_id: UUID) -> None:
        await reprice_order(self.session, organization_id, order_id)

    async def ensure_mutable(self, organization_id: UUID, order_id: UUID) -> None:
        from beanly.modules.customers.infrastructure.db.models import LoyaltyRedemptionModel
        from beanly.modules.sales.domain.exceptions import OrderImmutable

        if await self.session.scalar(
            select(LoyaltyRedemptionModel.id).where(
                LoyaltyRedemptionModel.organization_id == organization_id,
                LoyaltyRedemptionModel.order_id == order_id,
                LoyaltyRedemptionModel.status == "RESERVED",
            )
        ):
            raise OrderImmutable("Release loyalty redemption before changing this order")
