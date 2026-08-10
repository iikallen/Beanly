from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class IntegrationConnectionCreated:
    connection_id: UUID
    organization_id: UUID


@dataclass(frozen=True, slots=True)
class IntegrationConnectionActivated:
    connection_id: UUID
    organization_id: UUID


@dataclass(frozen=True, slots=True)
class IntegrationConnectionDegraded:
    connection_id: UUID
    organization_id: UUID


@dataclass(frozen=True, slots=True)
class IntegrationConnectionRevoked:
    connection_id: UUID
    organization_id: UUID


@dataclass(frozen=True, slots=True)
class IntegrationJobSucceeded:
    job_id: UUID
    organization_id: UUID


@dataclass(frozen=True, slots=True)
class IntegrationJobDeadLettered:
    job_id: UUID
    organization_id: UUID


@dataclass(frozen=True, slots=True)
class IntegrationWebhookProcessed:
    inbox_event_id: UUID
    organization_id: UUID
