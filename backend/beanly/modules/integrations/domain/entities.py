from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from beanly.modules.integrations.domain.enums import (
    IntegrationAuthType,
    IntegrationCapability,
    IntegrationConnectionStatus,
    IntegrationJobStatus,
)


@dataclass(frozen=True, slots=True)
class IntegrationConnection:
    id: UUID
    organization_id: UUID
    provider_code: str
    display_name: str
    status: IntegrationConnectionStatus
    auth_type: IntegrationAuthType
    config: dict[str, object]
    credentials_ciphertext: str | None
    credentials_key_version: int | None
    external_account_id: str | None
    connected_at: datetime | None
    last_health_check_at: datetime | None
    last_success_at: datetime | None
    last_error_code: str | None
    last_error_message: str | None
    created_by: UUID
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class IntegrationLocationBinding:
    id: UUID
    organization_id: UUID
    connection_id: UUID
    location_id: UUID
    capability: IntegrationCapability
    external_location_id: str | None
    settings: dict[str, object]
    is_active: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class IntegrationJob:
    id: UUID
    organization_id: UUID
    connection_id: UUID
    location_id: UUID | None
    capability: IntegrationCapability
    job_type: str
    source_event_id: UUID | None
    source_type: str
    source_id: UUID
    idempotency_key: str
    status: IntegrationJobStatus
    available_at: datetime
    attempts: int
    locked_by: str | None
    locked_until: datetime | None
    external_id: str | None
    completed_at: datetime | None
    dead_lettered_at: datetime | None
    last_error_code: str | None
    last_error_message: str | None
    created_at: datetime
    updated_at: datetime
