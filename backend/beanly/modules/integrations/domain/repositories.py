from typing import Protocol
from uuid import UUID

from beanly.modules.integrations.domain.entities import IntegrationConnection


class IntegrationConnectionRepository(Protocol):
    async def get_connection(
        self, organization_id: UUID, connection_id: UUID
    ) -> IntegrationConnection | None: ...
