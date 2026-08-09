import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from beanly.main import app
from beanly.modules.identity.infrastructure.db.models import AuthSessionModel, UserModel


async def register(client: AsyncClient, payload: dict[str, str]):
    return await client.post("/api/v1/auth/register", json=payload)


async def login(client: AsyncClient, payload: dict[str, str]):
    return await client.post(
        "/api/v1/auth/login",
        json={"email": payload["email"], "password": payload["password"]},
    )


@pytest.mark.anyio
async def test_user_can_register_and_password_is_hashed(app_client, user_payload) -> None:
    client, sessions = app_client
    response = await register(client, user_payload)
    assert response.status_code == 201
    assert response.json()["email"] == user_payload["email"]
    assert "password" not in response.json()

    async with sessions() as session:
        user = await session.scalar(select(UserModel))
    assert user is not None
    assert user.password_hash != user_payload["password"]
    assert user.password_hash.startswith("$argon2")


@pytest.mark.anyio
async def test_duplicate_email_is_rejected_case_insensitively(app_client, user_payload) -> None:
    client, _ = app_client
    assert (await register(client, user_payload)).status_code == 201
    duplicate = {**user_payload, "email": "OWNER@EXAMPLE.COM"}
    response = await register(client, duplicate)
    assert response.status_code == 409


@pytest.mark.anyio
async def test_invalid_email_is_rejected(app_client, user_payload) -> None:
    client, _ = app_client
    response = await register(client, {**user_payload, "email": "not-an-email"})
    assert response.status_code == 422


@pytest.mark.anyio
async def test_user_can_login_and_wrong_password_is_rejected(app_client, user_payload) -> None:
    client, sessions = app_client
    await register(client, user_payload)

    wrong = await client.post(
        "/api/v1/auth/login",
        json={"email": user_payload["email"], "password": "wrong-password"},
    )
    assert wrong.status_code == 401

    response = await login(client, user_payload)
    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    raw_refresh = client.cookies.get("beanly_refresh")
    assert raw_refresh

    async with sessions() as session:
        auth_session = await session.scalar(select(AuthSessionModel))
    assert auth_session is not None
    assert auth_session.refresh_token_hash != raw_refresh
    assert len(auth_session.refresh_token_hash) == 64


@pytest.mark.anyio
async def test_refresh_rotates_token_and_old_token_is_rejected(app_client, user_payload) -> None:
    client, _ = app_client
    await register(client, user_payload)
    login_response = await login(client, user_payload)
    old_refresh = client.cookies.get("beanly_refresh")
    old_access = login_response.json()["access_token"]

    refreshed = await client.post("/api/v1/auth/refresh")
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"] != old_access
    assert client.cookies.get("beanly_refresh") != old_refresh

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"origin": "http://localhost:3000", "cookie": f"beanly_refresh={old_refresh}"},
    ) as replay_client:
        replay = await replay_client.post("/api/v1/auth/refresh")
    assert replay.status_code == 401


@pytest.mark.anyio
async def test_logout_invalidates_session_and_access_token(app_client, user_payload) -> None:
    client, _ = app_client
    await register(client, user_payload)
    login_response = await login(client, user_payload)
    access_token = login_response.json()["access_token"]

    before = await client.get(
        "/api/v1/auth/me", headers={"authorization": f"Bearer {access_token}"}
    )
    assert before.status_code == 200

    logout_response = await client.post("/api/v1/auth/logout")
    assert logout_response.status_code == 204
    after = await client.get("/api/v1/auth/me", headers={"authorization": f"Bearer {access_token}"})
    assert after.status_code == 401
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401


@pytest.mark.anyio
async def test_me_requires_authentication(app_client) -> None:
    client, _ = app_client
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.anyio
async def test_cookie_mutations_reject_untrusted_origin(app_client, user_payload) -> None:
    client, _ = app_client
    await register(client, user_payload)
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": user_payload["email"], "password": user_payload["password"]},
        headers={"origin": "https://evil.example"},
    )
    assert response.status_code == 403
