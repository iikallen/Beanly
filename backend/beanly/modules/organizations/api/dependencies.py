from collections.abc import Callable, Coroutine
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status

from beanly.core.security.audit import SecurityAuditRecorder
from beanly.modules.employees.application.services.employee_service import EmployeeService
from beanly.modules.employees.infrastructure.db.repositories import (
    SqlAlchemyEmployeeRepository,
)
from beanly.modules.identity.api.dependencies import CurrentUserDep, SessionDep, SettingsDep
from beanly.modules.organizations.application.services.invitation_service import (
    InvitationService,
)
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.organizations.domain.exceptions import OrganizationAccessDenied
from beanly.modules.organizations.domain.permissions import Permission
from beanly.modules.organizations.infrastructure.db.invitation_repository import (
    SqlAlchemyInvitationRepository,
)
from beanly.modules.organizations.infrastructure.db.repositories import (
    SqlAlchemyOrganizationRepository,
)
from beanly.modules.organizations.infrastructure.email import ConsoleEmailSender


def organization_service(session: SessionDep) -> OrganizationService:
    return OrganizationService(SqlAlchemyOrganizationRepository(session))


OrganizationServiceDep = Annotated[OrganizationService, Depends(organization_service)]


def employee_service(session: SessionDep) -> EmployeeService:
    return EmployeeService(SqlAlchemyEmployeeRepository(session))


EmployeeServiceDep = Annotated[EmployeeService, Depends(employee_service)]


def invitation_service(session: SessionDep, settings: SettingsDep) -> InvitationService:
    return InvitationService(
        invitations=SqlAlchemyInvitationRepository(session),
        organizations=SqlAlchemyOrganizationRepository(session),
        employees=SqlAlchemyEmployeeRepository(session),
        email_sender=ConsoleEmailSender(),
        settings=settings,
        audit=SecurityAuditRecorder(session) if settings.audit_enabled else None,
    )


InvitationServiceDep = Annotated[InvitationService, Depends(invitation_service)]


async def get_tenant_context(
    user: CurrentUserDep,
    service: OrganizationServiceDep,
    organization_id: Annotated[UUID, Header(alias="X-Organization-ID")],
) -> TenantContext:
    try:
        return await service.tenant_context(user.id, organization_id)
    except OrganizationAccessDenied as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization access denied",
        ) from exc


TenantContextDep = Annotated[TenantContext, Depends(get_tenant_context)]


async def ensure_location_scope(
    context: TenantContext,
    location_ids: tuple[UUID, ...],
    service: OrganizationService,
) -> None:
    try:
        for location_id in dict.fromkeys(location_ids):
            await service.ensure_location_access(context, location_id)
    except OrganizationAccessDenied as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid locations") from exc


def require_permission(
    permission: Permission,
) -> Callable[..., Coroutine[Any, Any, TenantContext]]:
    async def dependency(context: TenantContextDep) -> TenantContext:
        if permission not in context.permissions:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Permission denied")
        return context

    return dependency


def require_location_permission(
    permission: Permission,
) -> Callable[..., Coroutine[Any, Any, TenantContext]]:
    async def dependency(
        location_id: UUID,
        context: Annotated[TenantContext, Depends(require_permission(permission))],
        service: OrganizationServiceDep,
    ) -> TenantContext:
        try:
            await service.ensure_location_access(context, location_id)
        except OrganizationAccessDenied as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Location not found") from exc
        return context

    return dependency
