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
from beanly.modules.purchasing.application.services import PurchasingService
from beanly.modules.purchasing.infrastructure.db.repositories import (
    SqlAlchemyPurchasingRepository,
)
from beanly.modules.purchasing.infrastructure.inventory_gateway import (
    InventoryApplicationGateway,
    PurchasingReferenceValidator,
)


def purchasing_service(session: SessionDep) -> PurchasingService:
    repository = SqlAlchemyPurchasingRepository(session)
    organizations = OrganizationService(SqlAlchemyOrganizationRepository(session))
    inventory = InventoryService(
        SqlAlchemyInventoryRepository(session),
        organizations,
        reference_validator=PurchasingReferenceValidator(repository),
    )
    return PurchasingService(
        repository,
        organizations,
        InventoryApplicationGateway(inventory),
        OutboxEventSink(OutboxRepository(session)),
    )


PurchasingServiceDep = Annotated[PurchasingService, Depends(purchasing_service)]


def _permission(permission: Permission):
    async def dependency(context: TenantContextDep) -> TenantContext:
        if permission not in context.permissions:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Permission denied")
        return context

    return dependency


PurchasingReadDep = Annotated[TenantContext, Depends(_permission(Permission.PURCHASING_READ))]
PurchasingCreateDep = Annotated[TenantContext, Depends(_permission(Permission.PURCHASING_CREATE))]
PurchasingUpdateDep = Annotated[TenantContext, Depends(_permission(Permission.PURCHASING_UPDATE))]
PurchasingReceiveDep = Annotated[TenantContext, Depends(_permission(Permission.PURCHASING_RECEIVE))]
PurchasingCancelDep = Annotated[TenantContext, Depends(_permission(Permission.PURCHASING_CANCEL))]
