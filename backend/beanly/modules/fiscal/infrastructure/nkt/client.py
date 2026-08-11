
import httpx

from beanly.modules.fiscal.application.nkt_dto import NktProduct
from beanly.modules.fiscal.domain.exceptions import (
    NktInvalidResponse,
    NktRateLimited,
    NktUnavailable,
)
from beanly.modules.fiscal.infrastructure.nkt.mapper import map_product

_BASE_URL = "https://nationalcatalog.kz"


class NktHttpClient:
    """Documented NKT portal v2 TIN lookup; no undocumented free-text endpoint."""

    def __init__(
        self,
        api_key: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 10,
    ) -> None:
        if not api_key:
            raise ValueError("NKT API key is required")
        self.api_key = api_key
        self.transport = transport
        self.timeout = timeout

    async def lookup(self, tin: str) -> tuple[NktProduct, ...]:
        _validate_tin(tin)
        try:
            async with httpx.AsyncClient(
                base_url=_BASE_URL,
                transport=self.transport,
                timeout=self.timeout,
                headers={"X-API-KEY": self.api_key},
            ) as client:
                response = await client.get(f"/gwp/portal/api/v2/products/{tin}")
        except httpx.TimeoutException as exc:
            raise NktUnavailable("NKT request timed out") from exc
        except httpx.HTTPError as exc:
            raise NktUnavailable("NKT is unavailable") from exc
        if response.status_code == 429:
            raise NktRateLimited("NKT rate limit exceeded")
        if response.status_code == 404:
            return ()
        if response.status_code >= 500:
            raise NktUnavailable("NKT is unavailable")
        if response.status_code >= 400:
            raise NktInvalidResponse("NKT rejected the lookup")
        try:
            payload = response.json()
        except ValueError as exc:
            raise NktInvalidResponse("NKT returned invalid JSON") from exc
        if not isinstance(payload, list):
            raise NktInvalidResponse("NKT v2 lookup must return a list")
        return tuple(map_product(item) for item in payload)


class UnconfiguredNktClient:
    async def lookup(self, tin: str) -> tuple[NktProduct, ...]:
        _validate_tin(tin)
        raise NktUnavailable("NKT API key is not configured")


def _validate_tin(value: str) -> None:
    if len(value) != 13 or not value.isascii() or not value.isdecimal():
        raise NktInvalidResponse("TIN must contain exactly 13 digits")
