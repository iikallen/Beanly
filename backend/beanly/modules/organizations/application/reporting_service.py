from beanly.modules.organizations.application.queries.list_locations import (
    ListLocationsQuery,
)
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.domain.entities import Location, TenantContext


class OrganizationReportingService:
    def __init__(self, organizations: OrganizationService) -> None:
        self.organizations = organizations

    async def accessible_locations(self, context: TenantContext) -> tuple[Location, ...]:
        values = await self.organizations.list_locations(
            ListLocationsQuery(context.user_id, context.organization_id)
        )
        return tuple(values)

    async def reporting_timezone(self, context: TenantContext) -> str:
        return (await self.organizations.primary_location(context)).timezone
