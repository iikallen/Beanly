from typing import Annotated

from fastapi import Depends, HTTPException, status

from beanly.modules.identity.api.dependencies import SessionDep
from beanly.modules.kitchen.infrastructure.service import KitchenService
from beanly.modules.organizations.api.dependencies import TenantContextDep
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.organizations.domain.permissions import Permission
from beanly.modules.organizations.infrastructure.db.repositories import (
    SqlAlchemyOrganizationRepository,
)


def kitchen_service(session: SessionDep) -> KitchenService:
    return KitchenService(
        session,
        OrganizationService(SqlAlchemyOrganizationRepository(session)),
    )


KitchenServiceDep = Annotated[KitchenService, Depends(kitchen_service)]


def _permission(permission: Permission):
    async def dependency(context: TenantContextDep) -> TenantContext:
        if permission not in context.permissions:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Permission denied")
        return context

    return dependency


KitchenReadDep = Annotated[TenantContext, Depends(_permission(Permission.KITCHEN_READ))]
KitchenWorkDep = Annotated[TenantContext, Depends(_permission(Permission.KITCHEN_WORK))]
KitchenExpoDep = Annotated[TenantContext, Depends(_permission(Permission.KITCHEN_EXPO))]
KitchenManageDep = Annotated[TenantContext, Depends(_permission(Permission.KITCHEN_MANAGE))]
KitchenReportDep = Annotated[TenantContext, Depends(_permission(Permission.KITCHEN_REPORT))]
