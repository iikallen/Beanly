from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ListLocationsQuery:
    user_id: UUID
    organization_id: UUID
