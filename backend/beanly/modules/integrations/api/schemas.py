from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from beanly.modules.integrations.domain.enums import (
    IntegrationAttemptOutcome,
    IntegrationAuthType,
    IntegrationCapability,
    IntegrationConnectionStatus,
    IntegrationJobStatus,
)


class ProviderDescriptorResponse(BaseModel):
    code: str
    name: str
    capabilities: list[IntegrationCapability]
    auth_type: IntegrationAuthType
    supports_webhooks: bool
    supports_health_check: bool
    location_scoped: bool


class ConnectionCreateRequest(BaseModel):
    provider_code: str = Field(min_length=1, max_length=80)
    display_name: str = Field(min_length=1, max_length=150)
    config: dict[str, object] = Field(default_factory=dict)
    credentials: dict[str, object] | None = None


class ConnectionPatchRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=150)
    config: dict[str, object] | None = None
    credentials: dict[str, object] | None = None


class LocationBindingRequest(BaseModel):
    capability: IntegrationCapability
    external_location_id: str | None = Field(default=None, max_length=255)
    settings: dict[str, object] = Field(default_factory=dict)
    is_active: bool = True


class LocationBindingResponse(BaseModel):
    id: UUID
    location_id: UUID
    capability: IntegrationCapability
    external_location_id: str | None
    settings: dict[str, object]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ConnectionResponse(BaseModel):
    id: UUID
    provider_code: str
    display_name: str
    status: IntegrationConnectionStatus
    auth_type: IntegrationAuthType
    config: dict[str, object]
    has_credentials: bool
    external_account_id: str | None
    connected_at: datetime | None
    last_health_check_at: datetime | None
    last_success_at: datetime | None
    last_error_code: str | None
    last_error_message: str | None
    created_at: datetime
    updated_at: datetime
    can_manage: bool
    bindings: list[LocationBindingResponse]


class JobAttemptResponse(BaseModel):
    attempt_number: int
    started_at: datetime
    finished_at: datetime
    outcome: IntegrationAttemptOutcome
    http_status: int | None
    provider_request_id: str | None
    duration_ms: int | None
    error_code: str | None
    error_message: str | None


class JobResponse(BaseModel):
    id: UUID
    connection_id: UUID
    location_id: UUID | None
    capability: IntegrationCapability
    job_type: str
    source_type: str
    source_id: UUID
    idempotency_key: str
    status: IntegrationJobStatus
    available_at: datetime
    attempts: int
    external_id: str | None
    completed_at: datetime | None
    dead_lettered_at: datetime | None
    last_error_code: str | None
    last_error_message: str | None
    created_at: datetime
    updated_at: datetime
    attempt_history: list[JobAttemptResponse]


class JobListResponse(BaseModel):
    items: list[JobResponse]
    total: int
    limit: int
    offset: int


class OAuthStartResponse(BaseModel):
    authorization_url: str


class WebhookAcceptedResponse(BaseModel):
    inbox_event_id: UUID
