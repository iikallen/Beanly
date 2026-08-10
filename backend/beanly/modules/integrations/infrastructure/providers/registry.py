from beanly.core.config.settings import Settings
from beanly.modules.integrations.application.dto import ProviderDescriptor
from beanly.modules.integrations.domain.enums import (
    IntegrationAuthType,
    IntegrationCapability,
)
from beanly.modules.integrations.domain.exceptions import UnknownProvider
from beanly.modules.integrations.infrastructure.providers.base import ProviderAdapter
from beanly.modules.integrations.infrastructure.providers.mock import MockFiscalProvider


class ProviderRegistry:
    def __init__(self) -> None:
        self._entries: dict[str, tuple[ProviderDescriptor, ProviderAdapter]] = {}

    def register(self, descriptor: ProviderDescriptor, adapter: ProviderAdapter) -> None:
        if descriptor.code in self._entries:
            raise ValueError(f"Provider already registered: {descriptor.code}")
        self._entries[descriptor.code] = descriptor, adapter

    def descriptors(self) -> tuple[ProviderDescriptor, ...]:
        return tuple(value[0] for value in self._entries.values())

    def descriptor(self, code: str) -> ProviderDescriptor:
        try:
            return self._entries[code][0]
        except KeyError as exc:
            raise UnknownProvider(f"Unknown provider: {code}") from exc

    def adapter(self, code: str) -> ProviderAdapter:
        try:
            return self._entries[code][1]
        except KeyError as exc:
            raise UnknownProvider(f"Unknown provider: {code}") from exc


def build_provider_registry(settings: Settings) -> ProviderRegistry:
    registry = ProviderRegistry()
    if settings.environment in {"development", "test"}:
        registry.register(
            ProviderDescriptor(
                code="mock_fiscal",
                name="Mock Fiscal",
                capabilities=frozenset({IntegrationCapability.FISCAL}),
                auth_type=IntegrationAuthType.API_KEY,
                supports_webhooks=True,
                supports_health_check=True,
                location_scoped=True,
            ),
            MockFiscalProvider(),
        )
    return registry
