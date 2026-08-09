from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from beanly.modules.organizations.domain.enums import (
    InvitationStatus,
    LocationAccess,
    MembershipRole,
    MembershipStatus,
    OrganizationStatus,
)


@dataclass(frozen=True, slots=True)
class Organization:
    id: UUID
    name: str
    country_code: str
    currency_code: str
    status: OrganizationStatus
    created_by: UUID
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class Location:
    id: UUID
    organization_id: UUID
    name: str
    timezone: str
    address: str | None
    is_active: bool
    is_primary: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class OrganizationMembership:
    id: UUID
    organization_id: UUID
    user_id: UUID
    role: MembershipRole
    status: MembershipStatus
    location_access: LocationAccess
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class TenantContext:
    user_id: UUID
    organization_id: UUID
    membership_id: UUID
    role: MembershipRole
    permissions: frozenset["Permission"]
    location_access: LocationAccess


@dataclass(frozen=True, slots=True)
class MembershipLocation:
    membership_id: UUID
    location_id: UUID
    created_at: datetime


@dataclass(frozen=True, slots=True)
class OrganizationInvitation:
    id: UUID
    organization_id: UUID
    employee_id: UUID | None
    email: str
    role: MembershipRole
    token_hash: str
    status: InvitationStatus
    expires_at: datetime
    invited_by: UUID
    accepted_by: UUID | None
    accepted_at: datetime | None
    location_ids: tuple[UUID, ...]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class TeamMember:
    employee_id: UUID | None
    user_id: UUID | None
    first_name: str
    last_name: str
    phone: str | None
    position: str | None
    email: str | None
    role: MembershipRole | None
    status: str
    location_access: LocationAccess | None
    locations: tuple[str, ...]


from beanly.modules.organizations.domain.permissions import Permission  # noqa: E402
