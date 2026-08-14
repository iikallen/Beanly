from typing import Annotated

from fastapi import Depends, HTTPException, status

from beanly.modules.cash_management.infrastructure.service import (
    CashDrawerService,
    IntegrationFiscalShiftCloseGateway,
)
from beanly.modules.identity.api.dependencies import SessionDep, SettingsDep
from beanly.modules.organizations.api.dependencies import TenantContextDep
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.organizations.domain.permissions import Permission
from beanly.modules.organizations.infrastructure.db.repositories import (
    SqlAlchemyOrganizationRepository,
)


def cash_service(session: SessionDep, settings: SettingsDep) -> CashDrawerService:
    return CashDrawerService(
        session,
        OrganizationService(SqlAlchemyOrganizationRepository(session)),
        IntegrationFiscalShiftCloseGateway(session, settings),
    )


CashServiceDep = Annotated[CashDrawerService, Depends(cash_service)]


def _permission(*required: Permission):
    async def dependency(context: TenantContextDep) -> TenantContext:
        if not context.permissions.intersection(required):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Permission denied")
        return context

    return dependency


CashUseDep = Annotated[
    TenantContext, Depends(_permission(Permission.CASH_DRAWER_USE, Permission.CASH_DRAWER_REPORT))
]
CashAdjustDep = Annotated[TenantContext, Depends(_permission(Permission.CASH_DRAWER_ADJUST))]
CashCloseDep = Annotated[TenantContext, Depends(_permission(Permission.CASH_DRAWER_CLOSE))]
CashApproveDep = Annotated[
    TenantContext, Depends(_permission(Permission.CASH_DRAWER_APPROVE_VARIANCE))
]
CashReportDep = Annotated[TenantContext, Depends(_permission(Permission.CASH_DRAWER_REPORT))]
