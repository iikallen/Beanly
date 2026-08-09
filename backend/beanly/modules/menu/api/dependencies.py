from typing import Annotated

from fastapi import Depends, HTTPException, status

from beanly.modules.identity.api.dependencies import SessionDep
from beanly.modules.inventory.infrastructure.db.repositories import (
    SqlAlchemyInventoryRepository,
)
from beanly.modules.menu.application.services import MenuService
from beanly.modules.menu.infrastructure.db.repositories import SqlAlchemyMenuRepository
from beanly.modules.menu.infrastructure.inventory_gateway import InventoryApplicationGateway
from beanly.modules.organizations.api.dependencies import TenantContextDep
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.organizations.domain.permissions import Permission
from beanly.modules.organizations.infrastructure.db.repositories import (
    SqlAlchemyOrganizationRepository,
)


def menu_service(session: SessionDep) -> MenuService:
    inventory_repository = SqlAlchemyInventoryRepository(session)
    return MenuService(
        SqlAlchemyMenuRepository(session),
        InventoryApplicationGateway(inventory_repository),
        OrganizationService(SqlAlchemyOrganizationRepository(session)),
    )


MenuServiceDep = Annotated[MenuService, Depends(menu_service)]


def _permission(*required: Permission):
    async def dependency(context: TenantContextDep) -> TenantContext:
        if not context.permissions.intersection(required):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Permission denied")
        return context

    return dependency


MenuReadDep = Annotated[TenantContext, Depends(_permission(Permission.MENU_READ))]
MenuProductCreateDep = Annotated[
    TenantContext,
    Depends(_permission(Permission.MENU_PRODUCT_CREATE, Permission.MENU_WRITE)),
]
MenuProductUpdateDep = Annotated[
    TenantContext,
    Depends(_permission(Permission.MENU_PRODUCT_UPDATE, Permission.MENU_WRITE)),
]
MenuProductArchiveDep = Annotated[
    TenantContext,
    Depends(_permission(Permission.MENU_PRODUCT_ARCHIVE, Permission.MENU_WRITE)),
]
MenuRecipeReadDep = Annotated[
    TenantContext,
    Depends(_permission(Permission.MENU_RECIPE_READ, Permission.MENU_WRITE)),
]
MenuRecipeWriteDep = Annotated[
    TenantContext,
    Depends(_permission(Permission.MENU_RECIPE_WRITE, Permission.MENU_WRITE)),
]
MenuPriceWriteDep = Annotated[
    TenantContext,
    Depends(_permission(Permission.MENU_PRICE_WRITE, Permission.MENU_WRITE)),
]
