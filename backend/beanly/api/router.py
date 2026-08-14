from fastapi import APIRouter

from beanly.modules.analytics.api.router import router as analytics_router
from beanly.modules.cash_management.api.router import fiscal_shift_router
from beanly.modules.cash_management.api.router import router as cash_router
from beanly.modules.customers.api.router import (
    loyalty_router,
    promotion_audience_router,
    sales_loyalty_router,
)
from beanly.modules.customers.api.router import (
    router as customers_router,
)
from beanly.modules.dashboard.api.router import router as dashboard_router
from beanly.modules.employees.api.router import router as employees_router
from beanly.modules.finance.api.router import router as finance_router
from beanly.modules.fiscal.api.router import router as fiscal_router
from beanly.modules.identity.api.router import router as auth_router
from beanly.modules.integrations.api.oauth_router import router as integration_oauth_router
from beanly.modules.integrations.api.router import router as integrations_router
from beanly.modules.integrations.api.webhook_router import (
    router as integration_webhook_router,
)
from beanly.modules.inventory.api.router import router as inventory_router
from beanly.modules.menu.api.router import router as menu_router
from beanly.modules.offline_pos.api.router import router as offline_pos_router
from beanly.modules.onboarding.api.router import router as onboarding_router
from beanly.modules.organizations.api.router import router as organizations_router
from beanly.modules.organizations.api.team_router import router as team_router
from beanly.modules.payments.api.router import router as payments_router
from beanly.modules.promotions.api.order_router import router as order_discounts_router
from beanly.modules.promotions.api.router import router as promotions_router
from beanly.modules.purchasing.api.router import router as purchasing_router
from beanly.modules.refunds.api.router import (
    payments_refunds_router,
)
from beanly.modules.refunds.api.router import (
    router as refunds_router,
)
from beanly.modules.sales.api.router import router as sales_router

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(auth_router)
api_v1_router.include_router(integration_webhook_router)
api_v1_router.include_router(integration_oauth_router)
api_v1_router.include_router(integrations_router)
api_v1_router.include_router(inventory_router)
api_v1_router.include_router(offline_pos_router)
api_v1_router.include_router(onboarding_router)
api_v1_router.include_router(menu_router)
api_v1_router.include_router(organizations_router)
api_v1_router.include_router(employees_router)
api_v1_router.include_router(team_router)
api_v1_router.include_router(customers_router)
api_v1_router.include_router(loyalty_router)
api_v1_router.include_router(sales_loyalty_router)
api_v1_router.include_router(promotion_audience_router)
api_v1_router.include_router(purchasing_router)
api_v1_router.include_router(promotions_router)
api_v1_router.include_router(order_discounts_router)
api_v1_router.include_router(sales_router)
api_v1_router.include_router(payments_router)
api_v1_router.include_router(payments_refunds_router)
api_v1_router.include_router(refunds_router)
api_v1_router.include_router(fiscal_router)
api_v1_router.include_router(finance_router)
api_v1_router.include_router(dashboard_router)
api_v1_router.include_router(analytics_router)
api_v1_router.include_router(cash_router)
api_v1_router.include_router(fiscal_shift_router)
