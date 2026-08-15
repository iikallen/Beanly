from typing import Annotated

from fastapi import Depends, HTTPException, status

from beanly.modules.identity.api.dependencies import SessionDep, SettingsDep
from beanly.modules.online_ordering.infrastructure.service import OnlineOrderingService
from beanly.modules.organizations.api.dependencies import TenantContextDep
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.organizations.domain.permissions import Permission
from beanly.modules.organizations.infrastructure.db.repositories import (
    SqlAlchemyOrganizationRepository,
)


def online_ordering_service(
    session: SessionDep, settings: SettingsDep
) -> OnlineOrderingService:
    return OnlineOrderingService(
        session,
        OrganizationService(SqlAlchemyOrganizationRepository(session)),
        settings,
    )


OnlineOrderingServiceDep = Annotated[OnlineOrderingService, Depends(online_ordering_service)]


def _permission(*required: Permission):
    async def dependency(context: TenantContextDep) -> TenantContext:
        if not context.permissions.intersection(required):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Permission denied")
        return context

    return dependency


OnlineOrdersReadDep = Annotated[
    TenantContext, Depends(_permission(Permission.ONLINE_ORDERS_READ))
]
OnlineOrdersManageDep = Annotated[
    TenantContext, Depends(_permission(Permission.ONLINE_ORDERS_MANAGE))
]
OnlineOrderingManageDep = Annotated[
    TenantContext, Depends(_permission(Permission.ONLINE_ORDERING_MANAGE))
]
