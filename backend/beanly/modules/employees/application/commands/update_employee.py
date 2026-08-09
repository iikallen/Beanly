from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class UpdateEmployeeCommand:
    organization_id: UUID
    employee_id: UUID
    first_name: str | None = None
    last_name: str | None = None
    phone: str | None = None
    phone_set: bool = False
    position: str | None = None
    position_set: bool = False
    location_ids: tuple[UUID, ...] | None = None
