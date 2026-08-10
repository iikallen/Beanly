from beanly.modules.integrations.domain.entities import (
    IntegrationConnection,
    IntegrationJob,
    IntegrationLocationBinding,
)
from beanly.modules.integrations.domain.enums import (
    IntegrationAuthType,
    IntegrationCapability,
    IntegrationConnectionStatus,
    IntegrationJobStatus,
)
from beanly.modules.integrations.infrastructure.db.models import (
    IntegrationConnectionModel,
    IntegrationJobModel,
    IntegrationLocationBindingModel,
)


def to_connection(model: IntegrationConnectionModel) -> IntegrationConnection:
    return IntegrationConnection(
        id=model.id,
        organization_id=model.organization_id,
        provider_code=model.provider_code,
        display_name=model.display_name,
        status=IntegrationConnectionStatus(model.status),
        auth_type=IntegrationAuthType(model.auth_type),
        config=dict(model.config),
        credentials_ciphertext=model.credentials_ciphertext,
        credentials_key_version=model.credentials_key_version,
        external_account_id=model.external_account_id,
        connected_at=model.connected_at,
        last_health_check_at=model.last_health_check_at,
        last_success_at=model.last_success_at,
        last_error_code=model.last_error_code,
        last_error_message=model.last_error_message,
        created_by=model.created_by,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def to_binding(model: IntegrationLocationBindingModel) -> IntegrationLocationBinding:
    return IntegrationLocationBinding(
        id=model.id,
        organization_id=model.organization_id,
        connection_id=model.connection_id,
        location_id=model.location_id,
        capability=IntegrationCapability(model.capability),
        external_location_id=model.external_location_id,
        settings=dict(model.settings),
        is_active=model.is_active,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def to_job(model: IntegrationJobModel) -> IntegrationJob:
    return IntegrationJob(
        id=model.id,
        organization_id=model.organization_id,
        connection_id=model.connection_id,
        location_id=model.location_id,
        capability=IntegrationCapability(model.capability),
        job_type=model.job_type,
        source_event_id=model.source_event_id,
        source_type=model.source_type,
        source_id=model.source_id,
        idempotency_key=model.idempotency_key,
        status=IntegrationJobStatus(model.status),
        available_at=model.available_at,
        attempts=model.attempts,
        locked_by=model.locked_by,
        locked_until=model.locked_until,
        external_id=model.external_id,
        completed_at=model.completed_at,
        dead_lettered_at=model.dead_lettered_at,
        last_error_code=model.last_error_code,
        last_error_message=model.last_error_message,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )
