from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class UpdateLocationCommand:
    user_id: UUID
    organization_id: UUID
    location_id: UUID
    name: str | None = None
    timezone: str | None = None
    address: str | None = None
    address_set: bool = False
    is_active: bool | None = None
