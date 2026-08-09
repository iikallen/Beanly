from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from beanly.modules.organizations.application.commands.create_location import (
    CreateLocationCommand,
)
from beanly.modules.organizations.application.commands.create_organization import (
    CreateOrganizationCommand,
)
from beanly.modules.organizations.application.commands.update_location import (
    UpdateLocationCommand,
)
from beanly.modules.organizations.application.commands.update_organization import (
    UpdateOrganizationCommand,
)
from beanly.modules.organizations.application.dto import CreatedWorkspace
from beanly.modules.organizations.application.ports import OrganizationRepository
from beanly.modules.organizations.application.queries.get_organization import (
    GetOrganizationQuery,
)
from beanly.modules.organizations.application.queries.list_locations import ListLocationsQuery
from beanly.modules.organizations.application.queries.list_user_organizations import (
    ListUserOrganizationsQuery,
)
from beanly.modules.organizations.domain.entities import (
    Location,
    Organization,
    OrganizationMembership,
    TenantContext,
)
from beanly.modules.organizations.domain.enums import (
    LocationAccess,
    MembershipRole,
    MembershipStatus,
    OrganizationStatus,
)
from beanly.modules.organizations.domain.exceptions import (
    CurrencyLocked,
    LocationNotFound,
    OrganizationAccessDenied,
    OrganizationNotFound,
    PermissionDenied,
)
from beanly.modules.organizations.domain.permissions import Permission, permissions_for
from beanly.modules.organizations.domain.value_objects import (
    normalize_country_code,
    normalize_currency_code,
    normalize_timezone,
)


class OrganizationService:
    def __init__(self, repository: OrganizationRepository) -> None:
        self.repository = repository

    async def create_workspace(self, command: CreateOrganizationCommand) -> CreatedWorkspace:
        now = datetime.now(UTC)
        organization = Organization(
            id=uuid4(),
            name=_name(command.name),
            country_code=normalize_country_code(command.country_code),
            currency_code=normalize_currency_code(command.currency_code),
            status=OrganizationStatus.ACTIVE,
            created_by=command.user_id,
            created_at=now,
            updated_at=now,
        )
        location = Location(
            id=uuid4(),
            organization_id=organization.id,
            name=_name(command.location_name),
            timezone=normalize_timezone(command.timezone),
            address=_address(command.address),
            is_active=True,
            is_primary=True,
            created_at=now,
            updated_at=now,
        )
        membership = OrganizationMembership(
            id=uuid4(),
            organization_id=organization.id,
            user_id=command.user_id,
            role=MembershipRole.OWNER,
            status=MembershipStatus.ACTIVE,
            location_access=LocationAccess.ALL,
            created_at=now,
            updated_at=now,
        )
        try:
            await self.repository.add_organization(organization)
            await self.repository.add_location(location)
            await self.repository.add_membership(membership)
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise
        return CreatedWorkspace(organization, location, membership)

    async def list_organizations(self, query: ListUserOrganizationsQuery) -> list[Organization]:
        return await self.repository.list_for_user(query.user_id)

    async def get_organization(self, query: GetOrganizationQuery) -> Organization:
        organization = await self.repository.get_for_user(query.organization_id, query.user_id)
        if organization is None:
            raise OrganizationNotFound
        return organization

    async def update_organization(self, command: UpdateOrganizationCommand) -> Organization:
        membership = await self._membership(command.user_id, command.organization_id)
        _require(membership.role, Permission.ORGANIZATION_UPDATE)
        organization = await self.get_organization(
            GetOrganizationQuery(command.user_id, command.organization_id)
        )
        currency_code = (
            normalize_currency_code(command.currency_code)
            if command.currency_code is not None
            else organization.currency_code
        )
        if currency_code != organization.currency_code:
            raise CurrencyLocked(
                "Currency cannot change after organization creation"
            )
        updated = replace(
            organization,
            name=_name(command.name) if command.name is not None else organization.name,
            country_code=(
                normalize_country_code(command.country_code)
                if command.country_code is not None
                else organization.country_code
            ),
            currency_code=currency_code,
            updated_at=datetime.now(UTC),
        )
        await self.repository.update_organization(updated)
        await self.repository.commit()
        return updated

    async def create_location(self, command: CreateLocationCommand) -> Location:
        membership = await self._membership(command.user_id, command.organization_id)
        _require(membership.role, Permission.LOCATION_CREATE)
        now = datetime.now(UTC)
        location = Location(
            id=uuid4(),
            organization_id=command.organization_id,
            name=_name(command.name),
            timezone=normalize_timezone(command.timezone),
            address=_address(command.address),
            is_active=True,
            is_primary=False,
            created_at=now,
            updated_at=now,
        )
        await self.repository.add_location(location)
        await self.repository.commit()
        return location

    async def list_locations(self, query: ListLocationsQuery) -> list[Location]:
        membership = await self._membership(query.user_id, query.organization_id)
        return await self.repository.list_accessible_locations(membership)

    async def get_location(
        self, user_id: UUID, organization_id: UUID, location_id: UUID
    ) -> Location:
        membership = await self._membership(user_id, organization_id)
        if not await self.repository.membership_can_access_location(membership, location_id):
            raise LocationNotFound
        location = await self.repository.get_location(organization_id, location_id)
        if location is None:
            raise LocationNotFound
        return location

    async def update_location(self, command: UpdateLocationCommand) -> Location:
        membership = await self._membership(command.user_id, command.organization_id)
        _require(membership.role, Permission.LOCATION_UPDATE)
        location = await self.get_location(
            command.user_id, command.organization_id, command.location_id
        )
        updated = replace(
            location,
            name=_name(command.name) if command.name is not None else location.name,
            timezone=(
                normalize_timezone(command.timezone)
                if command.timezone is not None
                else location.timezone
            ),
            address=_address(command.address) if command.address_set else location.address,
            is_active=(command.is_active if command.is_active is not None else location.is_active),
            updated_at=datetime.now(UTC),
        )
        await self.repository.update_location(updated)
        await self.repository.commit()
        return updated

    async def tenant_context(self, user_id: UUID, organization_id: UUID) -> TenantContext:
        membership = await self.repository.get_membership(organization_id, user_id)
        if membership is None:
            raise OrganizationAccessDenied
        return TenantContext(
            user_id=user_id,
            organization_id=organization_id,
            membership_id=membership.id,
            role=membership.role,
            permissions=permissions_for(membership.role),
            location_access=membership.location_access,
        )

    async def ensure_location_access(self, context: TenantContext, location_id: UUID) -> None:
        membership = await self._membership(context.user_id, context.organization_id)
        if not await self.repository.membership_can_access_location(membership, location_id):
            raise OrganizationAccessDenied

    async def _membership(self, user_id: UUID, organization_id: UUID) -> OrganizationMembership:
        membership = await self.repository.get_membership(organization_id, user_id)
        if membership is None:
            raise OrganizationNotFound
        return membership


def _name(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 150:
        raise ValueError("Name must contain between 1 and 150 characters")
    return normalized


def _address(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _require(role: MembershipRole, permission: Permission) -> None:
    if permission not in permissions_for(role):
        raise PermissionDenied
