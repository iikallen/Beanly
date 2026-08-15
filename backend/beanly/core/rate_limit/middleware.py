import hashlib
import json
import logging
import re
from dataclasses import dataclass
from urllib.parse import parse_qs

from redis.exceptions import RedisError
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from beanly.core.rate_limit.limiter import RedisRateLimiter

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RateLimitRule:
    name: str
    method: str
    path: re.Pattern[str]
    limit: int
    window_seconds: int
    identity: str = "ip"
    fail_closed: bool = True


RULES = (
    RateLimitRule("auth-login", "POST", re.compile(r"^/api/v1/auth/login$"), 10, 60),
    RateLimitRule("auth-register", "POST", re.compile(r"^/api/v1/auth/register$"), 5, 3600),
    RateLimitRule(
        "auth-refresh", "POST", re.compile(r"^/api/v1/auth/refresh$"), 60, 60, "session"
    ),
    RateLimitRule(
        "invitation-accept",
        "POST",
        re.compile(r"^/api/v1/invitations/[^/]+/accept$"),
        20,
        3600,
    ),
    RateLimitRule(
        "oauth-start",
        "POST",
        re.compile(r"^/api/v1/integrations/providers/[^/]+/oauth/start$"),
        20,
        60,
        "authorization",
    ),
    RateLimitRule(
        "integration-test",
        "POST",
        re.compile(r"^/api/v1/integrations/connections/([^/]+)/test$"),
        10,
        60,
        "path",
    ),
    RateLimitRule(
        "integration-retry",
        "POST",
        re.compile(r"^/api/v1/integrations/jobs/[^/]+/retry$"),
        10,
        60,
        "authorization",
    ),
    RateLimitRule(
        "integration-webhook",
        "POST",
        re.compile(r"^/api/v1/integrations/webhooks/([^/]+)/([^/]+)$"),
        600,
        60,
        "path",
        False,
    ),
    RateLimitRule(
        "ai-menu-import",
        "POST",
        re.compile(r"^/api/v1/onboarding/imports/ai(?:/url)?$"),
        5,
        60,
        "authorization",
    ),
    RateLimitRule(
        "public-order-submit-ip",
        "POST",
        re.compile(r"^/api/v1/public/ordering/[^/]+/orders$"),
        10,
        60,
    ),
    RateLimitRule(
        "public-order-submit-slug",
        "POST",
        re.compile(r"^/api/v1/public/ordering/[^/]+/orders$"),
        300,
        60,
        "public_slug",
    ),
    RateLimitRule(
        "public-order-submit-station",
        "POST",
        re.compile(r"^/api/v1/public/ordering/[^/]+/orders$"),
        30,
        60,
        "public_station",
    ),
    RateLimitRule(
        "public-order-cancel",
        "POST",
        re.compile(r"^/api/v1/public/ordering/orders/[^/]+/cancel$"),
        10,
        60,
        "path",
    ),
    RateLimitRule(
        "public-order-quote-ip",
        "POST",
        re.compile(r"^/api/v1/public/ordering/[^/]+/quote$"),
        60,
        60,
    ),
    RateLimitRule(
        "public-order-quote-slug",
        "POST",
        re.compile(r"^/api/v1/public/ordering/[^/]+/quote$"),
        1200,
        60,
        "public_slug",
    ),
    RateLimitRule(
        "public-order-quote-station",
        "POST",
        re.compile(r"^/api/v1/public/ordering/[^/]+/quote$"),
        120,
        60,
        "public_station",
    ),
    RateLimitRule(
        "public-order-read-ip",
        "GET",
        re.compile(r"^/api/v1/public/ordering/.+$"),
        120,
        60,
    ),
    RateLimitRule(
        "public-order-read-slug",
        "GET",
        re.compile(r"^/api/v1/public/ordering/.+$"),
        2400,
        60,
        "public_slug",
    ),
    RateLimitRule(
        "public-order-read-station",
        "GET",
        re.compile(r"^/api/v1/public/ordering/.+$"),
        240,
        60,
        "public_station",
    ),
)


class RateLimitMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        limiter: RedisRateLimiter,
        enabled: bool = True,
    ) -> None:
        self.app = app
        self.limiter = limiter
        self.enabled = enabled

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self.enabled:
            await self.app(scope, receive, send)
            return
        rules = tuple(
            candidate
            for candidate in RULES
            if candidate.method == scope["method"]
            and candidate.path.fullmatch(scope["path"])
        )
        if not rules:
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        for rule in rules:
            identity = _identity(rule, scope, headers)
            if identity is None:
                continue
            try:
                decision = await self.limiter.check(
                    rule.name,
                    identity,
                    limit=rule.limit,
                    window_seconds=rule.window_seconds,
                )
            except RedisError:
                logger.exception("Rate limiter unavailable", extra={"action": rule.name})
                if rule.fail_closed:
                    await _json_response(
                        send,
                        503,
                        {"detail": "Rate limit service unavailable", **_request_id(scope)},
                    )
                    return
            else:
                if not decision.allowed:
                    await _json_response(
                        send,
                        429,
                        {"detail": "Too many requests", **_request_id(scope)},
                        retry_after=decision.retry_after,
                    )
                    return
        await self.app(scope, receive, send)


def _identity(rule: RateLimitRule, scope: Scope, headers: Headers) -> str | None:
    client = scope.get("client")
    ip = str(client[0]) if client else "unknown"
    if rule.identity == "path":
        return f"{ip}:{scope['path']}"
    if rule.identity == "authorization":
        authorization = headers.get("authorization", "anonymous")
        return f"{ip}:{hashlib.sha256(authorization.encode()).hexdigest()}"
    if rule.identity == "session":
        session = headers.get("cookie", "anonymous")
        return f"{ip}:{hashlib.sha256(session.encode()).hexdigest()}"
    if rule.identity == "public_slug":
        match = re.match(r"^/api/v1/public/ordering/([^/]+)", scope["path"])
        if match is None or match.group(1) == "orders":
            return None
        return f"slug:{match.group(1)}"
    if rule.identity == "public_station":
        query = parse_qs(scope.get("query_string", b"").decode("ascii", "ignore"))
        station = query.get("station", [""])[0]
        if not station:
            return None
        return f"station:{hashlib.sha256(station.encode()).hexdigest()}"
    return ip


def _request_id(scope: Scope) -> dict[str, str]:
    value = scope.get("state", {}).get("request_id")
    return {"request_id": value} if value else {}


async def _json_response(
    send: Send,
    status: int,
    payload: dict[str, str],
    *,
    retry_after: int | None = None,
) -> None:
    body = json.dumps(payload, separators=(",", ":")).encode()
    message: Message = {
        "type": "http.response.start",
        "status": status,
        "headers": [(b"content-type", b"application/json")],
    }
    if retry_after is not None:
        headers = MutableHeaders(scope=message)
        headers["Retry-After"] = str(max(1, retry_after))
    await send(message)
    await send({"type": "http.response.body", "body": body})
