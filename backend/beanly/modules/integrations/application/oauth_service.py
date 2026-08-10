import base64
import hashlib
import secrets
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from beanly.core.events.outbox.writer import DomainEventSink
from beanly.modules.integrations.application.ports import (
    IntegrationRepository,
    ProviderRegistryPort,
    SecretCipher,
)
from beanly.modules.integrations.domain.entities import IntegrationConnection
from beanly.modules.integrations.domain.enums import (
    IntegrationAuthType,
    IntegrationConnectionStatus,
)
from beanly.modules.integrations.domain.events import (
    IntegrationConnectionActivated,
    IntegrationConnectionCreated,
)
from beanly.modules.integrations.domain.exceptions import OAuthSessionInvalid
from beanly.modules.organizations.domain.entities import TenantContext


@dataclass(frozen=True, slots=True)
class OAuthStart:
    authorization_url: str
    state: str
    code_challenge: str
    code_challenge_method: str = "S256"


class IntegrationOAuthService:
    def __init__(
        self,
        repository: IntegrationRepository,
        registry: ProviderRegistryPort,
        cipher: SecretCipher,
        sink: DomainEventSink,
        public_base_url: str,
    ) -> None:
        self.repository = repository
        self.registry = registry
        self.cipher = cipher
        self.sink = sink
        self.public_base_url = public_base_url.rstrip("/")

    async def start(
        self,
        context: TenantContext,
        provider_code: str,
    ) -> OAuthStart:
        descriptor = self.registry.descriptor(provider_code)
        if descriptor.auth_type is not IntegrationAuthType.OAUTH2:
            raise OAuthSessionInvalid("Provider does not use OAuth2")
        adapter = self.registry.adapter(provider_code)
        redirect_uri = (
            f"{self.public_base_url}/api/v1/integrations/oauth/"
            f"{provider_code}/callback"
        )
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
        await self.repository.add_oauth_session(
            context.organization_id,
            context.user_id,
            provider_code,
            hashlib.sha256(state.encode()).hexdigest(),
            self.cipher.encrypt(verifier.encode()),
            redirect_uri,
            datetime.now(UTC) + timedelta(minutes=10),
        )
        await self.repository.commit()
        if hasattr(adapter, "authorization_url"):
            url = adapter.authorization_url(
                redirect_uri=redirect_uri,
                state=state,
                code_challenge=challenge,
                code_challenge_method="S256",
            )
        else:
            raise OAuthSessionInvalid("Provider OAuth adapter is incomplete")
        return OAuthStart(url, state, challenge)

    async def consume(
        self, provider_code: str, state: str, code: str
    ) -> tuple[UUID, str]:
        state_hash = hashlib.sha256(state.encode()).hexdigest()
        session = await self.repository.consume_oauth_session(provider_code, state_hash)
        if session is None:
            raise OAuthSessionInvalid("OAuth state is invalid, expired, or already used")
        # Commit one-use state before the external token exchange; a failed exchange
        # requires a fresh OAuth start and cannot be replayed concurrently.
        await self.repository.commit()
        adapter = self.registry.adapter(provider_code)
        if not hasattr(adapter, "exchange_code"):
            raise OAuthSessionInvalid("Provider OAuth adapter is incomplete")
        verifier = self.cipher.decrypt(session.code_verifier_ciphertext).decode()
        credentials = await adapter.exchange_code(
            code=code,
            redirect_uri=session.redirect_uri,
            code_verifier=verifier,
        )
        encrypted = self.cipher.encrypt(json_bytes(credentials))
        now = datetime.now(UTC)
        descriptor = self.registry.descriptor(provider_code)
        connection = await self.repository.add_connection(
            IntegrationConnection(
                id=uuid4(),
                organization_id=session.organization_id,
                provider_code=provider_code,
                display_name=descriptor.name,
                status=IntegrationConnectionStatus.ACTIVE,
                auth_type=IntegrationAuthType.OAUTH2,
                config={},
                credentials_ciphertext=encrypted,
                credentials_key_version=1,
                external_account_id=None,
                connected_at=now,
                last_health_check_at=None,
                last_success_at=now,
                last_error_code=None,
                last_error_message=None,
                created_by=session.user_id,
                created_at=now,
                updated_at=now,
            )
        )
        events = (
            IntegrationConnectionCreated(connection.id, connection.organization_id),
            IntegrationConnectionActivated(connection.id, connection.organization_id),
        )
        await self.sink.stage_many(events)
        await self.repository.commit()
        return connection.id, session.redirect_uri

    async def refresh(self, connection: IntegrationConnection) -> IntegrationConnection:
        if connection.auth_type is not IntegrationAuthType.OAUTH2:
            raise OAuthSessionInvalid("Connection does not use OAuth2")
        adapter = self.registry.adapter(connection.provider_code)
        if not hasattr(adapter, "refresh_credentials"):
            raise OAuthSessionInvalid("Provider OAuth adapter is incomplete")
        if connection.credentials_ciphertext is None:
            raise OAuthSessionInvalid("OAuth credentials are missing")
        import json

        current = json.loads(self.cipher.decrypt(connection.credentials_ciphertext))
        refreshed = await adapter.refresh_credentials(current)
        value = replace(
            connection,
            credentials_ciphertext=self.cipher.encrypt(json_bytes(refreshed)),
            credentials_key_version=1,
            updated_at=datetime.now(UTC),
        )
        result = await self.repository.update_connection(value)
        await self.repository.commit()
        return result


def json_bytes(value: object) -> bytes:
    import json

    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode()


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()
