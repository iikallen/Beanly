import hashlib
import json
import logging
import re
from dataclasses import dataclass

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
        rule = next(
            (
                candidate
                for candidate in RULES
                if candidate.method == scope["method"]
                and candidate.path.fullmatch(scope["path"])
            ),
            None,
        )
        if rule is None:
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        identity = _identity(rule, scope, headers)
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


def _identity(rule: RateLimitRule, scope: Scope, headers: Headers) -> str:
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
