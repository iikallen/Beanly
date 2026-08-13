from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from beanly.modules.promotions.infrastructure.pricing_service import reprice_order


class PromotionSalesPricingGateway:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def reprice(self, organization_id: UUID, order_id: UUID) -> None:
        await reprice_order(self.session, organization_id, order_id)
