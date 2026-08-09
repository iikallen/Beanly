from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class AcceptInvitationCommand:
    token: str
    user_id: UUID
    user_email: str
    first_name: str
    last_name: str
