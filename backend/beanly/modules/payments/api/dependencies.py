from typing import Annotated

from fastapi import Depends, HTTPException, status

from beanly.core.events.outbox.repositories import OutboxRepository
from beanly.core.events.outbox.writer import OutboxEventSink
from beanly.modules.fiscal.application.service import FiscalService
from beanly.modules.fiscal.infrastructure.operations import SqlAlchemyFiscalOperations
from beanly.modules.fiscal.infrastructure.payment_gateway import (
    FiscalCheckoutGateway,
    FiscalPaymentSnapshotGateway,
)
from beanly.modules.identity.api.dependencies import SessionDep, SettingsDep
from beanly.modules.inventory.application.services import InventoryService
from beanly.modules.inventory.infrastructure.db.repositories import (
    SqlAlchemyInventoryRepository,
)
from beanly.modules.organizations.api.dependencies import TenantContextDep
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.organizations.domain.permissions import Permission
from beanly.modules.organizations.infrastructure.db.repositories import (
    SqlAlchemyOrganizationRepository,
)
from beanly.modules.payments.application.payment_service import PaymentService
from beanly.modules.payments.application.terminal_service import TerminalPaymentService
from beanly.modules.payments.infrastructure.db.repositories import (
    SqlAlchemyPaymentRepository,
)
from beanly.modules.payments.infrastructure.inventory_gateway import (
    InventorySaleGateway,
    SalesOrderReferenceValidator,
)
from beanly.modules.payments.infrastructure.sales_gateway import SalesSettlementGateway
from beanly.modules.sales.infrastructure.db.repositories import SqlAlchemySalesRepository


def fiscal_checkout_gateway(session: SessionDep, settings: SettingsDep) -> FiscalCheckoutGateway:
    return FiscalCheckoutGateway(
        session,
        live_transport_enabled=settings.live_kz_fiscalization,
        real_provider_codes=frozenset({"webkassa"}),
        nkt_configured=settings.nkt_api_key is not None,
    )


def payment_service(session: SessionDep, settings: SettingsDep) -> PaymentService:
    organizations = OrganizationService(SqlAlchemyOrganizationRepository(session))
    sales_repository = SqlAlchemySalesRepository(session)
    inventory = InventoryService(
        SqlAlchemyInventoryRepository(session),
        organizations,
        reference_validator=SalesOrderReferenceValidator(sales_repository),
    )
    return PaymentService(
        SqlAlchemyPaymentRepository(session),
        SalesSettlementGateway(sales_repository, organizations),
        InventorySaleGateway(inventory, session),
        OutboxEventSink(OutboxRepository(session)),
        FiscalPaymentSnapshotGateway(FiscalService(SqlAlchemyFiscalOperations(session))),
        fiscal_checkout_gateway(session, settings),
    )


PaymentServiceDep = Annotated[PaymentService, Depends(payment_service)]


def terminal_payment_service(session: SessionDep) -> TerminalPaymentService:
    organizations = OrganizationService(SqlAlchemyOrganizationRepository(session))
    return TerminalPaymentService(
        SqlAlchemyPaymentRepository(session),
        SalesSettlementGateway(SqlAlchemySalesRepository(session), organizations),
    )


TerminalPaymentServiceDep = Annotated[TerminalPaymentService, Depends(terminal_payment_service)]


def _permission(*required: Permission):
    async def dependency(context: TenantContextDep) -> TenantContext:
        if not context.permissions.intersection(required):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Permission denied")
        return context

    return dependency


PaymentCreateDep = Annotated[TenantContext, Depends(_permission(Permission.PAYMENTS_CREATE))]
PaymentReadDep = Annotated[TenantContext, Depends(_permission(Permission.PAYMENTS_READ))]
PaymentAccessDep = Annotated[
    TenantContext,
    Depends(_permission(Permission.PAYMENTS_READ, Permission.PAYMENTS_CREATE)),
]
TerminalManageDep = Annotated[
    TenantContext, Depends(_permission(Permission.PAYMENTS_TERMINAL_MANAGE))
]
