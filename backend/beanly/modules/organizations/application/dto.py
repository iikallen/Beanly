from dataclasses import dataclass

from beanly.modules.organizations.domain.entities import (
    Location,
    Organization,
    OrganizationMembership,
)


@dataclass(frozen=True, slots=True)
class CreatedWorkspace:
    organization: Organization
    location: Location
    membership: OrganizationMembership
