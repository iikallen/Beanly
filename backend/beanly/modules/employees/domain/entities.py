from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from beanly.modules.employees.domain.enums import EmployeeStatus


@dataclass(frozen=True, slots=True)
class Employee:
    id: UUID
    organization_id: UUID
    user_id: UUID | None
    first_name: str
    last_name: str
    phone: str | None
    position: str | None
    status: EmployeeStatus
    location_ids: tuple[UUID, ...]
    created_at: datetime
    updated_at: datetime
