from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from beanly.core.database.base import Base
from beanly.core.database.session import get_session
from beanly.main import app


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest_asyncio.fixture
async def app_client(
    tmp_path,
) -> AsyncIterator[tuple[AsyncClient, async_sessionmaker[AsyncSession]]]:
    test_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    test_sessions = async_sessionmaker(test_engine, expire_on_commit=False)
    async with test_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with test_sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"origin": "http://localhost:3000"},
    ) as client:
        yield client, test_sessions
    app.dependency_overrides.clear()
    await test_engine.dispose()


@pytest.fixture
def user_payload() -> dict[str, str]:
    return {
        "email": "owner@example.com",
        "password": "correct-horse-battery-staple",
        "first_name": "Aruzhan",
        "last_name": "Owner",
    }
