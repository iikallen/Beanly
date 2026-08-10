from fastapi import APIRouter

from beanly.modules.analytics.api.router import router as analytics_router
from beanly.modules.dashboard.api.router import router as dashboard_router
from beanly.modules.employees.api.router import router as employees_router
from beanly.modules.finance.api.router import router as finance_router
from beanly.modules.identity.api.router import router as auth_router
from beanly.modules.inventory.api.router import router as inventory_router
from beanly.modules.menu.api.router import router as menu_router
from beanly.modules.organizations.api.router import router as organizations_router
from beanly.modules.organizations.api.team_router import router as team_router
from beanly.modules.payments.api.router import router as payments_router
from beanly.modules.purchasing.api.router import router as purchasing_router
from beanly.modules.sales.api.router import router as sales_router

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(auth_router)
api_v1_router.include_router(inventory_router)
api_v1_router.include_router(menu_router)
api_v1_router.include_router(organizations_router)
api_v1_router.include_router(employees_router)
api_v1_router.include_router(team_router)
api_v1_router.include_router(purchasing_router)
api_v1_router.include_router(sales_router)
api_v1_router.include_router(payments_router)
api_v1_router.include_router(finance_router)
api_v1_router.include_router(dashboard_router)
api_v1_router.include_router(analytics_router)
