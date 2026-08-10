import hashlib
import hmac
import logging
import time
from uuid import UUID, uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from beanly.core.logging.context import reset_request_context, set_request_context
from beanly.core.observability.metrics import metrics

logger = logging.getLogger("beanly.http")


def _request_id(headers: Headers) -> str:
    value = headers.get("x-request-id")
    if value:
        try:
            return str(UUID(value))
        except ValueError:
            pass
    return str(uuid4())


def _organization_id(headers: Headers) -> str | None:
    value = headers.get("x-organization-id")
    if value:
        try:
            return str(UUID(value))
        except ValueError:
            pass
    return None


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp, *, ip_hash_secret: str = "") -> None:
        self.app = app
        self.ip_hash_secret = ip_hash_secret.encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        request_id = _request_id(headers)
        scope.setdefault("state", {})["request_id"] = request_id
        client = scope.get("client")
        ip_hash = (
            hmac.new(self.ip_hash_secret, str(client[0]).encode(), hashlib.sha256).hexdigest()
            if client and self.ip_hash_secret
            else None
        )
        tokens = set_request_context(request_id, _organization_id(headers), ip_hash)
        started = time.monotonic()
        status_code = 500

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                response_headers = MutableHeaders(scope=message)
                response_headers["X-Request-ID"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            duration_ms = max(0, int((time.monotonic() - started) * 1000))
            route = getattr(scope.get("route"), "path", scope["path"])
            metrics.record_http(scope["method"], route, status_code, duration_ms)
            logger.info(
                "HTTP request completed",
                extra={"status": status_code, "duration_ms": duration_ms},
            )
            reset_request_context(tokens)


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, *, hsts: bool = False) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Content-Type-Options"] = "nosniff"
                headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
                headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
                if self.hsts:
                    headers["Strict-Transport-Security"] = (
                        "max-age=31536000; includeSubDomains"
                    )
            await send(message)

        await self.app(scope, receive, send_with_headers)
