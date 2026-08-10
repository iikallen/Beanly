from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from beanly.core.database.base import Base
from beanly.core.http.middleware import RequestContextMiddleware
from beanly.core.security.audit import (
    SecurityAuditEventModel,
    SecurityAuditMiddleware,
    SecurityAuditRecorder,
    mark_security_event,
)


@pytest_asyncio.fixture
async def audit_sessions(tmp_path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'audit.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield sessions
    await engine.dispose()


@pytest.mark.anyio
async def test_audit_metadata_recursively_rejects_secret_shaped_keys(
    audit_sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with audit_sessions() as session:
        recorder = SecurityAuditRecorder(session)
        for metadata in (
            {"password": "value"},
            {"nested": {"refresh_token": "value"}},
            {"items": [{"webhook_signature": "value"}]},
            {"api_secret": "value"},
            {"full_credentials": {"key": "value"}},
        ):
            with pytest.raises(ValueError, match="cannot contain secrets"):
                await recorder.record(
                    action="INTEGRATION_CREDENTIALS_REPLACED",
                    resource_type="integration_connection",
                    metadata=metadata,
                )
            await session.rollback()


@pytest.mark.anyio
async def test_marked_high_value_action_is_persisted_with_tenant_and_request_context(
    audit_sessions: async_sessionmaker[AsyncSession],
) -> None:
    organization_id = uuid4()
    actor_user_id = uuid4()
    resource_id = uuid4()

    async def update_role(request: Request) -> JSONResponse:
        request.state.actor_user_id = actor_user_id
        mark_security_event(
            request,
            action="MEMBERSHIP_ROLE_CHANGED",
            resource_type="membership",
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            resource_id=resource_id,
            metadata={"role": "MANAGER"},
        )
        return JSONResponse({"status": "ok"})

    app = Starlette(routes=[Route("/change-role", update_role, methods=["POST"])])
    app.add_middleware(
        SecurityAuditMiddleware,
        session_factory=audit_sessions,
        ip_hash_secret="audit-test-secret-at-least-32-characters",
    )
    app.add_middleware(RequestContextMiddleware)
    request_id = uuid4()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/change-role",
            headers={"X-Request-ID": str(request_id)},
        )

    assert response.status_code == 200
    async with audit_sessions() as session:
        events = (await session.scalars(select(SecurityAuditEventModel))).all()
    assert len(events) == 1
    event = events[0]
    assert event.organization_id == organization_id
    assert event.actor_user_id == actor_user_id
    assert event.resource_id == resource_id
    assert event.request_id == request_id
    assert event.action == "MEMBERSHIP_ROLE_CHANGED"
    assert event.event_metadata == {"role": "MANAGER"}
    assert event.ip_hash is not None and len(event.ip_hash) == 64


def test_audit_table_has_no_secret_or_plain_ip_columns() -> None:
    columns = SecurityAuditEventModel.__table__.columns
    assert "metadata" in columns
    assert "ip_hash" in columns
    assert "ip" not in columns
    assert {"password", "token", "secret", "credentials"}.isdisjoint(columns.keys())
    assert SecurityAuditEventModel.__table__.columns.request_id.type.python_type is UUID
