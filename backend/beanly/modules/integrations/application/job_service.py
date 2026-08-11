import json
import time
from datetime import UTC, datetime

from beanly.core.events.outbox.writer import DomainEventSink
from beanly.core.observability import metrics, traced
from beanly.modules.integrations.application.ports import (
    FiscalReceiptProjectionPort,
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
from beanly.modules.integrations.domain.exceptions import (
    PermanentProviderError,
    ProviderOutcomeUnknown,
)


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
        receipts: FiscalReceiptProjectionPort | None = None,
    ) -> None:
        self.repository = repository
        self.source = source
        self.registry = registry
        self.cipher = cipher
        self.sink = sink
        self.max_attempts = max_attempts
        self.receipts = receipts

    async def execute(self, job: IntegrationJob, worker_id: str) -> None:
        with traced(
            "integration.job.execute",
            job_id=str(job.id),
            organization_id=str(job.organization_id),
        ):
            await self._execute(job, worker_id)

    async def _execute(self, job: IntegrationJob, worker_id: str) -> None:
        started_at = datetime.now(UTC)
        started = time.monotonic()
        provider_code = "unknown"
        try:
            connection = await self.repository.get_connection_by_id(job.connection_id)
            if connection is None or connection.organization_id != job.organization_id:
                raise PermanentProviderError(
                    "Integration connection not found", code="CONNECTION_NOT_FOUND"
                )
            provider_code = connection.provider_code
            if connection.status.value not in {"ACTIVE", "DEGRADED"}:
                raise PermanentProviderError(
                    "Integration connection is not active", code="CONNECTION_INACTIVE"
                )
            credentials = self._credentials(connection.credentials_ciphertext)
            adapter = self.registry.adapter(connection.provider_code)
            if job.capability is not IntegrationCapability.FISCAL or job.job_type not in {
                "FISCALIZE_PAYMENT",
                "FISCALIZE_REFUND",
            }:
                raise PermanentProviderError("Unsupported integration job", code="UNSUPPORTED_JOB")
            command = (
                await self.source.fiscal_sale(job.organization_id, job.source_id)
                if job.job_type == "FISCALIZE_PAYMENT"
                else await self.source.fiscal_refund(
                    job.organization_id, job.source_id, job.connection_id
                )
            )
            source_type = "SALE" if job.job_type == "FISCALIZE_PAYMENT" else "REFUND"
            if self.receipts:
                await self.receipts.mark_receipt_processing(
                    job.organization_id, source_type, job.source_id
                )
            with traced("provider.request", provider_code=provider_code):
                method = (
                    adapter.fiscalize_sale
                    if job.job_type == "FISCALIZE_PAYMENT"
                    else adapter.fiscalize_refund
                )
                result = await method(
                    command, credentials=credentials, idempotency_key=job.idempotency_key
                )
        except Exception as exc:
            unknown = isinstance(exc, ProviderOutcomeUnknown)
            temporary = not isinstance(
                exc, (PermanentProviderError, ProviderOutcomeUnknown, ValueError)
            )
            metrics.integration_provider_errors.add(
                1,
                {"provider.code": provider_code, "temporary": temporary},
            )
            await self.repository.mark_job_failed(
                job.id,
                worker_id,
                exc,
                self.max_attempts,
                temporary=temporary,
                started_at=started_at,
                duration_ms=max(0, int((time.monotonic() - started) * 1000)),
            )
            if self.receipts and job.job_type in {
                "FISCALIZE_PAYMENT",
                "FISCALIZE_REFUND",
            }:
                await self.receipts.mark_receipt_failed(
                    job.organization_id,
                    "SALE" if job.job_type == "FISCALIZE_PAYMENT" else "REFUND",
                    job.source_id,
                    exc,
                    temporary=temporary,
                    unknown=unknown,
                )
            refreshed = await self.repository.get_job(job.organization_id, job.id)
            if refreshed and refreshed.status.value == "DEAD":
                await self.sink.stage(IntegrationJobDeadLettered(job.id, job.organization_id))
            elif temporary:
                metrics.integration_retries.add(1, {"provider.code": provider_code})
        else:
            with traced("job.complete", job_id=str(job.id)):
                await self.repository.mark_job_succeeded(
                    job.id,
                    worker_id,
                    external_id=result.external_receipt_id,
                    external_number=result.receipt_number,
                    external_url=result.receipt_url,
                    provider_request_id=result.provider_request_id,
                    started_at=started_at,
                    duration_ms=max(0, int((time.monotonic() - started) * 1000)),
                )
                if self.receipts:
                    await self.receipts.mark_receipt_succeeded(
                        job.organization_id,
                        "SALE" if job.job_type == "FISCALIZE_PAYMENT" else "REFUND",
                        job.source_id,
                        result,
                    )
                await self.sink.stage(IntegrationJobSucceeded(job.id, job.organization_id))
        await self.repository.commit()
        metrics.integration_duration.record(
            max(0, int((time.monotonic() - started) * 1000)),
            {"provider.code": provider_code},
        )

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
