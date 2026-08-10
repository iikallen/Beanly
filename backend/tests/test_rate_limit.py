from collections import defaultdict
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from redis.exceptions import RedisError
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from beanly.core.http.middleware import RequestContextMiddleware
from beanly.core.rate_limit.limiter import RateLimitDecision, RedisRateLimiter
from beanly.core.rate_limit.middleware import RateLimitMiddleware


class _SharedRedis:
    def __init__(self) -> None:
        self.counts: defaultdict[str, int] = defaultdict(int)
        self.keys: list[str] = []

    async def eval(self, _script: str, _key_count: int, key: str, ttl: int) -> list[int]:
        self.keys.append(key)
        self.counts[key] += 1
        return [self.counts[key], ttl]


class _DenyLimiter:
    async def check(self, *_args: object, **_kwargs: object) -> RateLimitDecision:
        return RateLimitDecision(False, 17, 0)


class _UnavailableLimiter:
    async def check(self, *_args: object, **_kwargs: object) -> RateLimitDecision:
        raise RedisError("redis unavailable")


async def _ok(_request: object) -> JSONResponse:
    return JSONResponse({"status": "ok"})


def _app(limiter: object) -> Starlette:
    app = Starlette(
        routes=[
            Route("/api/v1/auth/login", _ok, methods=["POST"]),
            Route(
                "/api/v1/integrations/webhooks/{provider}/{connection}",
                _ok,
                methods=["POST"],
            ),
        ]
    )
    app.add_middleware(RateLimitMiddleware, limiter=limiter, enabled=True)
    app.add_middleware(RequestContextMiddleware)
    return app


@pytest.mark.anyio
async def test_rate_limit_counter_is_shared_between_api_instances() -> None:
    redis = _SharedRedis()
    instance_a = RedisRateLimiter(redis)  # type: ignore[arg-type]
    instance_b = RedisRateLimiter(redis)  # type: ignore[arg-type]

    assert (await instance_a.check("login", "203.0.113.8", limit=2, window_seconds=60)).allowed
    assert (await instance_b.check("login", "203.0.113.8", limit=2, window_seconds=60)).allowed
    denied = await instance_a.check("login", "203.0.113.8", limit=2, window_seconds=60)

    assert not denied.allowed
    assert denied.retry_after == 60
    assert len(set(redis.keys)) == 1
    assert "203.0.113.8" not in redis.keys[0]


@pytest.mark.anyio
async def test_rate_limit_429_has_retry_after_and_request_id() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=_app(_DenyLimiter())),
        base_url="http://test",
    ) as client:
        response = await client.post("/api/v1/auth/login")

    assert response.status_code == 429
    assert response.headers["retry-after"] == "17"
    assert response.json()["detail"] == "Too many requests"
    assert response.json()["request_id"] == response.headers["x-request-id"]
    UUID(response.headers["x-request-id"])


@pytest.mark.anyio
async def test_sensitive_rate_limit_fails_closed_but_webhook_fails_open() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=_app(_UnavailableLimiter())),
        base_url="http://test",
    ) as client:
        login = await client.post("/api/v1/auth/login")
        webhook = await client.post("/api/v1/integrations/webhooks/mock/connection")

    assert login.status_code == 503
    assert login.json()["detail"] == "Rate limit service unavailable"
    assert login.json()["request_id"] == login.headers["x-request-id"]
    assert webhook.status_code == 200
