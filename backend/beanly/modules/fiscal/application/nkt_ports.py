from datetime import datetime
from typing import Protocol
from uuid import UUID

from beanly.modules.fiscal.application.nkt_dto import NktProduct
from beanly.modules.organizations.domain.entities import TenantContext


class NationalCatalogPort(Protocol):
    async def search(self, query: str, *, limit: int) -> tuple[NktProduct, ...]: ...

    async def find_by_ntin(self, ntin: str) -> NktProduct | None: ...

    async def find_by_gtin(self, gtin: str) -> tuple[NktProduct, ...]: ...


class NationalCatalogLookupPort(Protocol):
    async def lookup(self, tin: str) -> tuple[NktProduct, ...]: ...


class NktCachePort(Protocol):
    async def search(self, query: str, *, limit: int) -> tuple[NktProduct, ...]: ...
    async def by_ntin(self, ntin: str) -> NktProduct | None: ...
    async def by_gtin(self, gtin: str) -> tuple[NktProduct, ...]: ...
    async def upsert(self, products: tuple[NktProduct, ...]) -> None: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...


class FiscalNktLinkPort(Protocol):
    async def get_variant(self, organization_id: UUID, variant_id: UUID): ...

    async def link_variant_nkt(
        self,
        context: TenantContext,
        variant_id: UUID,
        *,
        ntin: str,
        external_product_id: str,
        verified_at: datetime,
    ): ...


class NktAuditPort(Protocol):
    async def record(self, **values: object): ...
