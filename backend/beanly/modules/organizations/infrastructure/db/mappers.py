from datetime import UTC, datetime
from uuid import UUID

from beanly.modules.organizations.domain.entities import (
    Location,
    Organization,
    OrganizationInvitation,
    OrganizationMembership,
)
from beanly.modules.organizations.domain.enums import (
    LocationAccess,
    MembershipRole,
    MembershipStatus,
    OrganizationStatus,
)
from beanly.modules.organizations.infrastructure.db.models import (
    LocationModel,
    OrganizationInvitationModel,
    OrganizationMembershipModel,
    OrganizationModel,
)


def to_organization(model: OrganizationModel) -> Organization:
    return Organization(
        id=model.id,
        name=model.name,
        country_code=model.country_code,
        currency_code=model.currency_code,
        status=OrganizationStatus(model.status),
        created_by=model.created_by,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def to_location(model: LocationModel) -> Location:
    return Location(
        id=model.id,
        organization_id=model.organization_id,
        name=model.name,
        timezone=model.timezone,
        address=model.address,
        is_active=model.is_active,
        is_primary=model.is_primary,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def to_membership(model: OrganizationMembershipModel) -> OrganizationMembership:
    return OrganizationMembership(
        id=model.id,
        organization_id=model.organization_id,
        user_id=model.user_id,
        role=MembershipRole(model.role),
        status=MembershipStatus(model.status),
        location_access=LocationAccess(model.location_access),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def to_invitation(
    model: OrganizationInvitationModel, location_ids: tuple[UUID, ...]
) -> OrganizationInvitation:
    from beanly.modules.organizations.domain.enums import InvitationStatus

    return OrganizationInvitation(
        id=model.id,
        organization_id=model.organization_id,
        employee_id=model.employee_id,
        email=model.email,
        role=MembershipRole(model.role),
        token_hash=model.token_hash,
        status=InvitationStatus(model.status),
        expires_at=_utc(model.expires_at),
        invited_by=model.invited_by,
        accepted_by=model.accepted_by,
        accepted_at=_utc(model.accepted_at) if model.accepted_at else None,
        location_ids=location_ids,
        created_at=_utc(model.created_at),
    )


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
