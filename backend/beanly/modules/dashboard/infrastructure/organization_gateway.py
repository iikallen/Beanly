from beanly.modules.dashboard.application.dto import ScopeLocation
from beanly.modules.organizations.application.reporting_service import (
    OrganizationReportingService,
)
from beanly.modules.organizations.domain.entities import TenantContext


class OrganizationDashboardGateway:
    def __init__(self, reporting: OrganizationReportingService) -> None:
        self.reporting = reporting

    async def locations(self, context: TenantContext) -> tuple[ScopeLocation, ...]:
        return tuple(
            ScopeLocation(value.id, value.name, value.timezone, value.is_primary)
            for value in await self.reporting.accessible_locations(context)
        )

    async def reporting_timezone(self, context: TenantContext) -> str:
        return await self.reporting.reporting_timezone(context)
