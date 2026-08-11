import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from beanly.core.config.settings import get_settings
from beanly.core.exceptions.base import AppError

logger = logging.getLogger(__name__)


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _error_headers(request_id: str | None) -> dict[str, str]:
    headers = {
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    }
    if request_id:
        headers["X-Request-ID"] = request_id
    if get_settings().environment == "production":
        headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return headers


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        request_id = _request_id(request)
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "request_id": request_id},
            headers=_error_headers(request_id),
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = _request_id(request)
        logger.exception("Unhandled API exception", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Internal server error",
                "request_id": request_id,
            },
            headers=_error_headers(request_id),
        )
