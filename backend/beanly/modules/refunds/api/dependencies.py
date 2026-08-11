from typing import Annotated

from fastapi import Depends, HTTPException, status

from beanly.core.events.outbox.repositories import OutboxRepository
from beanly.core.events.outbox.writer import OutboxEventSink
from beanly.core.security.audit import SecurityAuditRecorder
from beanly.modules.identity.api.dependencies import SessionDep, SettingsDep
from beanly.modules.inventory.application.services import InventoryService
from beanly.modules.inventory.infrastructure.db.repositories import SqlAlchemyInventoryRepository
from beanly.modules.organizations.api.dependencies import TenantContextDep
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.organizations.domain.permissions import Permission
from beanly.modules.organizations.infrastructure.db.repositories import (
    SqlAlchemyOrganizationRepository,
)
from beanly.modules.refunds.application.refund_service import RefundService
from beanly.modules.refunds.infrastructure.access_gateway import RefundAccessGateway
from beanly.modules.refunds.infrastructure.db.repositories import SqlAlchemyRefundRepository
from beanly.modules.refunds.infrastructure.inventory_gateway import RefundInventoryGateway
from beanly.modules.refunds.infrastructure.source_reader import SqlAlchemyRefundSourceReader


def refund_service(session: SessionDep, settings: SettingsDep) -> RefundService:
    organizations = OrganizationService(SqlAlchemyOrganizationRepository(session))
    inventory = InventoryService(SqlAlchemyInventoryRepository(session), organizations)
    return RefundService(
        SqlAlchemyRefundRepository(session),
        SqlAlchemyRefundSourceReader(session),
        RefundInventoryGateway(inventory),
        RefundAccessGateway(organizations),
        OutboxEventSink(OutboxRepository(session)),
        SecurityAuditRecorder(session) if settings.audit_enabled else None,
    )


RefundServiceDep = Annotated[RefundService, Depends(refund_service)]


def _permission(*permissions: Permission):
    async def dependency(context: TenantContextDep) -> TenantContext:
        if not context.permissions.intersection(permissions):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Permission denied")
        return context

    return dependency


RefundReadDep = Annotated[TenantContext, Depends(_permission(Permission.SALES_READ))]


async def refund_read(context: TenantContextDep) -> TenantContext:
    if not {Permission.SALES_READ, Permission.PAYMENTS_READ}.issubset(context.permissions):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Permission denied")
    return context


RefundReadDep = Annotated[TenantContext, Depends(refund_read)]


async def refund_write(context: TenantContextDep) -> TenantContext:
    if not {Permission.SALES_REFUND, Permission.PAYMENTS_REFUND}.issubset(context.permissions):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Permission denied")
    return context


RefundWriteDep = Annotated[TenantContext, Depends(refund_write)]
