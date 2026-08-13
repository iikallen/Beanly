from datetime import datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from test_offline_pos import _catalog, _cookie, _register_shift, _workspace

from beanly.modules.sales.infrastructure.db.models import SalesOrderModel


@pytest.mark.anyio
async def test_offline_snapshot_recomputes_discount_and_rejects_tampered_payment(
    app_client,
) -> None:
    client, sessions = app_client
    headers, _, location_id, warehouse_id = await _workspace(
        client, "stage24-offline@example.com", "Stage 24 offline"
    )
    register, shift = await _register_shift(client, headers, location_id, warehouse_id)
    variant_id, _ = await _catalog(client, headers)
    promotion = await client.post(
        "/api/v1/promotions",
        headers=headers,
        json={
            "name": "Offline Happy Hour",
            "pos_name": "Offline -20%",
            "application_mode": "AUTOMATIC",
            "discount_kind": "PERCENT",
            "scope": "ORDER",
            "percent_rate": "20.0000",
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
        },
    )
    assert promotion.status_code == 201, promotion.text
    promotion_id = promotion.json()["id"]
    assert (
        await client.post(f"/api/v1/promotions/{promotion_id}/activate", headers=headers)
    ).status_code == 200
    paired = await client.post(
        "/api/v1/pos/offline/devices/pair",
        headers=headers,
        json={"register_id": register["id"], "name": "Stage 24 POS"},
    )
    assert paired.status_code == 201, paired.text
    _, cookie = _cookie(paired)
    started = await client.post(
        "/api/v1/pos/offline/sessions/start",
        headers={**headers, "cookie": cookie},
        json={"shift_id": shift["id"]},
    )
    assert started.status_code == 201, started.text
    offline = started.json()
    snapshot_promotions = offline["catalog_snapshot"]["payload"]["promotions"]
    assert [value["promotion_id"] for value in snapshot_promotions] == [promotion_id]
    sold_at = datetime.fromisoformat(offline["server_time"])
    order = {
        "client_order_id": str(uuid4()),
        "revision": 1,
        "base_server_version": None,
        "catalog_snapshot_id": offline["catalog_snapshot_id"],
        "offline_display_number": 1,
        "created_at": sold_at.isoformat(),
        "updated_at": sold_at.isoformat(),
        "order_type": "TAKEAWAY",
        "status": "PAID",
        "items": [
            {
                "client_item_id": str(uuid4()),
                "variant_id": str(variant_id),
                "selected_option_ids": [],
                "quantity": 1,
            }
        ],
        "manual_promotion_ids": [],
        "payment": {
            "client_payment_id": str(uuid4()),
            "completed_at": sold_at.isoformat(),
            "lines": [
                {"method": "CASH", "amount_minor": "0", "cash_received_minor": "0"}
            ],
        },
    }
    result = await client.post(
        "/api/v1/pos/offline/sync",
        headers={"cookie": cookie},
        json={"session_id": offline["id"], "orders": [order]},
    )
    assert result.status_code == 200, result.text
    assert result.json()["results"][0]["status"] == "CONFLICT"
    async with sessions() as session:
        assert await session.scalar(select(SalesOrderModel)) is None
