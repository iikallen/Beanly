from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ListUserOrganizationsQuery:
    user_id: UUID
