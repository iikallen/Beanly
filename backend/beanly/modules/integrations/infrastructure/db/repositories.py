import random
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from beanly.modules.integrations.application.dto import NormalizedWebhookEvent, OAuthSession
from beanly.modules.integrations.domain.entities import (
    IntegrationConnection,
    IntegrationJob,
    IntegrationLocationBinding,
)
from beanly.modules.integrations.domain.enums import (
    IntegrationAttemptOutcome,
    IntegrationCapability,
    IntegrationJobStatus,
)
from beanly.modules.integrations.domain.exceptions import IntegrationNotFound
from beanly.modules.integrations.infrastructure.db.mappers import (
    to_binding,
    to_connection,
    to_job,
)
from beanly.modules.integrations.infrastructure.db.models import (
    IntegrationConnectionModel,
    IntegrationInboxEventModel,
    IntegrationJobAttemptModel,
    IntegrationJobModel,
    IntegrationLocationBindingModel,
    IntegrationOAuthSessionModel,
)


class SqlAlchemyIntegrationRepository:
    def __init__(
        self,
        session: AsyncSession,
        *,
        jitter: Callable[[float, float], float] = random.uniform,
    ) -> None:
        self.session = session
        self._jitter = jitter

    async def add_connection(self, value: IntegrationConnection) -> IntegrationConnection:
        model = IntegrationConnectionModel(
            **{
                field: getattr(value, field)
                for field in value.__dataclass_fields__
                if field not in {"status", "auth_type"}
            },
            status=value.status.value,
            auth_type=value.auth_type.value,
        )
        self.session.add(model)
        await self.session.flush()
        return to_connection(model)

    async def get_connection(
        self, organization_id: UUID, connection_id: UUID
    ) -> IntegrationConnection | None:
        model = await self.session.scalar(
            select(IntegrationConnectionModel).where(
                IntegrationConnectionModel.id == connection_id,
                IntegrationConnectionModel.organization_id == organization_id,
            )
        )
        return to_connection(model) if model else None

    async def get_connection_by_id(self, connection_id: UUID) -> IntegrationConnection | None:
        model = await self.session.get(IntegrationConnectionModel, connection_id)
        return to_connection(model) if model else None

    async def list_connections(self, organization_id: UUID) -> list[IntegrationConnection]:
        models = await self.session.scalars(
            select(IntegrationConnectionModel)
            .where(IntegrationConnectionModel.organization_id == organization_id)
            .order_by(IntegrationConnectionModel.created_at)
        )
        return [to_connection(model) for model in models]

    async def update_connection(self, value: IntegrationConnection) -> IntegrationConnection:
        model = await self.session.scalar(
            select(IntegrationConnectionModel).where(
                IntegrationConnectionModel.id == value.id,
                IntegrationConnectionModel.organization_id == value.organization_id,
            )
        )
        if model is None:
            raise IntegrationNotFound("Integration connection not found")
        for field in (
            "display_name",
            "status",
            "config",
            "credentials_ciphertext",
            "credentials_key_version",
            "external_account_id",
            "connected_at",
            "last_health_check_at",
            "last_success_at",
            "last_error_code",
            "last_error_message",
            "updated_at",
        ):
            current = getattr(value, field)
            setattr(model, field, current.value if hasattr(current, "value") else current)
        await self.session.flush()
        return to_connection(model)

    async def active_connections(
        self,
        organization_id: UUID,
        capability: IntegrationCapability,
        location_id: UUID | None = None,
    ) -> list[tuple[IntegrationConnection, UUID | None]]:
        statement = (
            select(IntegrationConnectionModel, IntegrationLocationBindingModel.location_id)
            .join(
                IntegrationLocationBindingModel,
                IntegrationLocationBindingModel.connection_id == IntegrationConnectionModel.id,
            )
            .where(
                IntegrationConnectionModel.organization_id == organization_id,
                IntegrationConnectionModel.status == "ACTIVE",
                IntegrationLocationBindingModel.capability == capability.value,
                IntegrationLocationBindingModel.organization_id == organization_id,
                IntegrationLocationBindingModel.is_active.is_(True),
            )
        )
        if location_id is not None:
            statement = statement.where(
                IntegrationLocationBindingModel.location_id == location_id
            )
        rows = (await self.session.execute(statement)).all()
        return [(to_connection(connection), bound_location) for connection, bound_location in rows]

    async def upsert_binding(
        self, value: IntegrationLocationBinding
    ) -> IntegrationLocationBinding:
        model = await self.session.scalar(
            select(IntegrationLocationBindingModel).where(
                IntegrationLocationBindingModel.connection_id == value.connection_id,
                IntegrationLocationBindingModel.organization_id == value.organization_id,
                IntegrationLocationBindingModel.location_id == value.location_id,
                IntegrationLocationBindingModel.capability == value.capability.value,
            )
        )
        if model is None:
            model = IntegrationLocationBindingModel(
                id=value.id,
                organization_id=value.organization_id,
                connection_id=value.connection_id,
                location_id=value.location_id,
                capability=value.capability.value,
                external_location_id=value.external_location_id,
                settings=value.settings,
                is_active=value.is_active,
                created_at=value.created_at,
                updated_at=value.updated_at,
            )
            self.session.add(model)
        else:
            model.external_location_id = value.external_location_id
            model.settings = value.settings
            model.is_active = value.is_active
            model.updated_at = value.updated_at
        await self.session.flush()
        return to_binding(model)

    async def list_bindings(
        self, organization_id: UUID, connection_id: UUID
    ) -> list[IntegrationLocationBinding]:
        models = await self.session.scalars(
            select(IntegrationLocationBindingModel)
            .where(
                IntegrationLocationBindingModel.connection_id == connection_id,
                IntegrationLocationBindingModel.organization_id == organization_id,
            )
            .order_by(IntegrationLocationBindingModel.created_at)
        )
        return [to_binding(model) for model in models]

    async def delete_binding(
        self,
        organization_id: UUID,
        connection_id: UUID,
        location_id: UUID,
        capability: IntegrationCapability,
    ) -> bool:
        model = await self.session.scalar(
            select(IntegrationLocationBindingModel).where(
                IntegrationLocationBindingModel.connection_id == connection_id,
                IntegrationLocationBindingModel.organization_id == organization_id,
                IntegrationLocationBindingModel.location_id == location_id,
                IntegrationLocationBindingModel.capability == capability.value,
            )
        )
        if model is None:
            return False
        await self.session.delete(model)
        await self.session.flush()
        return True

    async def add_job(self, value: IntegrationJob) -> IntegrationJob:
        existing = await self.session.scalar(
            select(IntegrationJobModel).where(
                IntegrationJobModel.connection_id == value.connection_id,
                IntegrationJobModel.idempotency_key == value.idempotency_key,
            )
        )
        if existing:
            return to_job(existing)
        model = IntegrationJobModel(
            **{
                field: getattr(value, field)
                for field in value.__dataclass_fields__
                if field not in {"capability", "status"}
            },
            capability=value.capability.value,
            status=value.status.value,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(model)
                await self.session.flush()
        except IntegrityError:
            existing = await self.session.scalar(
                select(IntegrationJobModel).where(
                    IntegrationJobModel.connection_id == value.connection_id,
                    IntegrationJobModel.idempotency_key == value.idempotency_key,
                )
            )
            if existing is None:
                raise
            return to_job(existing)
        return to_job(model)

    async def claim_jobs(
        self, worker_id: str, batch_size: int, lease_seconds: int, now: datetime | None = None
    ) -> list[IntegrationJob]:
        timestamp = _utc(now)
        models = list(
            await self.session.scalars(
                select(IntegrationJobModel)
                .where(
                    IntegrationJobModel.available_at <= timestamp,
                    or_(
                        (
                            IntegrationJobModel.status.in_(["PENDING", "RETRYING"])
                            & or_(
                                IntegrationJobModel.locked_until.is_(None),
                                IntegrationJobModel.locked_until < timestamp,
                            )
                        ),
                        (
                            (IntegrationJobModel.status == "PROCESSING")
                            & (IntegrationJobModel.locked_until < timestamp)
                        ),
                    ),
                )
                .order_by(IntegrationJobModel.available_at, IntegrationJobModel.id)
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            )
        )
        lease_until = timestamp + timedelta(seconds=lease_seconds)
        for model in models:
            model.status = IntegrationJobStatus.PROCESSING.value
            model.locked_by = worker_id
            model.locked_until = lease_until
        if models:
            await self.session.flush()
        return [to_job(model) for model in models]

    async def mark_job_succeeded(
        self,
        job_id: UUID,
        worker_id: str,
        *,
        external_id: str,
        provider_request_id: str | None,
        started_at: datetime,
        duration_ms: int,
        now: datetime | None = None,
    ) -> None:
        timestamp = _utc(now)
        model = await self._owned_job(job_id, worker_id, timestamp)
        model.attempts += 1
        attempt_number = await self._next_attempt_number(model.id)
        model.status = IntegrationJobStatus.SUCCESS.value
        model.external_id = external_id
        model.completed_at = timestamp
        model.locked_by = None
        model.locked_until = None
        model.last_error_code = None
        model.last_error_message = None
        self._attempt(
            model.id,
            attempt_number,
            started_at,
            timestamp,
            IntegrationAttemptOutcome.SUCCESS,
            duration_ms,
            provider_request_id=provider_request_id,
        )
        await self.session.flush()

    async def mark_job_failed(
        self,
        job_id: UUID,
        worker_id: str,
        error: BaseException,
        max_attempts: int,
        *,
        temporary: bool,
        started_at: datetime,
        duration_ms: int,
        now: datetime | None = None,
    ) -> None:
        timestamp = _utc(now)
        model = await self._owned_job(job_id, worker_id, timestamp)
        model.attempts += 1
        attempt_number = await self._next_attempt_number(model.id)
        code = str(getattr(error, "code", type(error).__name__))[:100]
        message = str(
            getattr(error, "public_message", "Provider request failed")
        )[:1000]
        model.last_error_code = code
        model.last_error_message = message
        model.locked_by = None
        model.locked_until = None
        if temporary and model.attempts < max_attempts:
            model.status = IntegrationJobStatus.RETRYING.value
            ceiling = min(2 ** (model.attempts - 1), 300)
            model.available_at = timestamp + timedelta(
                seconds=self._jitter(ceiling / 2, ceiling)
            )
        else:
            model.status = IntegrationJobStatus.DEAD.value
            model.dead_lettered_at = timestamp
        self._attempt(
            model.id,
            attempt_number,
            started_at,
            timestamp,
            (
                IntegrationAttemptOutcome.TEMPORARY_FAILURE
                if temporary
                else IntegrationAttemptOutcome.PERMANENT_FAILURE
            ),
            duration_ms,
            http_status=getattr(error, "http_status", None),
            error_code=code,
            error_message=message,
        )
        await self.session.flush()

    async def list_jobs(
        self,
        organization_id: UUID,
        *,
        connection_id: UUID | None = None,
        status: IntegrationJobStatus | None = None,
        job_type: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[IntegrationJob], int]:
        filters = [IntegrationJobModel.organization_id == organization_id]
        if connection_id:
            filters.append(IntegrationJobModel.connection_id == connection_id)
        if status:
            filters.append(IntegrationJobModel.status == status.value)
        if job_type:
            filters.append(IntegrationJobModel.job_type == job_type)
        if date_from:
            filters.append(IntegrationJobModel.created_at >= date_from)
        if date_to:
            filters.append(IntegrationJobModel.created_at < date_to)
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(IntegrationJobModel).where(*filters)
            )
            or 0
        )
        models = await self.session.scalars(
            select(IntegrationJobModel)
            .where(*filters)
            .order_by(IntegrationJobModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return [to_job(model) for model in models], total

    async def get_job(self, organization_id: UUID, job_id: UUID) -> IntegrationJob | None:
        model = await self.session.scalar(
            select(IntegrationJobModel).where(
                IntegrationJobModel.id == job_id,
                IntegrationJobModel.organization_id == organization_id,
            )
        )
        return to_job(model) if model else None

    async def list_attempts(
        self, job_ids: list[UUID]
    ) -> dict[UUID, list[IntegrationJobAttemptModel]]:
        if not job_ids:
            return {}
        models = await self.session.scalars(
            select(IntegrationJobAttemptModel)
            .where(IntegrationJobAttemptModel.job_id.in_(job_ids))
            .order_by(
                IntegrationJobAttemptModel.job_id,
                IntegrationJobAttemptModel.attempt_number,
            )
        )
        result: dict[UUID, list[IntegrationJobAttemptModel]] = {}
        for model in models:
            result.setdefault(model.job_id, []).append(model)
        return result

    async def retry_job(self, organization_id: UUID, job_id: UUID) -> IntegrationJob:
        model = await self.session.scalar(
            select(IntegrationJobModel)
            .where(
                IntegrationJobModel.id == job_id,
                IntegrationJobModel.organization_id == organization_id,
            )
            .with_for_update()
        )
        if model is None:
            raise IntegrationNotFound("Integration job not found")
        if model.status != IntegrationJobStatus.DEAD.value:
            raise ValueError("Only dead jobs can be retried")
        model.status = IntegrationJobStatus.RETRYING.value
        model.attempts = 0
        model.available_at = datetime.now(UTC)
        model.dead_lettered_at = None
        model.locked_by = None
        model.locked_until = None
        model.updated_at = datetime.now(UTC)
        await self.session.flush()
        return to_job(model)

    async def add_inbox_event(
        self,
        connection: IntegrationConnection,
        event: NormalizedWebhookEvent,
        payload_hash: str,
        now: datetime | None = None,
    ) -> UUID:
        timestamp = _utc(now)
        existing = await self.session.scalar(
            select(IntegrationInboxEventModel.id).where(
                IntegrationInboxEventModel.connection_id == connection.id,
                IntegrationInboxEventModel.external_event_id == event.external_event_id,
            )
        )
        if existing:
            return existing
        model = IntegrationInboxEventModel(
            id=uuid4(),
            organization_id=connection.organization_id,
            connection_id=connection.id,
            provider_code=connection.provider_code,
            external_event_id=event.external_event_id,
            event_type=event.event_type,
            payload=event.payload,
            payload_hash=payload_hash,
            received_at=timestamp,
            attempts=0,
            available_at=timestamp,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(model)
                await self.session.flush()
        except IntegrityError:
            existing = await self.session.scalar(
                select(IntegrationInboxEventModel.id).where(
                    IntegrationInboxEventModel.connection_id == connection.id,
                    IntegrationInboxEventModel.external_event_id == event.external_event_id,
                )
            )
            if existing is None:
                raise
            return existing
        return model.id

    async def claim_inbox(
        self, worker_id: str, batch_size: int, lease_seconds: int, now: datetime | None = None
    ) -> list[UUID]:
        timestamp = _utc(now)
        models = list(
            await self.session.scalars(
                select(IntegrationInboxEventModel)
                .where(
                    IntegrationInboxEventModel.processed_at.is_(None),
                    IntegrationInboxEventModel.dead_lettered_at.is_(None),
                    IntegrationInboxEventModel.available_at <= timestamp,
                    or_(
                        IntegrationInboxEventModel.locked_until.is_(None),
                        IntegrationInboxEventModel.locked_until < timestamp,
                    ),
                )
                .order_by(
                    IntegrationInboxEventModel.received_at,
                    IntegrationInboxEventModel.id,
                )
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            )
        )
        for model in models:
            model.locked_by = worker_id
            model.locked_until = timestamp + timedelta(seconds=lease_seconds)
        if models:
            await self.session.flush()
        return [model.id for model in models]

    async def mark_inbox_processed(
        self, inbox_id: UUID, worker_id: str, now: datetime | None = None
    ) -> UUID:
        timestamp = _utc(now)
        model = await self._owned_inbox(inbox_id, worker_id, timestamp)
        model.processed_at = timestamp
        model.attempts += 1
        model.locked_by = None
        model.locked_until = None
        await self.session.flush()
        return model.organization_id

    async def mark_inbox_failed(
        self,
        inbox_id: UUID,
        worker_id: str,
        error: BaseException,
        max_attempts: int,
        now: datetime | None = None,
    ) -> None:
        timestamp = _utc(now)
        model = await self._owned_inbox(inbox_id, worker_id, timestamp)
        model.attempts += 1
        code = str(getattr(error, "code", type(error).__name__))[:100]
        message = str(getattr(error, "public_message", "Inbox processing failed"))[:1000]
        model.last_error = f"{code}: {message}"
        model.locked_by = None
        model.locked_until = None
        if model.attempts >= max_attempts:
            model.dead_lettered_at = timestamp
        else:
            ceiling = min(2 ** (model.attempts - 1), 300)
            model.available_at = timestamp + timedelta(
                seconds=self._jitter(ceiling / 2, ceiling)
            )
        await self.session.flush()

    async def add_oauth_session(
        self,
        organization_id: UUID,
        user_id: UUID,
        provider_code: str,
        state_hash: str,
        verifier_ciphertext: str,
        redirect_uri: str,
        expires_at: datetime,
    ) -> UUID:
        session_id = uuid4()
        self.session.add(
            IntegrationOAuthSessionModel(
                id=session_id,
                organization_id=organization_id,
                user_id=user_id,
                provider_code=provider_code,
                state_hash=state_hash,
                code_verifier_ciphertext=verifier_ciphertext,
                redirect_uri=redirect_uri,
                expires_at=expires_at,
                created_at=datetime.now(UTC),
            )
        )
        await self.session.flush()
        return session_id

    async def consume_oauth_session(
        self, provider_code: str, state_hash: str, now: datetime | None = None
    ) -> OAuthSession | None:
        timestamp = _utc(now)
        model = await self.session.scalar(
            select(IntegrationOAuthSessionModel)
            .where(
                IntegrationOAuthSessionModel.provider_code == provider_code,
                IntegrationOAuthSessionModel.state_hash == state_hash,
                IntegrationOAuthSessionModel.used_at.is_(None),
                IntegrationOAuthSessionModel.expires_at > timestamp,
            )
            .with_for_update()
        )
        if model:
            model.used_at = timestamp
            await self.session.flush()
        return (
            OAuthSession(
                model.id,
                model.organization_id,
                model.user_id,
                model.code_verifier_ciphertext,
                model.redirect_uri,
            )
            if model
            else None
        )

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()

    async def _owned_job(
        self, job_id: UUID, worker_id: str, timestamp: datetime
    ) -> IntegrationJobModel:
        model = await self.session.scalar(
            select(IntegrationJobModel)
            .where(
                IntegrationJobModel.id == job_id,
                IntegrationJobModel.locked_by == worker_id,
                IntegrationJobModel.status == IntegrationJobStatus.PROCESSING.value,
                IntegrationJobModel.locked_until >= timestamp,
            )
            .with_for_update()
        )
        if model is None:
            raise RuntimeError(f"Integration job lease lost: {job_id}")
        return model

    async def _owned_inbox(
        self, inbox_id: UUID, worker_id: str, timestamp: datetime
    ) -> IntegrationInboxEventModel:
        model = await self.session.scalar(
            select(IntegrationInboxEventModel)
            .where(
                IntegrationInboxEventModel.id == inbox_id,
                IntegrationInboxEventModel.locked_by == worker_id,
                IntegrationInboxEventModel.processed_at.is_(None),
                IntegrationInboxEventModel.dead_lettered_at.is_(None),
                IntegrationInboxEventModel.locked_until >= timestamp,
            )
            .with_for_update()
        )
        if model is None:
            raise RuntimeError(f"Integration inbox lease lost: {inbox_id}")
        return model

    def _attempt(
        self,
        job_id: UUID,
        attempt_number: int,
        started_at: datetime,
        finished_at: datetime,
        outcome: IntegrationAttemptOutcome,
        duration_ms: int,
        *,
        http_status: int | None = None,
        provider_request_id: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        self.session.add(
            IntegrationJobAttemptModel(
                id=uuid4(),
                job_id=job_id,
                attempt_number=attempt_number,
                started_at=started_at,
                finished_at=finished_at,
                outcome=outcome.value,
                http_status=http_status,
                provider_request_id=provider_request_id,
                duration_ms=duration_ms,
                error_code=error_code,
                error_message=error_message,
            )
        )

    async def _next_attempt_number(self, job_id: UUID) -> int:
        current = await self.session.scalar(
            select(func.max(IntegrationJobAttemptModel.attempt_number)).where(
                IntegrationJobAttemptModel.job_id == job_id
            )
        )
        return int(current or 0) + 1


def _utc(value: datetime | None) -> datetime:
    result = value or datetime.now(UTC)
    if result.utcoffset() is None:
        raise ValueError("Integration timestamps must include a timezone")
    return result.astimezone(UTC)
