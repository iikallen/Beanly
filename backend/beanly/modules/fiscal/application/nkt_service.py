from datetime import UTC, datetime
from uuid import UUID

from beanly.core.observability import metrics
from beanly.modules.fiscal.application.nkt_dto import NktProduct
from beanly.modules.fiscal.application.nkt_ports import (
    FiscalNktLinkPort,
    NationalCatalogLookupPort,
    NktAuditPort,
    NktCachePort,
)
from beanly.modules.fiscal.domain.exceptions import NktInvalidResponse, NktProductNotFound
from beanly.modules.organizations.domain.entities import TenantContext


class NktService:
    def __init__(
        self,
        cache: NktCachePort,
        lookup: NationalCatalogLookupPort,
        fiscal: FiscalNktLinkPort,
        audit: NktAuditPort | None = None,
    ) -> None:
        self.cache = cache
        self.lookup = lookup
        self.fiscal = fiscal
        self.audit = audit

    async def search(self, query: str, *, limit: int) -> tuple[NktProduct, ...]:
        normalized = query.strip()
        if len(normalized) < 2:
            raise NktInvalidResponse("NKT search requires at least 2 characters")
        values = await self.cache.search(normalized, limit=limit)
        metrics.nkt_requests.add(1, {"operation": "cache_search"})
        if values:
            metrics.nkt_cache_hits.add(1, {"operation": "search"})
        return values

    async def by_ntin(self, ntin: str, *, refresh: bool = False) -> NktProduct:
        if not refresh:
            cached = await self.cache.by_ntin(ntin)
            if cached is not None:
                metrics.nkt_cache_hits.add(1, {"operation": "ntin"})
                return cached
        values = await self._lookup(ntin)
        exact = tuple(value for value in values if value.ntin == ntin)
        if len(exact) > 1:
            raise NktInvalidResponse("NKT returned multiple products for one NTIN")
        if not exact:
            raise NktProductNotFound("NKT product not found")
        return exact[0]

    async def by_gtin(self, gtin: str) -> tuple[NktProduct, ...]:
        cached = await self.cache.by_gtin(gtin)
        if cached:
            metrics.nkt_cache_hits.add(1, {"operation": "gtin"})
            return cached
        return tuple(value for value in await self._lookup(gtin) if gtin in value.gtins)

    async def link(self, context: TenantContext, variant_id: UUID, ntin: str):
        product = await self.by_ntin(ntin)
        try:
            value = await self.fiscal.link_variant_nkt(
                context,
                variant_id,
                ntin=product.ntin,
                external_product_id=product.external_id,
                verified_at=datetime.now(UTC),
            )
            if self.audit:
                await self.audit.record(
                    action="NKT_VARIANT_LINKED",
                    resource_type="fiscal_variant_profile",
                    organization_id=context.organization_id,
                    actor_user_id=context.user_id,
                    resource_id=value.id,
                    metadata={"variant_id": str(variant_id), "ntin": product.ntin},
                )
            await self.cache.commit()
        except Exception:
            await self.cache.rollback()
            raise
        return value

    async def refresh(self, context: TenantContext, variant_id: UUID):
        current = await self.fiscal.get_variant(context.organization_id, variant_id)
        if current.nkt_code_type != "NTIN" or not current.nkt_code:
            raise NktProductNotFound("Variant is not linked to an NTIN")
        product = await self.by_ntin(current.nkt_code, refresh=True)
        return await self.link(context, variant_id, product.ntin)

    async def _lookup(self, tin: str) -> tuple[NktProduct, ...]:
        metrics.nkt_requests.add(1, {"operation": "lookup"})
        try:
            values = await self.lookup.lookup(tin)
        except Exception as exc:
            if getattr(exc, "code", None) == "NKT_RATE_LIMITED":
                metrics.nkt_rate_limit.add(1)
            raise
        await self.cache.upsert(values)
        await self.cache.commit()
        return values
