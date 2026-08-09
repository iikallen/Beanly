from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class DeactivateEmployeeCommand:
    organization_id: UUID
    employee_id: UUID
