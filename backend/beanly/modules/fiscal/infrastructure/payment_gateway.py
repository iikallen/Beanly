from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from beanly.modules.fiscal.application.service import FiscalService
from beanly.modules.fiscal.domain.enums import FiscalEnforcementMode, FiscalRouteSourceMode
from beanly.modules.fiscal.infrastructure.db.models import (
    FiscalRouteModel,
    FiscalTaxProfileModel,
    FiscalVariantProfileModel,
)
from beanly.modules.integrations.infrastructure.db.models import (
    IntegrationConnectionModel,
    IntegrationLocationBindingModel,
)
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.organizations.infrastructure.db.models import LocationModel
from beanly.modules.payments.domain.exceptions import FiscalCheckoutUnavailable
from beanly.modules.payments.infrastructure.db.models import TerminalBindingModel
from beanly.modules.sales.infrastructure.db.models import (
    RegisterShiftModel,
    SalesOrderItemModel,
    SalesOrderModel,
)


class FiscalPaymentSnapshotGateway:
    def __init__(self, fiscal: FiscalService) -> None:
        self.fiscal = fiscal

    async def stage_payment_snapshot(self, organization_id: UUID, payment_id: UUID) -> None:
        await self.fiscal.create_sale_snapshot(organization_id, payment_id)


class FiscalCheckoutGateway:
    def __init__(
        self,
        session: AsyncSession,
        *,
        live_transport_enabled: bool,
        real_provider_codes: frozenset[str],
        nkt_configured: bool,
    ) -> None:
        self.session = session
        self.live_transport_enabled = live_transport_enabled
        self.real_provider_codes = real_provider_codes
        self.nkt_configured = nkt_configured

    async def preflight(
        self, context: TenantContext, *, order_id: UUID, location_id: UUID
    ) -> None:
        mode = await self.session.scalar(
            select(LocationModel.fiscal_enforcement_mode).where(
                LocationModel.organization_id == context.organization_id,
                LocationModel.id == location_id,
            )
        )
        if mode != FiscalEnforcementMode.LIVE_REQUIRED.value:
            return
        if not self.live_transport_enabled or not self.nkt_configured:
            raise FiscalCheckoutUnavailable("Live fiscalization is not configured")

        register_id = await self.session.scalar(
            select(RegisterShiftModel.register_id)
            .join(SalesOrderModel, SalesOrderModel.shift_id == RegisterShiftModel.id)
            .where(
                SalesOrderModel.organization_id == context.organization_id,
                SalesOrderModel.location_id == location_id,
                SalesOrderModel.id == order_id,
            )
        )
        route_row = (
            await self.session.execute(
                select(FiscalRouteModel, IntegrationConnectionModel.provider_code)
                .join(
                    IntegrationConnectionModel,
                    IntegrationConnectionModel.id == FiscalRouteModel.provider_connection_id,
                )
                .where(
                    FiscalRouteModel.organization_id == context.organization_id,
                    FiscalRouteModel.location_id == location_id,
                    FiscalRouteModel.register_id == register_id,
                    FiscalRouteModel.is_active.is_(True),
                    IntegrationConnectionModel.status == "ACTIVE",
                )
            )
        ).first()
        if route_row is None or route_row[1] not in self.real_provider_codes:
            raise FiscalCheckoutUnavailable("No active live fiscal route for this register")

        route = route_row[0]
        if route.source_mode == FiscalRouteSourceMode.EXTERNAL_KKM.value:
            binding_id = await self.session.scalar(
                select(IntegrationLocationBindingModel.id).where(
                    IntegrationLocationBindingModel.organization_id == context.organization_id,
                    IntegrationLocationBindingModel.connection_id
                    == route.provider_connection_id,
                    IntegrationLocationBindingModel.location_id == location_id,
                    IntegrationLocationBindingModel.capability == "FISCAL",
                    IntegrationLocationBindingModel.is_active.is_(True),
                    IntegrationLocationBindingModel.external_location_id.is_not(None),
                )
            )
        else:
            binding_id = await self.session.scalar(
                select(TerminalBindingModel.id).where(
                    TerminalBindingModel.organization_id == context.organization_id,
                    TerminalBindingModel.connection_id == route.provider_connection_id,
                    TerminalBindingModel.location_id == location_id,
                    TerminalBindingModel.register_id == register_id,
                    TerminalBindingModel.is_active.is_(True),
                )
            )
        tax_profile_id = await self.session.scalar(
            select(FiscalTaxProfileModel.id).where(
                FiscalTaxProfileModel.organization_id == context.organization_id,
                FiscalTaxProfileModel.effective_to.is_(None),
            )
        )
        total_variants = int(
            await self.session.scalar(
                select(func.count(func.distinct(SalesOrderItemModel.product_variant_id))).where(
                    SalesOrderItemModel.order_id == order_id
                )
            )
            or 0
        )
        mapped_variants = int(
            await self.session.scalar(
                select(func.count(func.distinct(SalesOrderItemModel.product_variant_id)))
                .join(
                    FiscalVariantProfileModel,
                    FiscalVariantProfileModel.product_variant_id
                    == SalesOrderItemModel.product_variant_id,
                )
                .where(
                    SalesOrderItemModel.order_id == order_id,
                    FiscalVariantProfileModel.organization_id == context.organization_id,
                    FiscalVariantProfileModel.nkt_verified_at.is_not(None),
                    FiscalVariantProfileModel.nkt_code.is_not(None),
                )
            )
            or 0
        )
        if (
            binding_id is None
            or tax_profile_id is None
            or total_variants == 0
            or mapped_variants != total_variants
        ):
            raise FiscalCheckoutUnavailable("Fiscal checkout preflight failed")
