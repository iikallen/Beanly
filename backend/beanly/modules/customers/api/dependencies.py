from typing import Annotated

from fastapi import Depends, HTTPException, status

from beanly.modules.customers.infrastructure.service import CustomerService
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


def customer_service(session: SessionDep) -> CustomerService:
    return CustomerService(session, OrganizationService(SqlAlchemyOrganizationRepository(session)))


CustomerServiceDep = Annotated[CustomerService, Depends(customer_service)]


def permission(required: Permission):
    async def dependency(context: TenantContextDep) -> TenantContext:
        if required not in context.permissions:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Permission denied")
        return context

    return dependency


CustomersReadDep = Annotated[TenantContext, Depends(permission(Permission.CUSTOMERS_READ))]
CustomersWriteDep = Annotated[TenantContext, Depends(permission(Permission.CUSTOMERS_WRITE))]
LoyaltyReadDep = Annotated[TenantContext, Depends(permission(Permission.LOYALTY_READ))]
LoyaltyAdjustDep = Annotated[TenantContext, Depends(permission(Permission.LOYALTY_ADJUST))]
LoyaltyConfigureDep = Annotated[TenantContext, Depends(permission(Permission.LOYALTY_CONFIGURE))]
LoyaltyRedeemDep = Annotated[TenantContext, Depends(permission(Permission.LOYALTY_REDEEM))]
