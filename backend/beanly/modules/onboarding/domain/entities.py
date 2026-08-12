from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from beanly.modules.onboarding.domain.enums import (
    ImportEntityType,
    ImportResolution,
    ImportSourceType,
    ImportStatus,
    OnboardingStatus,
)


@dataclass(slots=True)
class OnboardingState:
    id: UUID
    organization_id: UUID
    status: OnboardingStatus
    current_step: str | None
    started_at: datetime
    completed_at: datetime | None
    dismissed_at: datetime | None
    created_by: UUID
    updated_at: datetime


@dataclass(slots=True)
class ImportEntity:
    id: UUID
    import_run_id: UUID
    entity_type: ImportEntityType
    source_key: str
    payload: dict[str, object]
    resolution: ImportResolution
    target_id: UUID | None
    error_codes: list[str]
    warning_codes: list[str]
    sort_order: int


@dataclass(slots=True)
class ImportRun:
    id: UUID
    organization_id: UUID
    location_id: UUID
    client_import_id: UUID
    source_type: ImportSourceType
    source_name: str
    source_version: int | None
    file_name: str | None
    file_hash: str | None
    status: ImportStatus
    entity_count: int
    error_count: int
    warning_count: int
    payload_hash: str
    mapping: dict[str, str]
    created_by: UUID
    created_at: datetime
    applied_at: datetime | None
    failed_at: datetime | None
    entities: list[ImportEntity] = field(default_factory=list)
