from typing import Annotated

from fastapi import Depends, HTTPException, status

from beanly.core.config.settings import get_settings
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
from beanly.modules.reservations.infrastructure.service import ReservationService
from beanly.modules.sales.api.dependencies import order_service


def reservation_service(session: SessionDep) -> ReservationService:
    return ReservationService(
        session,
        OrganizationService(SqlAlchemyOrganizationRepository(session)),
        get_settings(),
        order_service(session),
    )


ReservationServiceDep = Annotated[ReservationService, Depends(reservation_service)]


def _permission(*required: Permission):
    async def dependency(context: TenantContextDep) -> TenantContext:
        if not context.permissions.intersection(required):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Permission denied")
        return context

    return dependency


FohReadDep = Annotated[TenantContext, Depends(_permission(Permission.FOH_READ))]
FohManageDep = Annotated[TenantContext, Depends(_permission(Permission.FOH_MANAGE))]
FohConfigureDep = Annotated[TenantContext, Depends(_permission(Permission.FOH_CONFIGURE))]
