from uuid import UUID

from beanly.modules.fiscal.application.service import FiscalService


class FiscalPaymentSnapshotGateway:
    def __init__(self, fiscal: FiscalService) -> None:
        self.fiscal = fiscal

    async def stage_payment_snapshot(self, organization_id: UUID, payment_id: UUID) -> None:
        await self.fiscal.create_sale_snapshot(organization_id, payment_id)
