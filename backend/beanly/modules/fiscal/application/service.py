from datetime import date
from typing import Any
from uuid import UUID

from beanly.modules.fiscal.application.ports import FiscalOperationsPort
from beanly.modules.organizations.domain.entities import TenantContext


class FiscalService:
    """Application facade; persistence and canonical reads live behind one port."""

    def __init__(self, operations: FiscalOperationsPort) -> None:
        self.operations = operations

    async def get_tax_profile(
        self, organization_id: UUID, *, effective_on: date | None = None
    ) -> Any:
        return await self.operations.get_tax_profile(organization_id, effective_on=effective_on)

    async def set_tax_profile(self, context: TenantContext, **values: Any) -> Any:
        return await self.operations.set_tax_profile(context, **values)

    async def get_variant(self, organization_id: UUID, variant_id: UUID) -> Any:
        return await self.operations.get_variant(organization_id, variant_id)

    async def set_variant(self, context: TenantContext, variant_id: UUID, **values: Any) -> Any:
        return await self.operations.set_variant(context, variant_id, **values)

    async def readiness(self, organization_id: UUID) -> dict[str, object]:
        return await self.operations.readiness(organization_id)

    async def create_sale_snapshot(self, organization_id: UUID, payment_id: UUID) -> Any:
        return await self.operations.create_sale_snapshot(organization_id, payment_id)
