from typing import Protocol
from uuid import UUID

from beanly.modules.organizations.domain.entities import (
    Location,
    MembershipLocation,
    Organization,
    OrganizationMembership,
)


class OrganizationRepository(Protocol):
    async def add_organization(self, organization: Organization) -> Organization: ...

    async def add_location(self, location: Location) -> Location: ...

    async def add_membership(
        self, membership: OrganizationMembership
    ) -> OrganizationMembership: ...

    async def list_for_user(self, user_id: UUID) -> list[Organization]: ...

    async def get_for_user(self, organization_id: UUID, user_id: UUID) -> Organization | None: ...

    async def get_membership(
        self, organization_id: UUID, user_id: UUID
    ) -> OrganizationMembership | None: ...

    async def get_membership_any_status(
        self, organization_id: UUID, user_id: UUID
    ) -> OrganizationMembership | None: ...

    async def add_membership_locations(self, locations: tuple[MembershipLocation, ...]) -> None: ...

    async def locations_belong_to_organization(
        self, organization_id: UUID, location_ids: tuple[UUID, ...]
    ) -> bool: ...

    async def membership_can_access_location(
        self, membership: OrganizationMembership, location_id: UUID
    ) -> bool: ...

    async def update_organization(self, organization: Organization) -> Organization: ...

    async def list_locations(self, organization_id: UUID) -> list[Location]: ...

    async def list_accessible_locations(
        self, membership: OrganizationMembership
    ) -> list[Location]: ...

    async def get_location(self, organization_id: UUID, location_id: UUID) -> Location | None: ...

    async def update_location(self, location: Location) -> Location: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
