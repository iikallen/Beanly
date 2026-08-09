import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_liveness(app_client) -> None:
    client: AsyncClient = app_client[0]
    response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
