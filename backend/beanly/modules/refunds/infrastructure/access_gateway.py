from uuid import UUID

from beanly.modules.organizations.application.queries.list_locations import ListLocationsQuery
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.organizations.domain.exceptions import OrganizationAccessDenied
from beanly.modules.refunds.domain.exceptions import RefundNotFound


class RefundAccessGateway:
    def __init__(self, organizations: OrganizationService) -> None:
        self.organizations = organizations

    async def ensure_location(self, context: TenantContext, location_id: UUID) -> None:
        try:
            await self.organizations.ensure_location_access(context, location_id)
        except OrganizationAccessDenied as exc:
            raise RefundNotFound("Location not found") from exc

    async def location_ids(self, context: TenantContext) -> tuple[UUID, ...]:
        values = await self.organizations.list_locations(
            ListLocationsQuery(context.user_id, context.organization_id)
        )
        return tuple(value.id for value in values)
