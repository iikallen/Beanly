from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from beanly.modules.fiscal.application.nkt_dto import NktProduct
from beanly.modules.fiscal.application.nkt_service import NktService
from beanly.modules.fiscal.domain.exceptions import NktInvalidResponse, NktRateLimited
from beanly.modules.fiscal.infrastructure.nkt.cache_repository import NktCacheRepository
from beanly.modules.fiscal.infrastructure.nkt.client import NktHttpClient

GTIN = "0954353542345"
NTIN = "0200120931509"


def _payload(*, external_id: int = 18, ntin: str = NTIN) -> dict[str, object]:
    return {
        "id": external_id,
        "gtin": GTIN,
        "ntin": ntin,
        "nameKk": "Кофе",
        "nameRu": "Кофе",
        "categoryAncestors": [{"level": 1, "code": "1024", "nameRu": "Напитки"}],
        "updatedDate": "2026-08-11T12:00:00Z",
    }


@pytest.mark.anyio
async def test_nkt_client_uses_only_documented_v2_tin_lookup_and_preserves_gtin_ambiguity() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json=[
                _payload(),
                _payload(external_id=19, ntin="0200120931516"),
            ],
        )

    client = NktHttpClient("nkt-test-secret", transport=httpx.MockTransport(handler))
    products = await client.lookup(GTIN)

    assert [product.ntin for product in products] == [NTIN, "0200120931516"]
    assert len(requests) == 1
    assert requests[0].url.path == f"/gwp/portal/api/v2/products/{GTIN}"
    assert requests[0].headers["X-API-KEY"] == "nkt-test-secret"
    assert "/search/" not in requests[0].url.path


@pytest.mark.anyio
async def test_nkt_client_validates_13_ascii_digits_before_network_and_classifies_429() -> None:
    requests = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(429, headers={"retry-after": "10"})

    client = NktHttpClient("nkt-secret", transport=httpx.MockTransport(handler))
    for invalid in ("123", "ABCDEFGHIJKLM", "１２３４５６７８９０１２３"):
        with pytest.raises(NktInvalidResponse, match="13 digits"):
            await client.lookup(invalid)
    assert requests == 0

    with pytest.raises(NktRateLimited, match="rate limit") as failure:
        await client.lookup(NTIN)
    assert requests == 1
    assert "nkt-secret" not in str(failure.value)


class _Cache:
    def __init__(self, values: tuple[NktProduct, ...] = ()) -> None:
        self.values = values
        self.upserts: list[tuple[NktProduct, ...]] = []
        self.commits = 0
        self.rollbacks = 0

    async def search(self, query: str, *, limit: int) -> tuple[NktProduct, ...]:
        del query
        return self.values[:limit]

    async def by_ntin(self, ntin: str) -> NktProduct | None:
        return next((value for value in self.values if value.ntin == ntin), None)

    async def by_gtin(self, gtin: str) -> tuple[NktProduct, ...]:
        return tuple(value for value in self.values if gtin in value.gtins)

    async def upsert(self, products: tuple[NktProduct, ...]) -> None:
        self.upserts.append(products)
        self.values = products

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class _Lookup:
    def __init__(self, values: tuple[NktProduct, ...]) -> None:
        self.values = values
        self.calls: list[str] = []

    async def lookup(self, tin: str) -> tuple[NktProduct, ...]:
        self.calls.append(tin)
        return self.values


def _product(*, external_id: str = "18", ntin: str = NTIN) -> NktProduct:
    return NktProduct(
        external_id=external_id,
        ntin=ntin,
        gtins=(GTIN,),
        name_ru="Кофе",
        name_kk="Кофе",
        category_code="1024",
        unit_code=None,
        status="UNKNOWN",
        updated_at=datetime(2026, 8, 11, 12, tzinfo=UTC),
        payload_hash="0" * 64,
    )


@pytest.mark.anyio
async def test_nkt_free_text_search_is_cache_only_and_ntin_must_be_unique() -> None:
    cache = _Cache((_product(),))
    lookup = _Lookup((_product(),))
    service = NktService(cache, lookup, SimpleNamespace())  # type: ignore[arg-type]

    assert await service.search("coffee", limit=10) == cache.values
    assert lookup.calls == []
    assert await service.by_ntin(NTIN) == cache.values[0]
    assert lookup.calls == []

    ambiguous = (
        _product(),
        _product(external_id="19"),
    )
    uncached = NktService(_Cache(), _Lookup(ambiguous), SimpleNamespace())  # type: ignore[arg-type]
    with pytest.raises(NktInvalidResponse, match="multiple"):
        await uncached.by_ntin(NTIN)


@pytest.mark.anyio
async def test_nkt_lookup_is_committed_and_next_session_is_a_cache_hit(app_client) -> None:
    _, sessions = app_client
    lookup = _Lookup((_product(),))
    async with sessions() as session:
        first = NktService(
            NktCacheRepository(session), lookup, SimpleNamespace()  # type: ignore[arg-type]
        )
        assert (await first.by_ntin(NTIN)).ntin == NTIN

    async with sessions() as session:
        second = NktService(
            NktCacheRepository(session), lookup, SimpleNamespace()  # type: ignore[arg-type]
        )
        assert (await second.by_ntin(NTIN)).ntin == NTIN

    assert lookup.calls == [NTIN]


def test_nkt_adapter_contains_no_undocumented_free_text_endpoint() -> None:
    source = Path("beanly/modules/fiscal/infrastructure/nkt/client.py").read_text(
        encoding="utf-8"
    )
    assert "/search/api/" not in source
    assert "https://nationalcatalog.kz" in source
