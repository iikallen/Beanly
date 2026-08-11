from typing import Annotated

from fastapi import Depends, HTTPException, status

from beanly.core.security.audit import SecurityAuditRecorder
from beanly.modules.fiscal.application.service import FiscalService
from beanly.modules.fiscal.infrastructure.operations import SqlAlchemyFiscalOperations
from beanly.modules.identity.api.dependencies import SessionDep, SettingsDep
from beanly.modules.organizations.api.dependencies import TenantContextDep
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.organizations.domain.permissions import Permission


def fiscal_service(session: SessionDep, settings: SettingsDep) -> FiscalService:
    return FiscalService(
        SqlAlchemyFiscalOperations(
            session, SecurityAuditRecorder(session) if settings.audit_enabled else None
        )
    )


FiscalServiceDep = Annotated[FiscalService, Depends(fiscal_service)]


def _permission(*permissions: Permission):
    async def dependency(context: TenantContextDep) -> TenantContext:
        if not context.permissions.intersection(permissions):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Permission denied")
        return context

    return dependency


FiscalReadDep = Annotated[TenantContext, Depends(_permission(Permission.FISCAL_READ))]
FiscalWriteDep = Annotated[TenantContext, Depends(_permission(Permission.FISCAL_WRITE))]
