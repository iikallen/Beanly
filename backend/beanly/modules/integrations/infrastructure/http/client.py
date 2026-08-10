from uuid import UUID

import httpx

from beanly.core.config.settings import Settings


class ProviderHttpClientFactory:
    """Provider adapters own fixed base URLs; connection config never reaches this factory."""

    def __init__(self, settings: Settings) -> None:
        timeout = httpx.Timeout(
            connect=settings.integration_http_connect_timeout_seconds,
            read=settings.integration_http_read_timeout_seconds,
            write=settings.integration_http_read_timeout_seconds,
            pool=settings.integration_http_connect_timeout_seconds,
        )
        limits = httpx.Limits(
            max_connections=settings.integration_http_max_connections,
            max_keepalive_connections=settings.integration_http_max_connections,
        )
        self._options = {"timeout": timeout, "limits": limits}

    def create(
        self,
        *,
        base_url: str,
        organization_id: UUID | None = None,
        job_id: UUID | None = None,
        request_id: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.AsyncClient:
        correlation = dict(headers or {})
        if organization_id:
            correlation["X-Beanly-Organization-ID"] = str(organization_id)
        if job_id:
            correlation["X-Beanly-Job-ID"] = str(job_id)
        if request_id:
            correlation["X-Beanly-Request-ID"] = request_id
        return httpx.AsyncClient(
            base_url=base_url,
            headers=correlation,
            **self._options,
        )
