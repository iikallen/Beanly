from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from beanly.core.events.outbox.models import OutboxEventModel


async def _owner(client: AsyncClient) -> tuple[dict[str, str], UUID, UUID]:
    payload = {
        "email": "operations-owner@example.com",
        "password": "correct-horse-battery-staple",
        "first_name": "Inventory",
        "last_name": "Owner",
    }
    assert (await client.post("/api/v1/auth/register", json=payload)).status_code == 201
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": payload["email"], "password": payload["password"]},
    )
    headers = {"authorization": f"Bearer {login.json()['access_token']}"}
    workspace = await client.post(
        "/api/v1/organizations",
        headers=headers,
        json={
            "name": "Inventory Operations",
            "country_code": "KZ",
            "currency_code": "KZT",
            "first_location": {"name": "Dostyk", "timezone": "Asia/Almaty"},
        },
    )
    organization_id = UUID(workspace.json()["organization"]["id"])
    location_id = UUID(workspace.json()["location"]["id"])
    return {**headers, "X-Organization-ID": str(organization_id)}, organization_id, location_id


async def _warehouse(
    client: AsyncClient, headers: dict[str, str], location_id: UUID, name: str
) -> UUID:
    response = await client.post(
        "/api/v1/inventory/warehouses",
        headers=headers,
        json={"location_id": str(location_id), "name": name},
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


async def _item(client: AsyncClient, headers: dict[str, str], name: str) -> UUID:
    response = await client.post(
        "/api/v1/inventory/items",
        headers=headers,
        json={"name": name, "base_unit": "g", "sku": None},
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


async def _stock(
    client: AsyncClient, headers: dict[str, str], warehouse_id: UUID, item_id: UUID
) -> dict:
    response = await client.get(
        f"/api/v1/inventory/items/{item_id}/stock",
        params={"warehouse_id": str(warehouse_id)},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.anyio
async def test_writeoff_count_transfer_and_movement_workflows(app_client) -> None:
    client, sessions = app_client
    headers, organization_id, source_location_id = await _owner(client)
    source_id = await _warehouse(client, headers, source_location_id, "Source")
    destination_location = await client.post(
        f"/api/v1/organizations/{organization_id}/locations",
        headers=headers,
        json={"name": "Airport", "timezone": "Asia/Almaty"},
    )
    assert destination_location.status_code == 201, destination_location.text
    destination_id = await _warehouse(
        client, headers, UUID(destination_location.json()["id"]), "Destination"
    )
    coffee_id = await _item(client, headers, "Coffee")

    for warehouse_id, cost in ((source_id, "8000"), (destination_id, "10000")):
        opening = await client.post(
            "/api/v1/inventory/opening-balances",
            headers={**headers, "Idempotency-Key": f"opening:{warehouse_id}"},
            json={
                "warehouse_id": str(warehouse_id),
                "items": [
                    {
                        "inventory_item_id": str(coffee_id),
                        "quantity": "1",
                        "unit_code": "kg",
                        "unit_cost_amount": cost,
                    }
                ],
            },
        )
        assert opening.status_code == 201, opening.text

    reason = await client.post(
        "/api/v1/inventory/write-off-reasons",
        headers=headers,
        json={"name": "Spoilage"},
    )
    assert reason.status_code == 201, reason.text
    writeoff = await client.post(
        "/api/v1/inventory/write-offs",
        headers=headers,
        json={
            "warehouse_id": str(source_id),
            "reason_id": reason.json()["id"],
            "occurred_at": "2026-08-10T09:40:00Z",
            "note": "Expired",
            "lines": [
                {"inventory_item_id": str(coffee_id), "quantity": "0.1", "unit": "kg"}
            ],
        },
    )
    assert writeoff.status_code == 201, writeoff.text
    posted_writeoff = await client.post(
        f"/api/v1/inventory/write-offs/{writeoff.json()['id']}/post", headers=headers
    )
    assert posted_writeoff.status_code == 200, posted_writeoff.text
    assert posted_writeoff.json()["status"] == "POSTED"
    assert posted_writeoff.json()["total_cost_amount"] == "800"
    assert (await _stock(client, headers, source_id, coffee_id))["quantity"] == "900"

    generic_reverse = await client.post(
        f"/api/v1/inventory/transactions/"
        f"{posted_writeoff.json()['inventory_transaction_id']}/reverse",
        headers=headers,
    )
    assert generic_reverse.status_code == 409
    assert generic_reverse.json() == {"code": "SOURCE_CONTROLLED_TRANSACTION"}
    reversed_writeoff = await client.post(
        f"/api/v1/inventory/write-offs/{writeoff.json()['id']}/reverse", headers=headers
    )
    assert reversed_writeoff.status_code == 200, reversed_writeoff.text
    assert reversed_writeoff.json()["status"] == "REVERSED"
    assert (await _stock(client, headers, source_id, coffee_id))["quantity"] == "1000"
    assert (
        await client.post(
            f"/api/v1/inventory/write-offs/{writeoff.json()['id']}/reverse", headers=headers
        )
    ).status_code == 409

    count = await client.post(
        "/api/v1/inventory/counts",
        headers=headers,
        json={
            "warehouse_id": str(source_id),
            "type": "FULL",
            "inventory_item_ids": [],
        },
    )
    assert count.status_code == 201, count.text
    coffee_line = next(
        line for line in count.json()["lines"] if line["inventory_item_id"] == str(coffee_id)
    )
    assert coffee_line["expected_quantity"] == "1000"
    movement = await client.post(
        "/api/v1/inventory/adjustments",
        headers={**headers, "Idempotency-Key": "during-count"},
        json={
            "warehouse_id": str(source_id),
            "reason": "Sale during count",
            "lines": [
                {
                    "inventory_item_id": str(coffee_id),
                    "quantity": "-100",
                    "unit_code": "g",
                }
            ],
        },
    )
    assert movement.status_code == 201, movement.text
    restoring_movement = await client.post(
        "/api/v1/inventory/adjustments",
        headers={**headers, "Idempotency-Key": "during-count-restore"},
        json={
            "warehouse_id": str(source_id),
            "reason": "Correction during count",
            "lines": [
                {
                    "inventory_item_id": str(coffee_id),
                    "quantity": "100",
                    "unit_code": "g",
                }
            ],
        },
    )
    assert restoring_movement.status_code == 201, restoring_movement.text
    count_update = await client.put(
        f"/api/v1/inventory/counts/{count.json()['id']}/lines",
        headers=headers,
        json={
            "lines": [
                {
                    "inventory_item_id": str(coffee_id),
                    "counted_quantity": "850",
                    "unit": "g",
                }
            ]
        },
    )
    assert count_update.status_code == 200, count_update.text
    stale = await client.post(
        f"/api/v1/inventory/counts/{count.json()['id']}/post",
        headers=headers,
        json={"confirm_stock_changes": False},
    )
    assert stale.status_code == 409
    assert stale.json() == {
        "code": "INVENTORY_COUNT_CHANGED",
        "changed_items": [
            {
                "inventory_item_id": str(coffee_id),
                "expected_at_start": "1000.000000",
                "current": "1000.000000",
            }
        ],
    }
    posted_count = await client.post(
        f"/api/v1/inventory/counts/{count.json()['id']}/post",
        headers=headers,
        json={"confirm_stock_changes": True},
    )
    assert posted_count.status_code == 200, posted_count.text
    coffee_line = next(
        line
        for line in posted_count.json()["lines"]
        if line["inventory_item_id"] == str(coffee_id)
    )
    assert coffee_line["current_quantity_before_post"] == "1000"
    assert coffee_line["difference_quantity"] == "-150"
    assert (await _stock(client, headers, source_id, coffee_id))["quantity"] == "850"

    zero_count = await client.post(
        "/api/v1/inventory/counts",
        headers=headers,
        json={
            "warehouse_id": str(source_id),
            "type": "PARTIAL",
            "inventory_item_ids": [str(coffee_id)],
        },
    )
    zero_update = await client.put(
        f"/api/v1/inventory/counts/{zero_count.json()['id']}/lines",
        headers=headers,
        json={
            "lines": [
                {
                    "inventory_item_id": str(coffee_id),
                    "counted_quantity": "850",
                    "unit": "g",
                }
            ]
        },
    )
    assert zero_update.status_code == 200, zero_update.text
    zero_post = await client.post(
        f"/api/v1/inventory/counts/{zero_count.json()['id']}/post",
        headers=headers,
        json={"confirm_stock_changes": False},
    )
    assert zero_post.status_code == 200, zero_post.text
    assert zero_post.json()["inventory_transaction_id"] is None

    no_cost_count_item = await _item(client, headers, "Count without cost")
    positive_count = await client.post(
        "/api/v1/inventory/counts",
        headers=headers,
        json={
            "warehouse_id": str(source_id),
            "type": "PARTIAL",
            "inventory_item_ids": [str(no_cost_count_item)],
        },
    )
    positive_update_url = (
        f"/api/v1/inventory/counts/{positive_count.json()['id']}/lines"
    )
    positive_line = {
        "inventory_item_id": str(no_cost_count_item),
        "counted_quantity": "10",
        "unit": "g",
    }
    assert (
        await client.put(
            positive_update_url,
            headers=headers,
            json={"lines": [{**positive_line, "unit_cost_amount": "0.0000001"}]},
        )
    ).status_code == 422
    assert (
        await client.put(
            positive_update_url,
            headers=headers,
            json={
                "lines": [
                    {**positive_line, "unit_cost_amount": "100000000000000"}
                ]
            },
        )
    ).status_code == 422
    assert (
        await client.put(
            positive_update_url, headers=headers, json={"lines": [positive_line]}
        )
    ).status_code == 200
    missing_positive_cost = await client.post(
        f"/api/v1/inventory/counts/{positive_count.json()['id']}/post",
        headers=headers,
        json={"confirm_stock_changes": False},
    )
    assert missing_positive_cost.status_code == 409
    assert "Unit cost is required" in missing_positive_cost.text
    assert (
        await client.put(
            positive_update_url,
            headers=headers,
            json={"lines": [{**positive_line, "unit_cost_amount": "0"}]},
        )
    ).status_code == 200
    zero_cost_post = await client.post(
        f"/api/v1/inventory/counts/{positive_count.json()['id']}/post",
        headers=headers,
        json={"confirm_stock_changes": False},
    )
    assert zero_cost_post.status_code == 200, zero_cost_post.text
    assert (
        await _stock(client, headers, source_id, no_cost_count_item)
    )["average_unit_cost"] == "0"

    transfer = await client.post(
        "/api/v1/inventory/transfers",
        headers=headers,
        json={
            "source_warehouse_id": str(source_id),
            "destination_warehouse_id": str(destination_id),
            "occurred_at": "2026-08-10T10:30:00Z",
            "lines": [
                {"inventory_item_id": str(coffee_id), "quantity": "0.5", "unit": "kg"}
            ],
        },
    )
    assert transfer.status_code == 201, transfer.text
    posted_transfer = await client.post(
        f"/api/v1/inventory/transfers/{transfer.json()['id']}/post", headers=headers
    )
    assert posted_transfer.status_code == 200, posted_transfer.text
    assert (await _stock(client, headers, source_id, coffee_id))["quantity"] == "350"
    destination_stock = await _stock(client, headers, destination_id, coffee_id)
    assert destination_stock["quantity"] == "1500"
    assert destination_stock["average_unit_cost"] == "9.333333"
    repeated = await client.post(
        f"/api/v1/inventory/transfers/{transfer.json()['id']}/post", headers=headers
    )
    assert repeated.status_code == 200
    assert repeated.json()["out_transaction_id"] == posted_transfer.json()["out_transaction_id"]

    no_cost_id = await _item(client, headers, "No cost")
    missing_cost = await client.post(
        "/api/v1/inventory/transfers",
        headers=headers,
        json={
            "source_warehouse_id": str(source_id),
            "destination_warehouse_id": str(destination_id),
            "occurred_at": "2026-08-10T10:40:00Z",
            "lines": [
                {"inventory_item_id": str(no_cost_id), "quantity": "1", "unit": "g"}
            ],
        },
    )
    blocked = await client.post(
        f"/api/v1/inventory/transfers/{missing_cost.json()['id']}/post", headers=headers
    )
    assert blocked.status_code == 409
    assert "TRANSFER_COST_UNAVAILABLE" in blocked.text

    reversed_transfer = await client.post(
        f"/api/v1/inventory/transfers/{transfer.json()['id']}/reverse", headers=headers
    )
    assert reversed_transfer.status_code == 200, reversed_transfer.text
    assert (await _stock(client, headers, source_id, coffee_id))["quantity"] == "850"
    restored_destination = await _stock(client, headers, destination_id, coffee_id)
    assert restored_destination["quantity"] == "1000"
    assert restored_destination["average_unit_cost"] == "10"

    movements = await client.get(
        "/api/v1/inventory/movements",
        headers=headers,
        params={"inventory_item_id": str(coffee_id), "type": "TRANSFER_OUT"},
    )
    assert movements.status_code == 200, movements.text
    assert {value["reference_type"] for value in movements.json()} == {"TRANSFER"}
    assert all(value["inventory_item_id"] == str(coffee_id) for value in movements.json())

    async with sessions() as session:
        event_names = set(
            await session.scalars(
                select(OutboxEventModel.event_name).where(
                    OutboxEventModel.organization_id == organization_id
                )
            )
        )
    assert {
        "inventory.writeoff_posted",
        "inventory.writeoff_reversed",
        "inventory.count_posted",
        "inventory.transfer_posted",
        "inventory.transfer_reversed",
    } <= event_names
