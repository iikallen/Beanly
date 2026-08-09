from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RevokeInvitationCommand:
    organization_id: UUID
    invitation_id: UUID
