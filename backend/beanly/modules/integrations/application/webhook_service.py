import hashlib
import json
from uuid import UUID

from beanly.modules.integrations.application.ports import (
    IntegrationRepository,
    ProviderRegistryPort,
    SecretCipher,
)
from beanly.modules.integrations.domain.exceptions import IntegrationNotFound


class IntegrationWebhookService:
    def __init__(
        self,
        repository: IntegrationRepository,
        registry: ProviderRegistryPort,
        cipher: SecretCipher,
    ) -> None:
        self.repository = repository
        self.registry = registry
        self.cipher = cipher

    async def receive(
        self,
        provider_code: str,
        connection_id: UUID,
        raw_body: bytes,
        headers: dict[str, str],
    ) -> UUID:
        connection = await self.repository.get_connection_by_id(connection_id)
        if connection is None or connection.provider_code != provider_code:
            raise IntegrationNotFound("Integration connection not found")
        adapter = self.registry.adapter(provider_code)
        credentials = self._credentials(connection.credentials_ciphertext)
        event = adapter.verify_webhook(raw_body, headers, credentials)
        inbox_id = await self.repository.add_inbox_event(
            connection, event, hashlib.sha256(raw_body).hexdigest()
        )
        await self.repository.commit()
        return inbox_id

    def _credentials(self, ciphertext: str | None) -> dict[str, object]:
        if ciphertext is None:
            return {}
        value = json.loads(self.cipher.decrypt(ciphertext))
        if not isinstance(value, dict):
            raise ValueError("Stored credentials are invalid")
        return value
