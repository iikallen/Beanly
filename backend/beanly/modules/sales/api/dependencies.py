from typing import Annotated

from fastapi import Depends, HTTPException, status

from beanly.modules.cash_management.infrastructure.service import CashDrawerService
from beanly.modules.identity.api.dependencies import SessionDep
from beanly.modules.inventory.infrastructure.db.repositories import (
    SqlAlchemyInventoryRepository,
)
from beanly.modules.menu.application.customization_service import CustomizationService
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
from beanly.modules.promotions.infrastructure.sales_gateway import PromotionSalesPricingGateway
from beanly.modules.sales.application.order_service import OrderService
from beanly.modules.sales.application.register_service import RegisterService
from beanly.modules.sales.application.shift_service import ShiftService
from beanly.modules.sales.infrastructure.db.repositories import SqlAlchemySalesRepository
from beanly.modules.sales.infrastructure.inventory_gateway import InventorySalesGateway
from beanly.modules.sales.infrastructure.menu_gateway import MenuSalesGateway


def _dependencies(session: SessionDep):
    sales = SqlAlchemySalesRepository(session)
    organizations = OrganizationService(SqlAlchemyOrganizationRepository(session))
    inventory_repository = SqlAlchemyInventoryRepository(session)
    menu_repository = SqlAlchemyMenuRepository(session)
    customization = CustomizationService(
        menu_repository,
        InventoryApplicationGateway(inventory_repository),
        organizations,
    )
    return (
        sales,
        organizations,
        InventorySalesGateway(inventory_repository),
        MenuSalesGateway(menu_repository, customization),
    )


def register_service(session: SessionDep) -> RegisterService:
    sales, organizations, _, _ = _dependencies(session)
    return RegisterService(sales, organizations)


def shift_service(session: SessionDep) -> ShiftService:
    sales, organizations, inventory, _ = _dependencies(session)
    return ShiftService(
        sales,
        organizations,
        inventory,
        cash_drawers=CashDrawerService(session, organizations),
    )


def order_service(session: SessionDep) -> OrderService:
    sales, organizations, _, menu = _dependencies(session)
    return OrderService(
        sales,
        organizations,
        menu,
        pricing=PromotionSalesPricingGateway(session),
    )


RegisterServiceDep = Annotated[RegisterService, Depends(register_service)]
ShiftServiceDep = Annotated[ShiftService, Depends(shift_service)]
OrderServiceDep = Annotated[OrderService, Depends(order_service)]


def _permission(*required: Permission):
    async def dependency(context: TenantContextDep) -> TenantContext:
        if not context.permissions.intersection(required):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Permission denied")
        return context

    return dependency


SalesRegisterManageDep = Annotated[
    TenantContext, Depends(_permission(Permission.SALES_REGISTER_MANAGE))
]
SalesRegisterReadDep = Annotated[
    TenantContext,
    Depends(
        _permission(
            Permission.SALES_REGISTER_MANAGE,
            Permission.SALES_SHIFT_MANAGE,
        )
    ),
]
SalesShiftManageDep = Annotated[TenantContext, Depends(_permission(Permission.SALES_SHIFT_MANAGE))]
SalesCreateDep = Annotated[TenantContext, Depends(_permission(Permission.SALES_CREATE))]
SalesReadDep = Annotated[
    TenantContext,
    Depends(_permission(Permission.SALES_READ, Permission.SALES_READ_OWN)),
]
SalesCancelDep = Annotated[TenantContext, Depends(_permission(Permission.SALES_CANCEL))]
