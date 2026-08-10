from typing import Protocol
from uuid import UUID

from beanly.modules.integrations.application.dto import FiscalSaleCommand


class IntegrationSourcePort(Protocol):
    async def fiscal_sale(
        self, organization_id: UUID, payment_id: UUID
    ) -> FiscalSaleCommand: ...
