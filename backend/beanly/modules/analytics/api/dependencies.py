from typing import Annotated

from fastapi import Depends

from beanly.modules.analytics.application.analytics_query_service import (
    AnalyticsQueryService,
)
from beanly.modules.analytics.infrastructure.db.repositories import (
    SqlAlchemyAnalyticsRepository,
)
from beanly.modules.identity.api.dependencies import SessionDep
from beanly.modules.organizations.api.dependencies import require_permission
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.organizations.domain.permissions import Permission
from beanly.modules.organizations.infrastructure.db.repositories import (
    SqlAlchemyOrganizationRepository,
)


def analytics_query_service(session: SessionDep) -> AnalyticsQueryService:
    return AnalyticsQueryService(
        SqlAlchemyAnalyticsRepository(session),
        OrganizationService(SqlAlchemyOrganizationRepository(session)),
    )


AnalyticsQueryServiceDep = Annotated[
    AnalyticsQueryService, Depends(analytics_query_service)
]
AnalyticsReadDep = Annotated[
    TenantContext, Depends(require_permission(Permission.ANALYTICS_READ))
]
