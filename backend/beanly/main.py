from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from beanly.api.health import router as health_router
from beanly.api.router import api_v1_router
from beanly.core.config.settings import get_settings
from beanly.core.database.session import engine, session_factory
from beanly.core.exceptions.handlers import register_exception_handlers
from beanly.core.http import RequestContextMiddleware, SecurityHeadersMiddleware
from beanly.core.logging.config import configure_logging
from beanly.core.observability import configure_telemetry, shutdown_telemetry
from beanly.core.rate_limit import RateLimitMiddleware, RedisRateLimiter
from beanly.core.redis import redis_client
from beanly.core.security.audit import SecurityAuditMiddleware

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await redis_client.aclose()
    await engine.dispose()
    shutdown_telemetry()


configure_logging()
app = FastAPI(title="Beanly API", version=settings.app_version, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Organization-ID", "X-Request-ID"],
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
if settings.enforce_https:
    app.add_middleware(HTTPSRedirectMiddleware)
app.add_middleware(
    SecurityAuditMiddleware,
    session_factory=session_factory,
    ip_hash_secret=settings.audit_ip_hash_secret,
    enabled=settings.audit_enabled,
)
app.add_middleware(
    RateLimitMiddleware,
    limiter=RedisRateLimiter(redis_client),
    enabled=settings.rate_limit_enabled,
)
app.add_middleware(SecurityHeadersMiddleware, hsts=settings.environment == "production")
app.add_middleware(RequestContextMiddleware, ip_hash_secret=settings.audit_ip_hash_secret)
register_exception_handlers(app)
app.include_router(health_router)
app.include_router(api_v1_router)
configure_telemetry(settings, app=app, engine=engine)
