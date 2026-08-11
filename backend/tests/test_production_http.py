from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from beanly.core.exceptions.handlers import register_exception_handlers
from beanly.core.http.middleware import RequestContextMiddleware, SecurityHeadersMiddleware
from beanly.core.logging.context import organization_id_var, request_id_var


def _http_app() -> FastAPI:
    app = FastAPI()

    @app.get("/context")
    async def context() -> dict[str, str | None]:
        return {
            "request_id": request_id_var.get(),
            "organization_id": organization_id_var.get(),
        }

    app.add_middleware(SecurityHeadersMiddleware, hsts=True)
    app.add_middleware(RequestContextMiddleware)
    return app


@pytest.mark.anyio
async def test_valid_request_id_is_propagated_with_security_headers() -> None:
    request_id = uuid4()
    organization_id = uuid4()
    async with AsyncClient(
        transport=ASGITransport(app=_http_app()),
        base_url="https://test",
    ) as client:
        response = await client.get(
            "/context",
            headers={
                "X-Request-ID": str(request_id),
                "X-Organization-ID": str(organization_id),
            },
        )

    assert response.status_code == 200
    assert response.headers["x-request-id"] == str(request_id)
    assert response.json() == {
        "request_id": str(request_id),
        "organization_id": str(organization_id),
    }
    assert response.headers["strict-transport-security"].startswith("max-age=")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "camera=()" in response.headers["permissions-policy"]


@pytest.mark.anyio
async def test_invalid_request_and_organization_ids_are_not_trusted() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=_http_app()),
        base_url="https://test",
    ) as client:
        response = await client.get(
            "/context",
            headers={"X-Request-ID": "attacker-value", "X-Organization-ID": "not-a-uuid"},
        )

    generated = response.headers["x-request-id"]
    UUID(generated)
    assert generated != "attacker-value"
    assert response.json() == {"request_id": generated, "organization_id": None}
    assert request_id_var.get() is None
    assert organization_id_var.get() is None


@pytest.mark.anyio
async def test_unhandled_500_response_is_safe_and_correlated() -> None:
    app = FastAPI(debug=False)

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("SELECT password FROM users at C:/private/source.py")

    register_exception_handlers(app)
    app.add_middleware(RequestContextMiddleware)
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="https://test",
    ) as client:
        response = await client.get("/boom")

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Internal server error",
        "request_id": response.headers["x-request-id"],
    }
    assert "SELECT" not in response.text
    assert "private/source.py" not in response.text
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
