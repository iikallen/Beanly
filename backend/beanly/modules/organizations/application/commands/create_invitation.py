from dataclasses import dataclass
from uuid import UUID

from beanly.modules.organizations.domain.enums import MembershipRole


@dataclass(frozen=True, slots=True)
class CreateInvitationCommand:
    organization_id: UUID
    invited_by: UUID
    inviter_email: str
    inviter_role: MembershipRole
    email: str
    role: MembershipRole
    location_ids: tuple[UUID, ...]
    employee_id: UUID | None = None
