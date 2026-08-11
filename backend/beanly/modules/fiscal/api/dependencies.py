from typing import Annotated

from fastapi import Depends, HTTPException, status

from beanly.core.security.audit import SecurityAuditRecorder
from beanly.modules.fiscal.application.live_ports import (
    FiscalReconciliationPort,
    UnavailableFiscalReconciler,
)
from beanly.modules.fiscal.application.live_service import FiscalLiveService
from beanly.modules.fiscal.application.nkt_service import NktService
from beanly.modules.fiscal.application.service import FiscalService
from beanly.modules.fiscal.infrastructure.live_repository import SqlAlchemyFiscalLiveRepository
from beanly.modules.fiscal.infrastructure.nkt.cache_repository import NktCacheRepository
from beanly.modules.fiscal.infrastructure.nkt.client import NktHttpClient, UnconfiguredNktClient
from beanly.modules.fiscal.infrastructure.operations import SqlAlchemyFiscalOperations
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


def fiscal_service(session: SessionDep, settings: SettingsDep) -> FiscalService:
    return FiscalService(
        SqlAlchemyFiscalOperations(
            session, SecurityAuditRecorder(session) if settings.audit_enabled else None
        )
    )


FiscalServiceDep = Annotated[FiscalService, Depends(fiscal_service)]


def nkt_service(session: SessionDep, settings: SettingsDep) -> NktService:
    audit = SecurityAuditRecorder(session) if settings.audit_enabled else None
    lookup = (
        NktHttpClient(
            settings.nkt_api_key.get_secret_value(),
            timeout=(
                settings.integration_http_connect_timeout_seconds
                + settings.integration_http_read_timeout_seconds
            ),
        )
        if settings.nkt_api_key
        else UnconfiguredNktClient()
    )
    return NktService(
        NktCacheRepository(session),
        lookup,
        SqlAlchemyFiscalOperations(session, audit),
        audit,
    )


NktServiceDep = Annotated[NktService, Depends(nkt_service)]


def fiscal_reconciler() -> FiscalReconciliationPort:
    return UnavailableFiscalReconciler()


def fiscal_live_service(
    session: SessionDep,
    settings: SettingsDep,
    reconciler: Annotated[FiscalReconciliationPort, Depends(fiscal_reconciler)],
) -> FiscalLiveService:
    audit = SecurityAuditRecorder(session) if settings.audit_enabled else None
    return FiscalLiveService(
        SqlAlchemyFiscalLiveRepository(
            session,
            OrganizationService(SqlAlchemyOrganizationRepository(session)),
            audit,
        ),
        reconciler,
        live_transport_enabled=settings.live_kz_fiscalization,
        real_provider_codes=frozenset({"webkassa"}),
        nkt_configured=settings.nkt_api_key is not None,
    )


FiscalLiveServiceDep = Annotated[FiscalLiveService, Depends(fiscal_live_service)]


def _permission(*permissions: Permission):
    async def dependency(context: TenantContextDep) -> TenantContext:
        if not context.permissions.intersection(permissions):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Permission denied")
        return context

    return dependency


FiscalReadDep = Annotated[TenantContext, Depends(_permission(Permission.FISCAL_READ))]
FiscalWriteDep = Annotated[TenantContext, Depends(_permission(Permission.FISCAL_WRITE))]
