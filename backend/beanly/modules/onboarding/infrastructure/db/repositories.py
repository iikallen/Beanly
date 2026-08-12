from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from beanly.modules.onboarding.domain.entities import ImportEntity, ImportRun, OnboardingState
from beanly.modules.onboarding.domain.enums import (
    ImportEntityType,
    ImportResolution,
    ImportSourceType,
    ImportStatus,
    OnboardingStatus,
)
from beanly.modules.onboarding.infrastructure.db.models import (
    OnboardingImportEntityModel,
    OnboardingImportRunModel,
    OnboardingStateModel,
)


class SqlAlchemyOnboardingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_state(
        self, organization_id: UUID, *, lock: bool = False
    ) -> OnboardingState | None:
        statement = select(OnboardingStateModel).where(
            OnboardingStateModel.organization_id == organization_id
        )
        if lock:
            statement = statement.with_for_update()
        model = await self.session.scalar(statement)
        return _state(model) if model else None

    async def add_state(self, state: OnboardingState) -> None:
        self.session.add(
            OnboardingStateModel(
                id=state.id,
                organization_id=state.organization_id,
                status=state.status.value,
                current_step=state.current_step,
                started_at=state.started_at,
                completed_at=state.completed_at,
                dismissed_at=state.dismissed_at,
                created_by=state.created_by,
                updated_at=state.updated_at,
            )
        )
        await self.session.flush()

    async def save_state(self, state: OnboardingState) -> None:
        await self.session.execute(
            update(OnboardingStateModel)
            .where(
                OnboardingStateModel.organization_id == state.organization_id,
                OnboardingStateModel.id == state.id,
            )
            .values(
                status=state.status.value,
                current_step=state.current_step,
                completed_at=state.completed_at,
                dismissed_at=state.dismissed_at,
                updated_at=state.updated_at,
            )
        )
        await self.session.flush()

    async def get_run(
        self, organization_id: UUID, run_id: UUID, *, lock: bool = False
    ) -> ImportRun | None:
        statement = (
            select(OnboardingImportRunModel)
            .where(
                OnboardingImportRunModel.organization_id == organization_id,
                OnboardingImportRunModel.id == run_id,
            )
            .options(selectinload(OnboardingImportRunModel.entities))
        )
        if lock:
            statement = statement.with_for_update()
        value = await self.session.scalar(statement)
        return _run(value) if value else None

    async def get_by_client_import_id(
        self, organization_id: UUID, client_import_id: UUID
    ) -> ImportRun | None:
        run_id = await self.session.scalar(
            select(OnboardingImportRunModel.id).where(
                OnboardingImportRunModel.organization_id == organization_id,
                OnboardingImportRunModel.client_import_id == client_import_id,
            )
        )
        return await self.get_run(organization_id, run_id) if run_id else None

    async def find_duplicate_file(
        self, organization_id: UUID, file_hash: str, exclude_id: UUID | None = None
    ) -> UUID | None:
        statement = (
            select(OnboardingImportRunModel.id)
            .where(
                OnboardingImportRunModel.organization_id == organization_id,
                OnboardingImportRunModel.file_hash == file_hash,
            )
            .order_by(OnboardingImportRunModel.created_at, OnboardingImportRunModel.id)
        )
        if exclude_id is not None:
            statement = statement.where(OnboardingImportRunModel.id != exclude_id)
        return await self.session.scalar(statement.limit(1))

    async def list_runs(
        self,
        organization_id: UUID,
        *,
        location_ids: tuple[UUID, ...],
        status: ImportStatus | None,
        source_type: ImportSourceType | None,
        limit: int,
        offset: int,
    ) -> tuple[list[ImportRun], int]:
        filters = [
            OnboardingImportRunModel.organization_id == organization_id,
            OnboardingImportRunModel.location_id.in_(location_ids),
        ]
        if status is not None:
            filters.append(OnboardingImportRunModel.status == status.value)
        if source_type is not None:
            filters.append(OnboardingImportRunModel.source_type == source_type.value)
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(OnboardingImportRunModel).where(*filters)
            )
            or 0
        )
        values = list(
            await self.session.scalars(
                select(OnboardingImportRunModel)
                .where(*filters)
                .order_by(
                    OnboardingImportRunModel.created_at.desc(),
                    OnboardingImportRunModel.id.desc(),
                )
                .limit(limit)
                .offset(offset)
            )
        )
        return [_run_summary(value) for value in values], total

    async def add_run(
        self,
        run: ImportRun,
        entities: list[ImportEntity],
    ) -> None:
        self.session.add(
            OnboardingImportRunModel(
                id=run.id,
                organization_id=run.organization_id,
                location_id=run.location_id,
                client_import_id=run.client_import_id,
                source_type=run.source_type.value,
                source_name=run.source_name,
                source_version=run.source_version,
                file_name=run.file_name,
                file_hash=run.file_hash,
                status=run.status.value,
                entity_count=run.entity_count,
                error_count=run.error_count,
                warning_count=run.warning_count,
                payload_hash=run.payload_hash,
                mapping=run.mapping,
                created_by=run.created_by,
                created_at=run.created_at,
                applied_at=run.applied_at,
                failed_at=run.failed_at,
            )
        )
        self.session.add_all(_entity_model(entity) for entity in entities)
        await self.session.flush()

    async def save_run(self, run: ImportRun) -> None:
        await self.session.execute(
            update(OnboardingImportRunModel)
            .where(
                OnboardingImportRunModel.organization_id == run.organization_id,
                OnboardingImportRunModel.id == run.id,
            )
            .values(
                status=run.status.value,
                entity_count=run.entity_count,
                error_count=run.error_count,
                warning_count=run.warning_count,
                applied_at=run.applied_at,
                failed_at=run.failed_at,
            )
        )
        await self.session.flush()

    async def save_entity(self, entity: ImportEntity) -> None:
        await self.session.execute(
            update(OnboardingImportEntityModel)
            .where(
                OnboardingImportEntityModel.import_run_id == entity.import_run_id,
                OnboardingImportEntityModel.id == entity.id,
            )
            .values(
                payload=entity.payload,
                resolution=entity.resolution.value,
                target_id=entity.target_id,
                error_codes=entity.error_codes,
                warning_codes=entity.warning_codes,
            )
        )
        await self.session.flush()

    async def flush(self) -> None:
        await self.session.flush()

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()


def _state(model: OnboardingStateModel) -> OnboardingState:
    return OnboardingState(
        model.id,
        model.organization_id,
        OnboardingStatus(model.status),
        model.current_step,
        model.started_at,
        model.completed_at,
        model.dismissed_at,
        model.created_by,
        model.updated_at,
    )


def _run(model: OnboardingImportRunModel) -> ImportRun:
    entities = sorted(model.entities, key=lambda item: (item.sort_order, str(item.id)))
    return ImportRun(
        model.id,
        model.organization_id,
        model.location_id,
        model.client_import_id,
        ImportSourceType(model.source_type),
        model.source_name,
        model.source_version,
        model.file_name,
        model.file_hash,
        ImportStatus(model.status),
        model.entity_count,
        model.error_count,
        model.warning_count,
        model.payload_hash,
        dict(model.mapping),
        model.created_by,
        model.created_at,
        model.applied_at,
        model.failed_at,
        [_entity(value) for value in entities],
    )


def _run_summary(model: OnboardingImportRunModel) -> ImportRun:
    return ImportRun(
        model.id,
        model.organization_id,
        model.location_id,
        model.client_import_id,
        ImportSourceType(model.source_type),
        model.source_name,
        model.source_version,
        model.file_name,
        model.file_hash,
        ImportStatus(model.status),
        model.entity_count,
        model.error_count,
        model.warning_count,
        model.payload_hash,
        dict(model.mapping),
        model.created_by,
        model.created_at,
        model.applied_at,
        model.failed_at,
        [],
    )


def _entity(model: OnboardingImportEntityModel) -> ImportEntity:
    return ImportEntity(
        model.id,
        model.import_run_id,
        ImportEntityType(model.entity_type),
        model.source_key,
        dict(model.payload),
        ImportResolution(model.resolution),
        model.target_id,
        list(model.error_codes),
        list(model.warning_codes),
        model.sort_order,
    )


def _entity_model(entity: ImportEntity) -> OnboardingImportEntityModel:
    return OnboardingImportEntityModel(
        id=entity.id,
        import_run_id=entity.import_run_id,
        entity_type=entity.entity_type.value,
        source_key=entity.source_key,
        payload=entity.payload,
        resolution=entity.resolution.value,
        target_id=entity.target_id,
        error_codes=entity.error_codes,
        warning_codes=entity.warning_codes,
        sort_order=entity.sort_order,
    )
