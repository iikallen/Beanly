from datetime import datetime
from typing import Protocol
from uuid import UUID

from beanly.modules.onboarding.application.dto import CanonicalImportDraft
from beanly.modules.onboarding.domain.entities import ImportEntity, ImportRun, OnboardingState
from beanly.modules.onboarding.domain.enums import ImportSourceType, ImportStatus
from beanly.modules.organizations.domain.entities import TenantContext


class OnboardingRepository(Protocol):
    async def get_state(
        self, organization_id: UUID, *, lock: bool = False
    ) -> OnboardingState | None: ...

    async def add_state(self, state: OnboardingState) -> None: ...
    async def save_state(self, state: OnboardingState) -> None: ...

    async def get_run(
        self, organization_id: UUID, run_id: UUID, *, lock: bool = False
    ) -> ImportRun | None: ...

    async def get_by_client_import_id(
        self, organization_id: UUID, client_import_id: UUID
    ) -> ImportRun | None: ...

    async def find_duplicate_file(
        self, organization_id: UUID, file_hash: str, exclude_id: UUID | None = None
    ) -> UUID | None: ...

    async def list_runs(
        self,
        organization_id: UUID,
        *,
        location_ids: tuple[UUID, ...],
        status: ImportStatus | None,
        source_type: ImportSourceType | None,
        limit: int,
        offset: int,
    ) -> tuple[list[ImportRun], int]: ...

    async def add_run(
        self,
        run: ImportRun,
        entities: list[ImportEntity],
    ) -> None: ...

    async def save_run(self, run: ImportRun) -> None: ...
    async def save_entity(self, entity: ImportEntity) -> None: ...

    async def flush(self) -> None: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...


class BootstrapResult(Protocol):
    location_id: UUID
    warehouse_id: UUID
    register_id: UUID
    warehouse_created: bool
    register_created: bool


class OnboardingGateway(Protocol):
    async def bootstrap(
        self,
        context: TenantContext,
        warehouse_name: str,
        register_name: str,
        now: datetime,
    ) -> BootstrapResult: ...

    async def readiness(self, context: TenantContext) -> dict[str, object]: ...

    async def organization_origin(self, organization_id: UUID) -> tuple[UUID, datetime] | None: ...


class ImportApplyPort(Protocol):
    async def ensure_location_access(self, context: TenantContext, location_id: UUID) -> None: ...

    async def accessible_location_ids(self, context: TenantContext) -> tuple[UUID, ...]: ...

    async def apply(self, context: TenantContext, run: ImportRun) -> None: ...

    async def activate_ready(
        self,
        context: TenantContext,
        run: ImportRun,
        product_ids: tuple[UUID, ...],
        *,
        confirm_starter_recipes_reviewed: bool,
    ) -> tuple[list[dict[str, object]], int]: ...


class AiMenuExtractionPort(Protocol):
    @property
    def available(self) -> bool: ...

    async def extract_file(
        self, content: bytes, media_type: str, file_name: str
    ) -> CanonicalImportDraft: ...

    async def extract_url(self, public_url: str) -> CanonicalImportDraft: ...


class UnavailableAiMenuExtractor:
    @property
    def available(self) -> bool:
        return False

    async def extract_file(
        self, content: bytes, media_type: str, file_name: str
    ) -> CanonicalImportDraft:
        del content, media_type, file_name
        raise RuntimeError("AI extraction is not configured")

    async def extract_url(self, public_url: str) -> CanonicalImportDraft:
        del public_url
        raise RuntimeError("AI extraction is not configured")
