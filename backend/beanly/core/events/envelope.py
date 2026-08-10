from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    id: UUID
    organization_id: UUID | None
    event_name: str
    event_version: int
    aggregate_type: str | None
    aggregate_id: UUID | None
    payload: dict[str, object]
    occurred_at: datetime
