from collections.abc import Mapping
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from beanly.modules.integrations.application.dto import (
    FiscalReceiptResult,
    FiscalRefundCommand,
    FiscalSaleCommand,
    NormalizedWebhookEvent,
    OAuthSession,
    ProviderDescriptor,
)
from beanly.modules.integrations.domain.entities import (
    IntegrationConnection,
    IntegrationJob,
    IntegrationLocationBinding,
)
from beanly.modules.integrations.domain.enums import (
    IntegrationCapability,
)


class SecretCipher(Protocol):
    def encrypt(self, value: bytes) -> str: ...

    def decrypt(self, value: str) -> bytes: ...


class PaymentProvider(Protocol):
    async def health_check(self, credentials: Mapping[str, object]) -> None: ...


class FiscalProvider(Protocol):
    async def health_check(self, credentials: Mapping[str, object]) -> None: ...

    async def fiscalize_sale(
        self,
        command: FiscalSaleCommand,
        *,
        credentials: Mapping[str, object],
        idempotency_key: str,
    ) -> FiscalReceiptResult: ...

    async def fiscalize_refund(
        self,
        command: FiscalRefundCommand,
        *,
        credentials: Mapping[str, object],
        idempotency_key: str,
    ) -> FiscalReceiptResult: ...

    def verify_webhook(
        self,
        raw_body: bytes,
        headers: Mapping[str, str],
        credentials: Mapping[str, object],
    ) -> NormalizedWebhookEvent: ...


class DeliveryProvider(Protocol):
    async def health_check(self, credentials: Mapping[str, object]) -> None: ...


class NotificationProvider(Protocol):
    async def health_check(self, credentials: Mapping[str, object]) -> None: ...


class OAuthProvider(Protocol):
    def authorization_url(
        self,
        *,
        redirect_uri: str,
        state: str,
        code_challenge: str,
        code_challenge_method: str,
    ) -> str: ...

    async def exchange_code(
        self, *, code: str, redirect_uri: str, code_verifier: str
    ) -> Mapping[str, object]: ...

    async def refresh_credentials(
        self, credentials: Mapping[str, object]
    ) -> Mapping[str, object]: ...


class ProviderRegistryPort(Protocol):
    def descriptors(self) -> tuple[ProviderDescriptor, ...]: ...

    def descriptor(self, code: str) -> ProviderDescriptor: ...

    def adapter(self, code: str) -> Any: ...


class IntegrationRepository(Protocol):
    async def add_connection(self, value: IntegrationConnection) -> IntegrationConnection: ...

    async def get_connection(
        self, organization_id: UUID, connection_id: UUID
    ) -> IntegrationConnection | None: ...

    async def get_connection_by_id(self, connection_id: UUID) -> IntegrationConnection | None: ...

    async def list_connections(self, organization_id: UUID) -> list[IntegrationConnection]: ...

    async def update_connection(self, value: IntegrationConnection) -> IntegrationConnection: ...

    async def active_connections(
        self,
        organization_id: UUID,
        capability: IntegrationCapability,
        location_id: UUID | None = None,
    ) -> list[tuple[IntegrationConnection, UUID | None]]: ...

    async def upsert_binding(
        self, value: IntegrationLocationBinding
    ) -> IntegrationLocationBinding: ...

    async def delete_binding(
        self,
        organization_id: UUID,
        connection_id: UUID,
        location_id: UUID,
        capability: IntegrationCapability,
    ) -> bool: ...

    async def add_job(self, value: IntegrationJob) -> IntegrationJob: ...

    async def get_job(self, organization_id: UUID, job_id: UUID) -> IntegrationJob | None: ...

    async def mark_job_succeeded(
        self,
        job_id: UUID,
        worker_id: str,
        *,
        external_id: str,
        provider_request_id: str | None,
        started_at: datetime,
        duration_ms: int,
        external_number: str | None = None,
        external_url: str | None = None,
        now: datetime | None = None,
    ) -> None: ...

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
    ) -> None: ...

    async def add_inbox_event(
        self,
        connection: IntegrationConnection,
        event: NormalizedWebhookEvent,
        payload_hash: str,
        now: datetime | None = None,
    ) -> UUID: ...

    async def add_oauth_session(
        self,
        organization_id: UUID,
        user_id: UUID,
        provider_code: str,
        state_hash: str,
        verifier_ciphertext: str,
        redirect_uri: str,
        expires_at: datetime,
    ) -> UUID: ...

    async def consume_oauth_session(
        self, provider_code: str, state_hash: str, now: datetime | None = None
    ) -> OAuthSession | None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
