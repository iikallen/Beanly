from uuid import UUID

import pytest
from httpx import AsyncClient


async def _workspace(client: AsyncClient, email: str, name: str) -> tuple[dict[str, str], UUID]:
    password = "correct-horse-battery-staple"
    registered = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": password,
            "first_name": "Stage",
            "last_name": "TwentyFour",
        },
    )
    assert registered.status_code == 201
    login = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    auth = {"authorization": f"Bearer {login.json()['access_token']}"}
    created = await client.post(
        "/api/v1/organizations",
        headers=auth,
        json={
            "name": name,
            "country_code": "KZ",
            "currency_code": "KZT",
            "first_location": {"name": "Dostyk", "timezone": "Asia/Almaty"},
        },
    )
    assert created.status_code == 201, created.text
    organization_id = UUID(created.json()["organization"]["id"])
    return {**auth, "X-Organization-ID": str(organization_id)}, organization_id


def _payload() -> dict[str, object]:
    return {
        "name": "Happy Hour",
        "pos_name": "Happy Hour -20%",
        "application_mode": "AUTOMATIC",
        "discount_kind": "PERCENT",
        "scope": "ITEM",
        "percent_rate": "20.0000",
        "priority": 100,
        "stacking_policy": "EXCLUSIVE",
        "include_modifier_price": False,
        "all_locations": True,
        "schedules": [
            {"weekday": 0, "start_local_time": "15:00", "end_local_time": "17:00"}
        ],
        "targets": [
            {
                "role": "ELIGIBLE",
                "target_type": "ALL",
                "target_id": None,
                "quantity": 1,
                "sort_order": 0,
            }
        ],
    }


@pytest.mark.anyio
async def test_promotion_crud_is_tenant_scoped_and_code_is_normalized(app_client) -> None:
    client, _ = app_client
    headers_a, organization_a = await _workspace(
        client, "stage24-a@example.com", "Stage 24 Tenant A"
    )
    headers_b, organization_b = await _workspace(
        client, "stage24-b@example.com", "Stage 24 Tenant B"
    )
    location_b = (
        await client.get(
            f"/api/v1/organizations/{organization_b}/locations", headers=headers_b
        )
    ).json()[0]["id"]
    category_b = await client.post(
        "/api/v1/menu/categories", headers=headers_b, json={"name": "Foreign"}
    )
    assert category_b.status_code == 201

    foreign_target = _payload()
    foreign_target["targets"] = [
        {
            "role": "ELIGIBLE",
            "target_type": "CATEGORY",
            "target_id": category_b.json()["id"],
            "quantity": 1,
            "sort_order": 0,
        }
    ]
    assert (
        await client.post("/api/v1/promotions", headers=headers_a, json=foreign_target)
    ).status_code == 404

    created = await client.post("/api/v1/promotions", headers=headers_a, json=_payload())
    assert created.status_code == 201, created.text
    body = created.json()
    assert UUID(body["organization_id"]) == organization_a
    assert body["status"] == "DRAFT"
    promotion_id = body["id"]

    listed = await client.get("/api/v1/promotions", headers=headers_a)
    assert listed.json()[0]["id"] == promotion_id
    cross_tenant = await client.get(f"/api/v1/promotions/{promotion_id}", headers=headers_b)
    assert cross_tenant.status_code == 404
    foreign_preview = await client.post(
        f"/api/v1/promotions/{promotion_id}/preview",
        headers=headers_a,
        json={"location_id": location_b, "occurred_at": "2026-08-10T10:00:00Z", "items": []},
    )
    assert foreign_preview.status_code == 404

    code = await client.post(
        f"/api/v1/promotions/{promotion_id}/codes",
        headers=headers_a,
        json={"code": " beanly 10 ", "max_redemptions": 1},
    )
    assert code.status_code == 201, code.text
    assert code.json()["codes"][0]["code"] == "BEANLY10"
    duplicate = await client.post(
        f"/api/v1/promotions/{promotion_id}/codes",
        headers=headers_a,
        json={"code": "BEANLY10"},
    )
    assert duplicate.status_code == 409

    activated = await client.post(
        f"/api/v1/promotions/{promotion_id}/activate", headers=headers_a
    )
    assert activated.status_code == 200, activated.text
    assert activated.json()["status"] == "ACTIVE"
    archived = await client.post(
        f"/api/v1/promotions/{promotion_id}/archive", headers=headers_a
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["status"] == "ARCHIVED"
    immutable = await client.patch(
        f"/api/v1/promotions/{promotion_id}", headers=headers_a, json=_payload()
    )
    assert immutable.status_code == 409
