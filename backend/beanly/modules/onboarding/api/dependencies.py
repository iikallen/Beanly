from typing import Annotated

from fastapi import Depends, HTTPException, status

from beanly.core.events.outbox.repositories import OutboxRepository
from beanly.core.events.outbox.writer import OutboxEventSink
from beanly.core.security.audit import SecurityAuditRecorder
from beanly.modules.identity.api.dependencies import SessionDep, SettingsDep
from beanly.modules.inventory.application.services import InventoryService
from beanly.modules.inventory.infrastructure.db.repositories import SqlAlchemyInventoryRepository
from beanly.modules.onboarding.application.import_service import ImportService
from beanly.modules.onboarding.application.onboarding_service import OnboardingService
from beanly.modules.onboarding.application.ports import (
    AiMenuExtractionPort,
    UnavailableAiMenuExtractor,
)
from beanly.modules.onboarding.application.template_service import TemplateService
from beanly.modules.onboarding.infrastructure.ai.local_vision import (
    LocalVisionExtractionAdapter,
)
from beanly.modules.onboarding.infrastructure.ai.ollama_client import OllamaMenuClient
from beanly.modules.onboarding.infrastructure.apply_gateway import SqlAlchemyImportApplyGateway
from beanly.modules.onboarding.infrastructure.db.repositories import (
    SqlAlchemyOnboardingRepository,
)
from beanly.modules.onboarding.infrastructure.gateway import SqlAlchemyOnboardingGateway
from beanly.modules.organizations.api.dependencies import TenantContextDep
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.organizations.domain.permissions import Permission
from beanly.modules.organizations.infrastructure.db.repositories import (
    SqlAlchemyOrganizationRepository,
)


def onboarding_service(session: SessionDep, settings: SettingsDep) -> OnboardingService:
    return OnboardingService(
        SqlAlchemyOnboardingRepository(session),
        SqlAlchemyOnboardingGateway(
            session,
            live_transport_enabled=settings.live_kz_fiscalization,
            nkt_configured=settings.nkt_api_key is not None,
        ),
    )


def import_service(session: SessionDep, settings: SettingsDep) -> ImportService:
    repository = SqlAlchemyOnboardingRepository(session)
    sink = OutboxEventSink(OutboxRepository(session))
    organizations = OrganizationService(SqlAlchemyOrganizationRepository(session))
    inventory = InventoryService(
        SqlAlchemyInventoryRepository(session),
        organizations,
        sink,
        audit=SecurityAuditRecorder(session) if settings.audit_enabled else None,
    )
    return ImportService(
        repository,
        SqlAlchemyImportApplyGateway(
            session,
            inventory,
            organizations,
            sink,
            SecurityAuditRecorder(session) if settings.audit_enabled else None,
        ),
    )


def template_service() -> TemplateService:
    return TemplateService()


def ai_menu_extractor(settings: SettingsDep) -> AiMenuExtractionPort:
    if settings.ai_extraction_provider == "disabled":
        return UnavailableAiMenuExtractor()
    return LocalVisionExtractionAdapter(
        OllamaMenuClient(
            settings.ai_extraction_base_url,
            settings.ai_extraction_model,
            settings.ai_extraction_timeout_seconds,
        ),
        confidence_threshold=settings.ai_extraction_confidence_threshold,
    )


OnboardingServiceDep = Annotated[OnboardingService, Depends(onboarding_service)]
ImportServiceDep = Annotated[ImportService, Depends(import_service)]
TemplateServiceDep = Annotated[TemplateService, Depends(template_service)]
AiMenuExtractorDep = Annotated[AiMenuExtractionPort, Depends(ai_menu_extractor)]


def _permissions(*required: Permission):
    async def dependency(context: TenantContextDep) -> TenantContext:
        if not all(value in context.permissions for value in required):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Permission denied")
        return context

    return dependency


OnboardingReadDep = Annotated[TenantContext, Depends(_permissions(Permission.ONBOARDING_READ))]
OnboardingWriteDep = Annotated[TenantContext, Depends(_permissions(Permission.ONBOARDING_WRITE))]
MenuImportDep = Annotated[TenantContext, Depends(_permissions(Permission.MENU_IMPORT))]
ImportApplyDep = Annotated[
    TenantContext,
    Depends(
        _permissions(
            Permission.MENU_IMPORT,
            Permission.MENU_WRITE,
            Permission.INVENTORY_WRITE,
        )
    ),
]
