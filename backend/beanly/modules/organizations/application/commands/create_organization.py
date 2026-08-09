from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CreateOrganizationCommand:
    user_id: UUID
    name: str
    country_code: str
    currency_code: str
    location_name: str
    timezone: str
    address: str | None = None
