from typing import Protocol
from uuid import UUID

from beanly.modules.integrations.application.dto import FiscalRefundCommand, FiscalSaleCommand


class IntegrationSourcePort(Protocol):
    async def fiscal_sale(self, organization_id: UUID, payment_id: UUID) -> FiscalSaleCommand: ...

    async def fiscal_refund(
        self, organization_id: UUID, refund_id: UUID, connection_id: UUID
    ) -> FiscalRefundCommand: ...
