import json
import time
from datetime import UTC, datetime

from beanly.core.events.outbox.writer import DomainEventSink
from beanly.modules.integrations.application.ports import (
    IntegrationRepository,
    ProviderRegistryPort,
    SecretCipher,
)
from beanly.modules.integrations.application.source_ports import IntegrationSourcePort
from beanly.modules.integrations.domain.entities import IntegrationJob
from beanly.modules.integrations.domain.enums import IntegrationCapability
from beanly.modules.integrations.domain.events import (
    IntegrationJobDeadLettered,
    IntegrationJobSucceeded,
)
from beanly.modules.integrations.domain.exceptions import PermanentProviderError


class IntegrationJobService:
    def __init__(
        self,
        repository: IntegrationRepository,
        source: IntegrationSourcePort,
        registry: ProviderRegistryPort,
        cipher: SecretCipher,
        sink: DomainEventSink,
        *,
        max_attempts: int,
    ) -> None:
        self.repository = repository
        self.source = source
        self.registry = registry
        self.cipher = cipher
        self.sink = sink
        self.max_attempts = max_attempts

    async def execute(self, job: IntegrationJob, worker_id: str) -> None:
        started_at = datetime.now(UTC)
        started = time.monotonic()
        try:
            connection = await self.repository.get_connection_by_id(job.connection_id)
            if connection is None or connection.organization_id != job.organization_id:
                raise PermanentProviderError(
                    "Integration connection not found", code="CONNECTION_NOT_FOUND"
                )
            if connection.status.value not in {"ACTIVE", "DEGRADED"}:
                raise PermanentProviderError(
                    "Integration connection is not active", code="CONNECTION_INACTIVE"
                )
            credentials = self._credentials(connection.credentials_ciphertext)
            adapter = self.registry.adapter(connection.provider_code)
            if (
                job.capability is not IntegrationCapability.FISCAL
                or job.job_type != "FISCALIZE_PAYMENT"
            ):
                raise PermanentProviderError(
                    "Unsupported integration job", code="UNSUPPORTED_JOB"
                )
            command = await self.source.fiscal_sale(job.organization_id, job.source_id)
            result = await adapter.fiscalize_sale(
                command,
                credentials=credentials,
                idempotency_key=job.idempotency_key,
            )
        except Exception as exc:
            temporary = not isinstance(exc, (PermanentProviderError, ValueError))
            await self.repository.mark_job_failed(
                job.id,
                worker_id,
                exc,
                self.max_attempts,
                temporary=temporary,
                started_at=started_at,
                duration_ms=max(0, int((time.monotonic() - started) * 1000)),
            )
            refreshed = await self.repository.get_job(job.organization_id, job.id)
            if refreshed and refreshed.status.value == "DEAD":
                await self.sink.stage(IntegrationJobDeadLettered(job.id, job.organization_id))
        else:
            await self.repository.mark_job_succeeded(
                job.id,
                worker_id,
                external_id=result.external_receipt_id,
                provider_request_id=result.provider_request_id,
                started_at=started_at,
                duration_ms=max(0, int((time.monotonic() - started) * 1000)),
            )
            await self.sink.stage(IntegrationJobSucceeded(job.id, job.organization_id))
        await self.repository.commit()

    def _credentials(self, ciphertext: str | None) -> dict[str, object]:
        if ciphertext is None:
            return {}
        try:
            value = json.loads(self.cipher.decrypt(ciphertext))
        except Exception as exc:
            raise PermanentProviderError(
                "Stored credentials are invalid", code="INVALID_CREDENTIALS"
            ) from exc
        if not isinstance(value, dict):
            raise PermanentProviderError(
                "Stored credentials are invalid", code="INVALID_CREDENTIALS"
            )
        return value
