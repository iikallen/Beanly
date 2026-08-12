import asyncio

from beanly.modules.onboarding.application.dto import CanonicalImportDraft
from beanly.modules.onboarding.infrastructure.ai.media import (
    PublicMenuFetcher,
    prepare_file_isolated,
)
from beanly.modules.onboarding.infrastructure.ai.ollama_client import OllamaMenuClient
from beanly.modules.onboarding.infrastructure.ai.schemas import to_canonical_draft


class LocalVisionExtractionAdapter:
    def __init__(
        self,
        client: OllamaMenuClient,
        *,
        confidence_threshold: float,
        fetcher: PublicMenuFetcher | None = None,
    ) -> None:
        self.client = client
        self.confidence_threshold = confidence_threshold
        self.fetcher = fetcher or PublicMenuFetcher()

    @property
    def available(self) -> bool:
        return True

    async def extract_file(
        self, content: bytes, media_type: str, file_name: str
    ) -> CanonicalImportDraft:
        prepared = await asyncio.to_thread(
            prepare_file_isolated, content, media_type, file_name
        )
        document = await self.client.extract(text=prepared.text, images=prepared.images)
        return to_canonical_draft(
            document,
            confidence_threshold=self.confidence_threshold,
        )

    async def extract_url(self, public_url: str) -> CanonicalImportDraft:
        downloaded = await self.fetcher.fetch(public_url)
        return await self.extract_file(
            downloaded.content,
            downloaded.media_type,
            downloaded.file_name,
        )
