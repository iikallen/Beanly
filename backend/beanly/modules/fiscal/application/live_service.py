from uuid import UUID

from beanly.modules.fiscal.application.live_ports import (
    FiscalLiveRepositoryPort,
    FiscalReconciliationPort,
)
from beanly.modules.fiscal.domain.enums import FiscalEnforcementMode, FiscalReceiptStatus
from beanly.modules.fiscal.domain.exceptions import (
    FiscalNotReady,
    FiscalReceiptStateConflict,
    FiscalReconciliationUnavailable,
)
from beanly.modules.organizations.domain.entities import TenantContext


class FiscalLiveService:
    def __init__(
        self,
        repository: FiscalLiveRepositoryPort,
        reconciler: FiscalReconciliationPort,
        *,
        live_transport_enabled: bool,
        real_provider_codes: frozenset[str],
        nkt_configured: bool,
    ) -> None:
        self.repository = repository
        self.reconciler = reconciler
        self.live_transport_enabled = live_transport_enabled
        self.real_provider_codes = real_provider_codes
        self.nkt_configured = nkt_configured

    async def get_receipt(self, context: TenantContext, receipt_id: UUID):
        return await self.repository.get_receipt(context, receipt_id)

    async def list_receipts(self, context: TenantContext, **filters: object):
        return await self.repository.list_receipts(context, **filters)

    async def operations(self, context: TenantContext, location_id: UUID):
        return await self.repository.operations(context, location_id)

    async def retry(self, context: TenantContext, receipt_id: UUID):
        receipt = await self.repository.get_receipt(context, receipt_id)
        if receipt.status == FiscalReceiptStatus.UNKNOWN.value:
            raise FiscalReceiptStateConflict("UNKNOWN receipt must be reconciled, never retried")
        if receipt.status not in {
            FiscalReceiptStatus.DEAD.value,
            FiscalReceiptStatus.RETRYING.value,
        }:
            raise FiscalReceiptStateConflict("Receipt is not retryable")
        return await self.repository.retry_receipt(context, receipt_id)

    async def reconcile(self, context: TenantContext, receipt_id: UUID):
        receipt = await self.repository.get_receipt(context, receipt_id)
        if receipt.status != FiscalReceiptStatus.UNKNOWN.value:
            raise FiscalReceiptStateConflict("Only UNKNOWN receipts can be reconciled")
        result = await self.reconciler.reconcile(receipt)
        if result is None:
            raise FiscalReconciliationUnavailable(
                "Provider lookup is unavailable; the receipt remains UNKNOWN"
            )
        return await self.repository.finish_reconciliation(context, receipt_id, result)

    async def enforcement(self, context: TenantContext, location_id: UUID):
        return await self.repository.enforcement(context, location_id)

    async def set_enforcement(
        self, context: TenantContext, location_id: UUID, mode: FiscalEnforcementMode
    ):
        if mode is FiscalEnforcementMode.LIVE_REQUIRED:
            readiness = await self.go_live_readiness(context, location_id)
            if not readiness["ready"]:
                raise FiscalNotReady("Location is not ready for live fiscalization")
        return await self.repository.set_enforcement(context, location_id, mode.value)

    async def routes(self, context: TenantContext, location_id: UUID | None):
        return await self.repository.list_routes(context, location_id)

    async def create_route(self, context: TenantContext, **values: object):
        return await self.repository.create_route(context, **values)

    async def set_route_active(self, context: TenantContext, route_id: UUID, active: bool):
        return await self.repository.set_route_active(context, route_id, active)

    async def go_live_readiness(self, context: TenantContext, location_id: UUID):
        return await self.repository.go_live_readiness(
            context,
            location_id,
            live_transport_enabled=self.live_transport_enabled,
            real_provider_codes=self.real_provider_codes,
            nkt_configured=self.nkt_configured,
        )
