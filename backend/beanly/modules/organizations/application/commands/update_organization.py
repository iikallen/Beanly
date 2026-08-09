from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class UpdateOrganizationCommand:
    user_id: UUID
    organization_id: UUID
    name: str | None = None
    country_code: str | None = None
    currency_code: str | None = None
