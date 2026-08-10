from typing import Annotated

from fastapi import Depends, HTTPException, status

from beanly.core.events.outbox.repositories import OutboxRepository
from beanly.core.events.outbox.writer import OutboxEventSink
from beanly.modules.identity.api.dependencies import SessionDep
from beanly.modules.inventory.application.services import InventoryService
from beanly.modules.inventory.infrastructure.db.repositories import (
    SqlAlchemyInventoryRepository,
)
from beanly.modules.organizations.api.dependencies import TenantContextDep
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.organizations.domain.permissions import Permission
from beanly.modules.organizations.infrastructure.db.repositories import (
    SqlAlchemyOrganizationRepository,
)


def inventory_service(session: SessionDep) -> InventoryService:
    return InventoryService(
        SqlAlchemyInventoryRepository(session),
        OrganizationService(SqlAlchemyOrganizationRepository(session)),
        OutboxEventSink(OutboxRepository(session)),
    )


InventoryServiceDep = Annotated[InventoryService, Depends(inventory_service)]


async def inventory_read(context: TenantContextDep) -> TenantContext:
    if not context.permissions & {
        Permission.INVENTORY_READ,
        Permission.INVENTORY_READ_LIMITED,
    }:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Permission denied")
    return context


async def inventory_full_read(context: TenantContextDep) -> TenantContext:
    if Permission.INVENTORY_READ not in context.permissions:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Permission denied")
    return context


async def inventory_write(context: TenantContextDep) -> TenantContext:
    if Permission.INVENTORY_WRITE not in context.permissions:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Permission denied")
    return context


async def inventory_adjust(context: TenantContextDep) -> TenantContext:
    if Permission.INVENTORY_ADJUST not in context.permissions:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Permission denied")
    return context


InventoryReadDep = Annotated[TenantContext, Depends(inventory_read)]
InventoryFullReadDep = Annotated[TenantContext, Depends(inventory_full_read)]
InventoryWriteDep = Annotated[TenantContext, Depends(inventory_write)]
InventoryAdjustDep = Annotated[TenantContext, Depends(inventory_adjust)]
