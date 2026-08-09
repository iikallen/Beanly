from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CreateLocationCommand:
    user_id: UUID
    organization_id: UUID
    name: str
    timezone: str
    address: str | None = None
