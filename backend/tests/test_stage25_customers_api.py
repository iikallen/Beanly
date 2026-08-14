from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from test_offline_pos import _catalog, _cookie, _register_shift, _workspace
from test_payments import _order

from beanly.modules.customers.infrastructure.db.models import LoyaltyLedgerEntryModel


def _customer(phone: str, name: str = "Aruzhan") -> dict[str, object]:
    return {
        "phone": phone,
        "first_name": name,
        "last_name": "Tester",
        "email": f"{name.casefold()}@example.com",
        "birth_date": "1992-08-14",
        "note": "Stage 25",
        "marketing_consent": True,
    }


def _promotion() -> dict[str, object]:
    return {
        "name": "Customer only",
        "pos_name": "Customer only",
        "application_mode": "AUTOMATIC",
        "discount_kind": "PERCENT",
        "scope": "ORDER",
        "percent_rate": "10.0000",
        "priority": 100,
        "stacking_policy": "EXCLUSIVE",
        "all_locations": True,
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


def _coded(response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.json()["detail"]["code"] == code


@pytest.mark.anyio
async def test_customer_phone_is_normalized_per_tenant_without_cross_tenant_pii(app_client) -> None:
    client, _ = app_client
    first_headers, first_org, _, _ = await _workspace(
        client, "stage25-first@example.com", "Stage 25 first"
    )
    second_headers, second_org, _, _ = await _workspace(
        client, "stage25-second@example.com", "Stage 25 second"
    )

    first = await client.post(
        "/api/v1/customers", headers=first_headers, json=_customer("+7 (701) 234-56-78")
    )
    assert first.status_code == 201, first.text
    assert first.json()["organization_id"] == str(first_org)
    assert first.json()["phone"] == "+77012345678"

    duplicate = await client.post(
        "/api/v1/customers", headers=first_headers, json=_customer("8 701 234 56 78")
    )
    _coded(duplicate, 409, "CUSTOMER_PHONE_CONFLICT")

    second = await client.post(
        "/api/v1/customers", headers=second_headers, json=_customer("87012345678", "Dana")
    )
    assert second.status_code == 201, second.text
    assert second.json()["organization_id"] == str(second_org)
    assert second.json()["phone"] == "+77012345678"

    _coded(
        await client.get(f"/api/v1/customers/{second.json()['id']}", headers=first_headers),
        404,
        "CUSTOMER_NOT_FOUND",
    )
    listed = await client.get("/api/v1/customers", headers=first_headers)
    assert listed.status_code == 200, listed.text
    assert [row["id"] for row in listed.json()] == [first.json()["id"]]
    assert "dana@example.com" not in listed.text.casefold()


@pytest.mark.anyio
async def test_customer_targeted_promotion_is_excluded_from_offline_catalog(app_client) -> None:
    client, _ = app_client
    headers, _, location_id, warehouse_id = await _workspace(
        client, "stage25-offline@example.com", "Stage 25 offline"
    )
    customer = await client.post(
        "/api/v1/customers", headers=headers, json=_customer("+77015550101")
    )
    assert customer.status_code == 201, customer.text
    promotion = await client.post("/api/v1/promotions", headers=headers, json=_promotion())
    assert promotion.status_code == 201, promotion.text
    promotion_id = promotion.json()["id"]
    audience = await client.put(
        f"/api/v1/promotions/{promotion_id}/audience",
        headers=headers,
        json={"kind": "CUSTOMER", "tier_id": None, "customer_ids": [customer.json()["id"]]},
    )
    assert audience.status_code == 200, audience.text
    assert (
        await client.post(f"/api/v1/promotions/{promotion_id}/activate", headers=headers)
    ).status_code == 200

    register, shift = await _register_shift(client, headers, location_id, warehouse_id)
    await _catalog(client, headers)
    paired = await client.post(
        "/api/v1/pos/offline/devices/pair",
        headers=headers,
        json={"register_id": register["id"], "name": f"Stage 25 {uuid4().hex[:6]}"},
    )
    assert paired.status_code == 201, paired.text
    _, cookie = _cookie(paired)
    started = await client.post(
        "/api/v1/pos/offline/sessions/start",
        headers={**headers, "cookie": cookie},
        json={"shift_id": shift["id"]},
    )
    assert started.status_code == 201, started.text
    snapshot = started.json()["catalog_snapshot"]["payload"]
    assert promotion_id not in {
        value["promotion_id"] for value in snapshot.get("promotions", [])
    }
    assert "customer" not in str(snapshot).casefold()
    assert "+77015550101" not in str(snapshot)


@pytest.mark.anyio
async def test_loyalty_adjustment_is_immutable_and_payload_idempotent(app_client) -> None:
    client, sessions = app_client
    headers, _, _, _ = await _workspace(
        client, "stage25-adjust@example.com", "Stage 25 adjust"
    )
    customer = await client.post(
        "/api/v1/customers", headers=headers, json=_customer("+77015550102")
    )
    assert customer.status_code == 201, customer.text
    customer_id = customer.json()["id"]
    adjustment_id = str(uuid4())
    payload = {
        "client_adjustment_id": adjustment_id,
        "points_delta": "100",
        "reason": "Opening loyalty balance",
    }
    first = await client.post(
        f"/api/v1/customers/{customer_id}/loyalty/adjustments",
        headers=headers,
        json=payload,
    )
    assert first.status_code == 200, first.text
    assert first.json()["points_balance"] == "100"
    replay = await client.post(
        f"/api/v1/customers/{customer_id}/loyalty/adjustments",
        headers=headers,
        json=payload,
    )
    assert replay.status_code == 200, replay.text
    assert replay.json() == first.json()
    _coded(
        await client.post(
            f"/api/v1/customers/{customer_id}/loyalty/adjustments",
            headers=headers,
            json={**payload, "points_delta": "101"},
        ),
        409,
        "LOYALTY_IDEMPOTENCY_CONFLICT",
    )
    other_customer = await client.post(
        "/api/v1/customers",
        headers=headers,
        json=_customer("+77015550112", "Other"),
    )
    assert other_customer.status_code == 201, other_customer.text
    _coded(
        await client.post(
            f"/api/v1/customers/{other_customer.json()['id']}/loyalty/adjustments",
            headers=headers,
            json=payload,
        ),
        409,
        "LOYALTY_IDEMPOTENCY_CONFLICT",
    )
    _coded(
        await client.post(
            f"/api/v1/customers/{customer_id}/loyalty/adjustments",
            headers=headers,
            json={**payload, "client_adjustment_id": str(uuid4()), "points_delta": "-101"},
        ),
        409,
        "LOYALTY_INSUFFICIENT_BALANCE",
    )
    async with sessions() as session:
        assert await session.scalar(
            select(func.count()).select_from(LoyaltyLedgerEntryModel)
        ) == 1


@pytest.mark.anyio
async def test_customer_tier_and_birthday_promotion_audiences_are_server_authoritative(
    app_client,
) -> None:
    client, _ = app_client
    headers, _, location_id, warehouse_id = await _workspace(
        client, "stage25-audiences@example.com", "Stage 25 audiences"
    )
    assert (
        await client.patch(
            "/api/v1/loyalty/program",
            headers=headers,
            json={
                "earn_rate_bps": 0,
                "point_value_minor": "100",
                "birthday_reward_points": "10",
                "is_active": True,
            },
        )
    ).status_code == 200
    tier = await client.post(
        "/api/v1/loyalty/tiers",
        headers=headers,
        json={
            "name": "Birthday tier",
            "threshold_lifetime_points": "10",
            "earn_multiplier_bps": 10000,
        },
    )
    assert tier.status_code == 201, tier.text
    today = date.today()
    birthday = today.replace(year=2000).isoformat()
    other_day = (today - timedelta(days=1)).replace(year=2000).isoformat()
    eligible = await client.post(
        "/api/v1/customers",
        headers=headers,
        json={**_customer("+77015550103", "Birthday"), "birth_date": birthday},
    )
    other = await client.post(
        "/api/v1/customers",
        headers=headers,
        json={**_customer("+77015550104", "Other"), "birth_date": other_day},
    )
    assert eligible.status_code == other.status_code == 201
    _, shift = await _register_shift(client, headers, location_id, warehouse_id)
    variant_id, _ = await _catalog(client, headers)
    promotion = await client.post("/api/v1/promotions", headers=headers, json=_promotion())
    assert promotion.status_code == 201, promotion.text
    promotion_id = promotion.json()["id"]
    assert (
        await client.put(
            f"/api/v1/promotions/{promotion_id}/audience",
            headers=headers,
            json={
                "kind": "CUSTOMER",
                "tier_id": None,
                "customer_ids": [eligible.json()["id"]],
            },
        )
    ).status_code == 200
    assert (
        await client.post(f"/api/v1/promotions/{promotion_id}/activate", headers=headers)
    ).status_code == 200

    async def total(customer_id: str) -> str:
        order = await _order(client, headers, shift["id"], variant_id)
        attached = await client.put(
            f"/api/v1/sales/orders/{order['id']}/customer",
            headers=headers,
            json={"customer_id": customer_id},
        )
        assert attached.status_code == 200, attached.text
        return attached.json()["total_minor"]

    assert await total(eligible.json()["id"]) == "162000"
    assert await total(other.json()["id"]) == "180000"

    birthday_audience = await client.put(
        f"/api/v1/promotions/{promotion_id}/audience",
        headers=headers,
        json={"kind": "BIRTHDAY", "tier_id": None, "customer_ids": []},
    )
    assert birthday_audience.status_code == 200, birthday_audience.text
    assert await total(eligible.json()["id"]) == "162000"
    assert await total(other.json()["id"]) == "180000"

    tier_audience = await client.put(
        f"/api/v1/promotions/{promotion_id}/audience",
        headers=headers,
        json={"kind": "TIER", "tier_id": tier.json()["id"], "customer_ids": []},
    )
    assert tier_audience.status_code == 200, tier_audience.text
    assert await total(eligible.json()["id"]) == "162000"
    assert await total(other.json()["id"]) == "180000"
    loyalty = await client.get(
        f"/api/v1/customers/{eligible.json()['id']}/loyalty", headers=headers
    )
    assert loyalty.status_code == 200, loyalty.text
    assert loyalty.json()["points_balance"] == "10"
    assert [entry["kind"] for entry in loyalty.json()["entries"]] == [
        "BIRTHDAY_REWARD"
    ]
