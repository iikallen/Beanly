from uuid import UUID

from beanly.modules.finance.domain.exceptions import FinanceNotFound
from beanly.modules.organizations.application.queries.list_locations import ListLocationsQuery
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.organizations.domain.enums import LocationAccess
from beanly.modules.organizations.domain.exceptions import OrganizationAccessDenied


async def ensure_location(
    organizations: OrganizationService, context: TenantContext, location_id: UUID
) -> None:
    try:
        await organizations.ensure_location_access(context, location_id)
    except OrganizationAccessDenied as exc:
        raise FinanceNotFound("Location not found") from exc


async def allowed_locations(
    organizations: OrganizationService, context: TenantContext
) -> set[UUID] | None:
    if context.location_access == LocationAccess.ALL:
        return None
    values = await organizations.list_locations(
        ListLocationsQuery(context.user_id, context.organization_id)
    )
    return {value.id for value in values}


async def require_report_location(
    organizations: OrganizationService,
    context: TenantContext,
    location_id: UUID | None,
) -> None:
    if location_id is not None:
        await ensure_location(organizations, context, location_id)
