from typing import Annotated

from fastapi import Depends

from beanly.modules.dashboard.application.dashboard_query_service import (
    DashboardQueryService,
)
from beanly.modules.dashboard.infrastructure.finance_gateway import (
    FinanceDashboardGateway,
)
from beanly.modules.dashboard.infrastructure.inventory_gateway import (
    InventoryDashboardGateway,
)
from beanly.modules.dashboard.infrastructure.organization_gateway import (
    OrganizationDashboardGateway,
)
from beanly.modules.dashboard.infrastructure.payments_gateway import (
    PaymentsDashboardGateway,
)
from beanly.modules.dashboard.infrastructure.sales_gateway import SalesDashboardGateway
from beanly.modules.finance.application.finance_query_service import FinanceQueryService
from beanly.modules.finance.infrastructure.db.repositories import SqlAlchemyFinanceRepository
from beanly.modules.identity.api.dependencies import SessionDep
from beanly.modules.inventory.application.reporting_service import (
    InventoryReportingService,
)
from beanly.modules.inventory.infrastructure.db.repositories import (
    SqlAlchemyInventoryRepository,
)
from beanly.modules.organizations.api.dependencies import require_permission
from beanly.modules.organizations.application.reporting_service import (
    OrganizationReportingService,
)
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.organizations.domain.permissions import Permission
from beanly.modules.organizations.infrastructure.db.repositories import (
    SqlAlchemyOrganizationRepository,
)
from beanly.modules.payments.application.reporting_service import (
    PaymentsReportingService,
)
from beanly.modules.payments.infrastructure.db.repositories import (
    SqlAlchemyPaymentRepository,
)
from beanly.modules.sales.application.reporting_service import SalesReportingService
from beanly.modules.sales.infrastructure.db.repositories import SqlAlchemySalesRepository


def dashboard_query_service(session: SessionDep) -> DashboardQueryService:
    organization_service = OrganizationService(SqlAlchemyOrganizationRepository(session))
    payments = PaymentsReportingService(SqlAlchemyPaymentRepository(session))
    return DashboardQueryService(
        OrganizationDashboardGateway(
            OrganizationReportingService(organization_service)
        ),
        SalesDashboardGateway(
            payments,
            SalesReportingService(SqlAlchemySalesRepository(session)),
        ),
        PaymentsDashboardGateway(payments),
        InventoryDashboardGateway(
            InventoryReportingService(SqlAlchemyInventoryRepository(session))
        ),
        FinanceDashboardGateway(
            FinanceQueryService(
                SqlAlchemyFinanceRepository(session), organization_service
            )
        ),
    )


DashboardQueryServiceDep = Annotated[
    DashboardQueryService, Depends(dashboard_query_service)
]
DashboardReadDep = Annotated[
    TenantContext, Depends(require_permission(Permission.ANALYTICS_READ))
]
