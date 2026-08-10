from typing import Annotated

from fastapi import Depends

from beanly.core.events.outbox.repositories import OutboxRepository
from beanly.core.events.outbox.writer import OutboxEventSink
from beanly.core.security.audit import SecurityAuditRecorder
from beanly.modules.identity.api.dependencies import SessionDep, SettingsDep
from beanly.modules.integrations.application.connection_service import (
    IntegrationConnectionService,
)
from beanly.modules.integrations.application.oauth_service import IntegrationOAuthService
from beanly.modules.integrations.application.webhook_service import (
    IntegrationWebhookService,
)
from beanly.modules.integrations.infrastructure.crypto import FernetSecretCipher
from beanly.modules.integrations.infrastructure.db.repositories import (
    SqlAlchemyIntegrationRepository,
)
from beanly.modules.integrations.infrastructure.providers import (
    ProviderRegistry,
    build_provider_registry,
)
from beanly.modules.organizations.api.dependencies import require_permission
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.organizations.domain.permissions import Permission
from beanly.modules.organizations.infrastructure.db.repositories import (
    SqlAlchemyOrganizationRepository,
)


def provider_registry(settings: SettingsDep) -> ProviderRegistry:
    return build_provider_registry(settings)


def cipher(settings: SettingsDep) -> FernetSecretCipher:
    return FernetSecretCipher(settings.integration_encryption_key_list)


def connection_service(
    session: SessionDep,
    settings: SettingsDep,
) -> IntegrationConnectionService:
    repository = SqlAlchemyIntegrationRepository(session)
    return IntegrationConnectionService(
        repository,
        OrganizationService(SqlAlchemyOrganizationRepository(session)),
        build_provider_registry(settings),
        FernetSecretCipher(settings.integration_encryption_key_list),
        OutboxEventSink(OutboxRepository(session)),
        SecurityAuditRecorder(session) if settings.audit_enabled else None,
    )


def webhook_service(session: SessionDep, settings: SettingsDep) -> IntegrationWebhookService:
    return IntegrationWebhookService(
        SqlAlchemyIntegrationRepository(session),
        build_provider_registry(settings),
        FernetSecretCipher(settings.integration_encryption_key_list),
    )


def oauth_service(session: SessionDep, settings: SettingsDep) -> IntegrationOAuthService:
    return IntegrationOAuthService(
        SqlAlchemyIntegrationRepository(session),
        build_provider_registry(settings),
        FernetSecretCipher(settings.integration_encryption_key_list),
        OutboxEventSink(OutboxRepository(session)),
        settings.integration_oauth_public_base_url,
    )


ConnectionServiceDep = Annotated[
    IntegrationConnectionService, Depends(connection_service)
]
WebhookServiceDep = Annotated[IntegrationWebhookService, Depends(webhook_service)]
OAuthServiceDep = Annotated[IntegrationOAuthService, Depends(oauth_service)]
RegistryDep = Annotated[ProviderRegistry, Depends(provider_registry)]
IntegrationsReadDep = Annotated[
    TenantContext, Depends(require_permission(Permission.INTEGRATIONS_READ))
]
IntegrationsWriteDep = Annotated[
    TenantContext, Depends(require_permission(Permission.INTEGRATIONS_WRITE))
]
