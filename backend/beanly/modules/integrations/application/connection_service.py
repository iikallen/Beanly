import json
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from beanly.core.events.outbox.writer import DomainEventSink
from beanly.modules.integrations.application.ports import (
    IntegrationRepository,
    ProviderRegistryPort,
    SecretCipher,
)
from beanly.modules.integrations.domain.entities import (
    IntegrationConnection,
    IntegrationLocationBinding,
)
from beanly.modules.integrations.domain.enums import (
    IntegrationAuthType,
    IntegrationCapability,
    IntegrationConnectionStatus,
)
from beanly.modules.integrations.domain.events import (
    IntegrationConnectionActivated,
    IntegrationConnectionCreated,
    IntegrationConnectionDegraded,
    IntegrationConnectionRevoked,
)
from beanly.modules.integrations.domain.exceptions import (
    IntegrationError,
    IntegrationNotFound,
    PermanentProviderError,
)
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.organizations.domain.exceptions import OrganizationAccessDenied

_SECRET_CONFIG_KEYS = frozenset(
    {"api_key", "access_token", "refresh_token", "client_secret", "webhook_secret"}
)


class IntegrationConnectionService:
    def __init__(
        self,
        repository: IntegrationRepository,
        organizations: OrganizationService,
        registry: ProviderRegistryPort,
        cipher: SecretCipher,
        sink: DomainEventSink,
    ) -> None:
        self.repository = repository
        self.organizations = organizations
        self.registry = registry
        self.cipher = cipher
        self.sink = sink

    async def create(
        self,
        context: TenantContext,
        provider_code: str,
        display_name: str,
        config: dict[str, object],
        credentials: dict[str, object] | None,
    ) -> IntegrationConnection:
        descriptor = self.registry.descriptor(provider_code)
        _validate_config(config)
        if descriptor.auth_type is IntegrationAuthType.API_KEY and not credentials:
            raise IntegrationError("Credentials are required")
        now = datetime.now(UTC)
        encrypted = _encrypt_credentials(self.cipher, credentials)
        value = IntegrationConnection(
            id=uuid4(),
            organization_id=context.organization_id,
            provider_code=provider_code,
            display_name=display_name.strip(),
            status=IntegrationConnectionStatus.PENDING,
            auth_type=descriptor.auth_type,
            config=config,
            credentials_ciphertext=encrypted,
            credentials_key_version=1 if encrypted else None,
            external_account_id=None,
            connected_at=None,
            last_health_check_at=None,
            last_success_at=None,
            last_error_code=None,
            last_error_message=None,
            created_by=context.user_id,
            created_at=now,
            updated_at=now,
        )
        result = await self.repository.add_connection(value)
        await self.sink.stage(IntegrationConnectionCreated(result.id, result.organization_id))
        await self.repository.commit()
        return result

    async def list(self, context: TenantContext) -> list[IntegrationConnection]:
        return await self.repository.list_connections(context.organization_id)

    async def get(
        self, context: TenantContext, connection_id: UUID
    ) -> IntegrationConnection:
        value = await self.repository.get_connection(context.organization_id, connection_id)
        if value is None:
            raise IntegrationNotFound("Integration connection not found")
        return value

    async def update(
        self,
        context: TenantContext,
        connection_id: UUID,
        *,
        display_name: str | None,
        config: dict[str, object] | None,
        credentials: dict[str, object] | None,
    ) -> IntegrationConnection:
        current = await self.get(context, connection_id)
        if config is not None:
            _validate_config(config)
        encrypted = (
            _encrypt_credentials(self.cipher, credentials)
            if credentials is not None
            else current.credentials_ciphertext
        )
        value = replace(
            current,
            display_name=display_name.strip() if display_name is not None else current.display_name,
            config=config if config is not None else current.config,
            credentials_ciphertext=encrypted,
            credentials_key_version=1 if encrypted else None,
            status=(
                IntegrationConnectionStatus.PENDING
                if credentials is not None
                else current.status
            ),
            updated_at=datetime.now(UTC),
        )
        result = await self.repository.update_connection(value)
        await self.repository.commit()
        return result

    async def test(
        self, context: TenantContext, connection_id: UUID
    ) -> IntegrationConnection:
        current = await self.get(context, connection_id)
        adapter = self.registry.adapter(current.provider_code)
        credentials = self.credentials(current)
        now = datetime.now(UTC)
        try:
            await adapter.health_check(credentials)
        except PermanentProviderError as exc:
            code = str(getattr(exc, "code", type(exc).__name__))[:100]
            value = replace(
                current,
                status=IntegrationConnectionStatus.DEGRADED,
                last_health_check_at=now,
                last_error_code=code,
                last_error_message=exc.public_message[:500],
                updated_at=now,
            )
        except Exception:
            value = replace(
                current,
                status=IntegrationConnectionStatus.DEGRADED,
                last_health_check_at=now,
                last_error_code="PROVIDER_UNAVAILABLE",
                last_error_message="Provider health check failed",
                updated_at=now,
            )
        else:
            value = replace(
                current,
                status=IntegrationConnectionStatus.ACTIVE,
                connected_at=current.connected_at or now,
                last_health_check_at=now,
                last_success_at=now,
                last_error_code=None,
                last_error_message=None,
                updated_at=now,
            )
        result = await self.repository.update_connection(value)
        await self.sink.stage(
            IntegrationConnectionActivated(result.id, result.organization_id)
            if result.status is IntegrationConnectionStatus.ACTIVE
            else IntegrationConnectionDegraded(result.id, result.organization_id)
        )
        await self.repository.commit()
        return result

    async def disconnect(
        self, context: TenantContext, connection_id: UUID
    ) -> IntegrationConnection:
        current = await self.get(context, connection_id)
        value = replace(
            current,
            status=IntegrationConnectionStatus.REVOKED,
            credentials_ciphertext=None,
            credentials_key_version=None,
            updated_at=datetime.now(UTC),
        )
        result = await self.repository.update_connection(value)
        await self.sink.stage(IntegrationConnectionRevoked(result.id, result.organization_id))
        await self.repository.commit()
        return result

    async def bind_location(
        self,
        context: TenantContext,
        connection_id: UUID,
        location_id: UUID,
        capability: IntegrationCapability,
        external_location_id: str | None,
        settings: dict[str, object],
        is_active: bool,
    ) -> IntegrationLocationBinding:
        connection = await self.get(context, connection_id)
        descriptor = self.registry.descriptor(connection.provider_code)
        if capability not in descriptor.capabilities:
            raise IntegrationError("Provider does not support this capability")
        _validate_config(settings)
        if (
            await self.organizations.repository.get_location(
                context.organization_id, location_id
            )
            is None
        ):
            raise IntegrationNotFound("Location not found")
        try:
            await self.organizations.ensure_location_access(context, location_id)
        except OrganizationAccessDenied as exc:
            raise IntegrationNotFound("Location not found") from exc
        now = datetime.now(UTC)
        result = await self.repository.upsert_binding(
            IntegrationLocationBinding(
                id=uuid4(),
                organization_id=context.organization_id,
                connection_id=connection_id,
                location_id=location_id,
                capability=capability,
                external_location_id=external_location_id,
                settings=settings,
                is_active=is_active,
                created_at=now,
                updated_at=now,
            )
        )
        await self.repository.commit()
        return result

    async def unbind_location(
        self,
        context: TenantContext,
        connection_id: UUID,
        location_id: UUID,
        capability: IntegrationCapability,
    ) -> None:
        await self.get(context, connection_id)
        if (
            await self.organizations.repository.get_location(
                context.organization_id, location_id
            )
            is None
        ):
            raise IntegrationNotFound("Location not found")
        try:
            await self.organizations.ensure_location_access(context, location_id)
        except OrganizationAccessDenied as exc:
            raise IntegrationNotFound("Location not found") from exc
        if not await self.repository.delete_binding(
            context.organization_id, connection_id, location_id, capability
        ):
            raise IntegrationNotFound("Integration location binding not found")
        await self.repository.commit()

    def credentials(self, connection: IntegrationConnection) -> dict[str, object]:
        if connection.credentials_ciphertext is None:
            return {}
        try:
            value = json.loads(self.cipher.decrypt(connection.credentials_ciphertext))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise PermanentProviderError(
                "Stored credentials are invalid", code="INVALID_CREDENTIALS"
            ) from exc
        if not isinstance(value, dict):
            raise PermanentProviderError(
                "Stored credentials are invalid", code="INVALID_CREDENTIALS"
            )
        return value


def _encrypt_credentials(
    cipher: SecretCipher, credentials: dict[str, object] | None
) -> str | None:
    if credentials is None:
        return None
    return cipher.encrypt(
        json.dumps(credentials, separators=(",", ":"), sort_keys=True).encode()
    )


def _validate_config(config: dict[str, object]) -> None:
    def walk(value: object) -> None:
        if isinstance(value, dict):
            for raw_key, child in value.items():
                key = str(raw_key).lower()
                if key in _SECRET_CONFIG_KEYS:
                    raise IntegrationError("Secrets must be stored as credentials")
                if key in {"provider_url", "base_url", "api_url"}:
                    raise IntegrationError("Provider URLs are fixed by the adapter")
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(config)
