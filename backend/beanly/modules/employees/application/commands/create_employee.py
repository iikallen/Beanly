from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CreateEmployeeCommand:
    organization_id: UUID
    first_name: str
    last_name: str
    phone: str | None
    position: str | None
    location_ids: tuple[UUID, ...]
