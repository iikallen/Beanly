from typing import Annotated

from fastapi import Depends, HTTPException, status

from beanly.modules.identity.api.dependencies import SessionDep
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
from beanly.modules.payments.infrastructure.db.repositories import (
    SqlAlchemyPaymentRepository,
)
from beanly.modules.payments.infrastructure.sales_gateway import SalesSettlementGateway
from beanly.modules.sales.infrastructure.db.repositories import SqlAlchemySalesRepository


def payment_service(session: SessionDep) -> PaymentService:
    organizations = OrganizationService(SqlAlchemyOrganizationRepository(session))
    return PaymentService(
        SqlAlchemyPaymentRepository(session),
        SalesSettlementGateway(SqlAlchemySalesRepository(session), organizations),
    )


PaymentServiceDep = Annotated[PaymentService, Depends(payment_service)]


def _permission(*required: Permission):
    async def dependency(context: TenantContextDep) -> TenantContext:
        if not context.permissions.intersection(required):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Permission denied")
        return context

    return dependency


PaymentCreateDep = Annotated[
    TenantContext, Depends(_permission(Permission.PAYMENTS_CREATE))
]
PaymentReadDep = Annotated[
    TenantContext, Depends(_permission(Permission.PAYMENTS_READ))
]
PaymentAccessDep = Annotated[
    TenantContext,
    Depends(_permission(Permission.PAYMENTS_READ, Permission.PAYMENTS_CREATE)),
]

