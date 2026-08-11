from datetime import date
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from beanly.modules.organizations.domain.entities import TenantContext


class FiscalOperationsPort(Protocol):
    async def get_tax_profile(
        self, organization_id: UUID, *, effective_on: date | None = None
    ) -> Any: ...

    async def set_tax_profile(
        self,
        context: TenantContext,
        *,
        country_code: str,
        tax_regime_code: str,
        vat_registered: bool,
        default_vat_rate: Decimal | None,
        effective_from: date,
    ) -> Any: ...

    async def get_variant(self, organization_id: UUID, variant_id: UUID) -> Any: ...
    async def set_variant(self, context: TenantContext, variant_id: UUID, **values: Any) -> Any: ...
    async def readiness(self, organization_id: UUID) -> dict[str, object]: ...
    async def create_sale_snapshot(self, organization_id: UUID, payment_id: UUID) -> Any: ...
