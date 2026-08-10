from datetime import UTC, datetime
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from beanly.core.events.outbox.models import OutboxEventModel
from beanly.core.events.outbox.repositories import OutboxRepository
from beanly.modules.purchasing.infrastructure.inventory_gateway import (
    InventoryApplicationGateway,
)


async def authenticated_user(client: AsyncClient, email: str) -> dict[str, str]:
    payload = {
        "email": email,
        "password": "correct-horse-battery-staple",
        "first_name": "Purchasing",
        "last_name": "Owner",
    }
    assert (await client.post("/api/v1/auth/register", json=payload)).status_code == 201
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": payload["password"]},
    )
    return {"authorization": f"Bearer {login.json()['access_token']}"}


async def workspace(
    client: AsyncClient, headers: dict[str, str], name: str
) -> tuple[dict[str, str], UUID, UUID]:
    response = await client.post(
        "/api/v1/organizations",
        headers=headers,
        json={
            "name": name,
            "country_code": "KZ",
            "currency_code": "KZT",
            "first_location": {"name": "Dostyk", "timezone": "Asia/Almaty"},
        },
    )
    body = response.json()
    organization_id = UUID(body["organization"]["id"])
    location_id = UUID(body["location"]["id"])
    return (
        {**headers, "X-Organization-ID": str(organization_id)},
        organization_id,
        location_id,
    )


async def inventory_resources(
    client: AsyncClient,
    headers: dict[str, str],
    location_id: UUID,
    name: str = "Coffee Beans",
    base_unit: str = "g",
) -> tuple[str, str]:
    warehouse = await client.post(
        "/api/v1/inventory/warehouses",
        headers=headers,
        json={"location_id": str(location_id), "name": "Main warehouse"},
    )
    item = await client.post(
        "/api/v1/inventory/items",
        headers=headers,
        json={"name": name, "base_unit": base_unit},
    )
    assert warehouse.status_code == item.status_code == 201
    return warehouse.json()["id"], item.json()["id"]


async def supplier(client: AsyncClient, headers: dict[str, str], name: str) -> dict:
    response = await client.post(
        "/api/v1/suppliers",
        headers=headers,
        json={
            "name": name,
            "contact_name": "Aruzhan",
            "email": "SUPPLIER@example.com",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def order(
    client: AsyncClient,
    headers: dict[str, str],
    supplier_id: str,
    location_id: UUID,
    warehouse_id: str,
    item_id: str,
    quantity: str = "10",
) -> dict:
    response = await client.post(
        "/api/v1/purchasing/orders",
        headers=headers,
        json={
            "supplier_id": supplier_id,
            "location_id": str(location_id),
            "warehouse_id": warehouse_id,
            "expected_at": "2026-08-12T10:00:00Z",
            "lines": [
                {
                    "inventory_item_id": item_id,
                    "quantity": quantity,
                    "unit": "kg",
                    "unit_price": "8000",
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def receipt_for_order(
    client: AsyncClient,
    headers: dict[str, str],
    order_body: dict,
    quantity: str,
    price: str = "8100",
) -> dict:
    line = order_body["lines"][0]
    response = await client.post(
        f"/api/v1/purchasing/orders/{order_body['id']}/receipts",
        headers=headers,
        json={
            "received_at": datetime.now(UTC).isoformat(),
            "document_number": "INV-34819",
            "lines": [
                {
                    "purchase_order_line_id": line["id"],
                    "inventory_item_id": line["inventory_item_id"],
                    "quantity": quantity,
                    "purchase_unit": "kg",
                    "unit_price": price,
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.anyio
async def test_supplier_order_partial_receipts_idempotency_and_reversal(app_client) -> None:
    client, _ = app_client
    auth = await authenticated_user(client, "purchasing-flow@example.com")
    headers, _, location_id = await workspace(client, auth, "Purchasing Flow")
    warehouse_id, item_id = await inventory_resources(client, headers, location_id)
    supplier_body = await supplier(client, headers, "Coffee Import KZ")
    assert supplier_body["email"] == "supplier@example.com"
    updated_supplier = await client.patch(
        f"/api/v1/suppliers/{supplier_body['id']}",
        headers=headers,
        json={**supplier_body, "contact_name": "Dana"},
    )
    assert updated_supplier.status_code == 200
    assert updated_supplier.json()["contact_name"] == "Dana"
    order_body = await order(
        client,
        headers,
        supplier_body["id"],
        location_id,
        warehouse_id,
        item_id,
    )
    assert order_body["number"].startswith("PO-")
    assert order_body["status"] == "DRAFT"
    assert order_body["lines"][0]["base_quantity"] == "10000"
    assert order_body["lines"][0]["line_total_minor"] == "8000000"

    submitted = await client.post(
        f"/api/v1/purchasing/orders/{order_body['id']}/submit", headers=headers
    )
    assert submitted.status_code == 200, submitted.text
    order_body = submitted.json()
    assert order_body["status"] == "ORDERED"
    assert (
        await client.patch(
            f"/api/v1/purchasing/orders/{order_body['id']}",
            headers=headers,
            json={"note": "late edit"},
        )
    ).status_code == 409

    first = await receipt_for_order(client, headers, order_body, "6")
    assert first["lines"][0]["base_quantity"] == "6000"
    assert first["lines"][0]["unit_price"] == "8100"
    posted = await client.post(
        f"/api/v1/purchasing/receipts/{first['id']}/post",
        headers=headers,
        json={"confirm_over_receipt": False},
    )
    assert posted.status_code == 200, posted.text
    first = posted.json()
    assert first["status"] == "POSTED"
    inventory_transaction_id = first["inventory_transaction_id"]
    again = await client.post(
        f"/api/v1/purchasing/receipts/{first['id']}/post",
        headers=headers,
        json={"confirm_over_receipt": False},
    )
    assert again.status_code == 200
    assert again.json()["inventory_transaction_id"] == inventory_transaction_id
    assert (
        await client.patch(
            f"/api/v1/purchasing/receipts/{first['id']}",
            headers=headers,
            json={"note": "mutate posted"},
        )
    ).status_code == 409
    partial = await client.get(f"/api/v1/purchasing/orders/{order_body['id']}", headers=headers)
    assert partial.json()["status"] == "PARTIALLY_RECEIVED"
    assert partial.json()["lines"][0]["remaining_base_quantity"] == "4000"

    second = await receipt_for_order(client, headers, partial.json(), "4", "8200")
    posted_second = await client.post(
        f"/api/v1/purchasing/receipts/{second['id']}/post",
        headers=headers,
        json={"confirm_over_receipt": False},
    )
    assert posted_second.status_code == 200, posted_second.text
    received = await client.get(f"/api/v1/purchasing/orders/{order_body['id']}", headers=headers)
    assert received.json()["status"] == "RECEIVED"
    assert (
        await client.post(f"/api/v1/purchasing/orders/{order_body['id']}/cancel", headers=headers)
    ).status_code == 409
    stock = await client.get(
        f"/api/v1/inventory/items/{item_id}/stock",
        headers=headers,
        params={"warehouse_id": warehouse_id},
    )
    assert stock.json()["quantity"] == "10000"
    transaction = await client.get(
        f"/api/v1/inventory/transactions/{inventory_transaction_id}", headers=headers
    )
    assert transaction.json()["type"] == "PURCHASE"
    assert transaction.json()["reference_type"] == "GOODS_RECEIPT"
    assert transaction.json()["reference_id"] == first["id"]
    assert transaction.json()["lines"][0]["unit_cost_amount"] == "8.1"

    reversed_response = await client.post(
        f"/api/v1/purchasing/receipts/{second['id']}/reverse", headers=headers
    )
    assert reversed_response.status_code == 200, reversed_response.text
    assert reversed_response.json()["status"] == "REVERSED"
    assert (
        await client.post(f"/api/v1/purchasing/receipts/{second['id']}/reverse", headers=headers)
    ).status_code == 409
    order_after_reverse = await client.get(
        f"/api/v1/purchasing/orders/{order_body['id']}", headers=headers
    )
    assert order_after_reverse.json()["status"] == "PARTIALLY_RECEIVED"
    restored = await client.get(
        f"/api/v1/inventory/items/{item_id}/stock",
        headers=headers,
        params={"warehouse_id": warehouse_id},
    )
    assert restored.json()["quantity"] == "6000"

    cancellable = await order(
        client,
        headers,
        supplier_body["id"],
        location_id,
        warehouse_id,
        item_id,
        "1",
    )
    cancelled = await client.post(
        f"/api/v1/purchasing/orders/{cancellable['id']}/cancel", headers=headers
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
    assert (
        await client.post(f"/api/v1/purchasing/orders/{cancellable['id']}/submit", headers=headers)
    ).status_code == 409

    deactivated = await client.post(
        f"/api/v1/suppliers/{supplier_body['id']}/deactivate", headers=headers
    )
    assert deactivated.json()["is_active"] is False
    history = await client.get(f"/api/v1/purchasing/orders/{order_body['id']}", headers=headers)
    assert history.json()["supplier_name"] == "Coffee Import KZ"


@pytest.mark.anyio
async def test_quick_receive_over_receipt_tenant_isolation_and_atomic_rollback(
    app_client, monkeypatch
) -> None:
    client, _ = app_client
    auth_a = await authenticated_user(client, "purchasing-a@example.com")
    headers_a, _, location_a = await workspace(client, auth_a, "Purchasing A")
    warehouse_a, item_a = await inventory_resources(client, headers_a, location_a)
    supplier_a = await supplier(client, headers_a, "Supplier A")
    order_a = await order(
        client,
        headers_a,
        supplier_a["id"],
        location_a,
        warehouse_a,
        item_a,
        "1",
    )
    await client.post(f"/api/v1/purchasing/orders/{order_a['id']}/submit", headers=headers_a)
    order_a = (
        await client.get(f"/api/v1/purchasing/orders/{order_a['id']}", headers=headers_a)
    ).json()
    over = await receipt_for_order(client, headers_a, order_a, "1.1")
    warning = await client.post(
        f"/api/v1/purchasing/receipts/{over['id']}/post",
        headers=headers_a,
        json={"confirm_over_receipt": False},
    )
    assert warning.status_code == 409
    assert warning.json()["detail"]["code"] == "RECEIVED_QUANTITY_EXCEEDS_ORDER"
    confirmed = await client.post(
        f"/api/v1/purchasing/receipts/{over['id']}/post",
        headers=headers_a,
        json={"confirm_over_receipt": True},
    )
    assert confirmed.status_code == 200

    auth_b = await authenticated_user(client, "purchasing-b@example.com")
    headers_b, _, location_b = await workspace(client, auth_b, "Purchasing B")
    for path in (
        f"/api/v1/suppliers/{supplier_a['id']}",
        f"/api/v1/purchasing/orders/{order_a['id']}",
        f"/api/v1/purchasing/receipts/{over['id']}",
    ):
        assert (await client.get(path, headers=headers_b)).status_code == 404

    supplier_b = await supplier(client, headers_b, "Supplier B")
    warehouse_b, item_b = await inventory_resources(client, headers_b, location_b)
    base_payload = {
        "supplier_id": supplier_a["id"],
        "location_id": str(location_a),
        "warehouse_id": warehouse_a,
        "lines": [
            {
                "inventory_item_id": item_a,
                "quantity": "1",
                "unit": "kg",
                "unit_price": "10",
            }
        ],
    }
    for changed in (
        {"supplier_id": supplier_b["id"]},
        {"warehouse_id": warehouse_b},
        {"inventory_item_id": item_b},
        {"location_id": str(location_b)},
    ):
        payload = {**base_payload, **{k: v for k, v in changed.items() if k != "inventory_item_id"}}
        if "inventory_item_id" in changed:
            payload["lines"] = [{**base_payload["lines"][0], **changed}]
        rejected = await client.post("/api/v1/purchasing/orders", headers=headers_a, json=payload)
        assert rejected.status_code == 404, rejected.text

    milk_warehouse, milk_item = await inventory_resources(
        client, headers_a, location_a, "Whole Milk", "ml"
    )
    quick_success = await client.post(
        "/api/v1/purchasing/receipts",
        headers=headers_a,
        json={
            "supplier_id": supplier_a["id"],
            "location_id": str(location_a),
            "warehouse_id": milk_warehouse,
            "received_at": datetime.now(UTC).isoformat(),
            "lines": [
                {
                    "inventory_item_id": milk_item,
                    "quantity": "1",
                    "purchase_unit": "box",
                    "unit_multiplier": "12000",
                    "unit_price": "8400",
                }
            ],
        },
    )
    assert quick_success.status_code == 201
    quick_posted = await client.post(
        f"/api/v1/purchasing/receipts/{quick_success.json()['id']}/post",
        headers=headers_a,
        json={"confirm_over_receipt": False},
    )
    assert quick_posted.status_code == 200
    assert quick_posted.json()["purchase_order_id"] is None
    assert quick_posted.json()["lines"][0]["base_quantity"] == "12000"
    milk_stock = await client.get(
        f"/api/v1/inventory/items/{milk_item}/stock",
        headers=headers_a,
        params={"warehouse_id": milk_warehouse},
    )
    assert milk_stock.json()["quantity"] == "12000"

    original = InventoryApplicationGateway.receive_purchase

    async def fail_after_inventory(self, *args, **kwargs):
        await original(self, *args, **kwargs)
        raise RuntimeError("forced failure after inventory staging")

    monkeypatch.setattr(InventoryApplicationGateway, "receive_purchase", fail_after_inventory)
    quick = await client.post(
        "/api/v1/purchasing/receipts",
        headers=headers_a,
        json={
            "supplier_id": supplier_a["id"],
            "location_id": str(location_a),
            "warehouse_id": warehouse_a,
            "received_at": datetime.now(UTC).isoformat(),
            "lines": [
                {
                    "inventory_item_id": item_a,
                    "quantity": "2",
                    "purchase_unit": "kg",
                    "unit_price": "7000",
                }
            ],
        },
    )
    assert quick.status_code == 201
    with pytest.raises(RuntimeError, match="forced failure"):
        await client.post(
            f"/api/v1/purchasing/receipts/{quick.json()['id']}/post",
            headers=headers_a,
            json={"confirm_over_receipt": False},
        )
    receipt = await client.get(
        f"/api/v1/purchasing/receipts/{quick.json()['id']}", headers=headers_a
    )
    assert receipt.json()["status"] == "DRAFT"
    stock = await client.get(
        f"/api/v1/inventory/items/{item_a}/stock",
        headers=headers_a,
        params={"warehouse_id": warehouse_a},
    )
    assert stock.json()["quantity"] == "1100"


@pytest.mark.anyio
async def test_linked_supplier_return_uses_wac_limits_cumulative_and_reverses(
    app_client, monkeypatch
) -> None:
    client, sessions = app_client
    auth = await authenticated_user(client, "supplier-return@example.com")
    headers, _, location_id = await workspace(client, auth, "Supplier Return")
    warehouse_id, item_id = await inventory_resources(client, headers, location_id)
    supplier_body = await supplier(client, headers, "Coffee Supplier")
    order_body = await order(
        client,
        headers,
        supplier_body["id"],
        location_id,
        warehouse_id,
        item_id,
    )
    order_body = (
        await client.post(f"/api/v1/purchasing/orders/{order_body['id']}/submit", headers=headers)
    ).json()
    receipt = await receipt_for_order(client, headers, order_body, "10", "8100")
    receipt = (
        await client.post(
            f"/api/v1/purchasing/receipts/{receipt['id']}/post",
            headers=headers,
            json={"confirm_over_receipt": False},
        )
    ).json()

    wrong_supplier = await supplier(client, headers, "Wrong Supplier")
    mismatch = await client.post(
        "/api/v1/purchasing/returns",
        headers=headers,
        json={
            "supplier_id": wrong_supplier["id"],
            "location_id": str(location_id),
            "warehouse_id": warehouse_id,
            "goods_receipt_id": receipt["id"],
            "returned_at": datetime.now(UTC).isoformat(),
            "lines": [
                {
                    "goods_receipt_line_id": receipt["lines"][0]["id"],
                    "inventory_item_id": item_id,
                    "quantity": "1",
                }
            ],
        },
    )
    assert mismatch.status_code == 409

    created = await client.post(
        "/api/v1/purchasing/returns",
        headers=headers,
        json={
            "supplier_id": supplier_body["id"],
            "location_id": str(location_id),
            "warehouse_id": warehouse_id,
            "goods_receipt_id": receipt["id"],
            "returned_at": datetime.now(UTC).isoformat(),
            "lines": [
                {
                    "goods_receipt_line_id": receipt["lines"][0]["id"],
                    "inventory_item_id": item_id,
                    "quantity": "3",
                }
            ],
        },
    )
    assert created.status_code == 201, created.text
    draft = created.json()
    assert draft["number"].startswith("SR-")
    assert draft["status"] == "DRAFT"
    assert draft["lines"][0]["unit_price"] == "8100"
    assert draft["lines"][0]["line_total_minor"] == "2430000"
    updated = await client.patch(
        f"/api/v1/purchasing/returns/{draft['id']}",
        headers=headers,
        json={"document_number": "SUP-CREDIT-1", "note": "Damaged bags"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["document_number"] == "SUP-CREDIT-1"
    listed = await client.get("/api/v1/purchasing/returns", headers=headers)
    assert listed.status_code == 200
    assert listed.json()[0]["goods_receipt_number"] == receipt["number"]

    posted = await client.post(f"/api/v1/purchasing/returns/{draft['id']}/post", headers=headers)
    assert posted.status_code == 200, posted.text
    posted_body = posted.json()
    assert posted_body["status"] == "POSTED"
    assert posted_body["lines"][0]["cumulative_returned_base_quantity"] == "3000"
    transaction = await client.get(
        f"/api/v1/inventory/transactions/{posted_body['inventory_transaction_id']}",
        headers=headers,
    )
    assert transaction.status_code == 200
    transaction_body = transaction.json()
    assert transaction_body["type"] == "RETURN_OUT"
    assert transaction_body["reference_type"] == "SUPPLIER_RETURN"
    assert transaction_body["reference_id"] == draft["id"]
    assert transaction_body["lines"][0]["quantity_delta"] == "-3000"
    assert transaction_body["lines"][0]["unit_cost_amount"] == "8.1"
    receipt_availability = await client.get(
        f"/api/v1/purchasing/receipts/{receipt['id']}", headers=headers
    )
    assert receipt_availability.json()["lines"][0]["returned_base_quantity"] == "3000"
    assert receipt_availability.json()["lines"][0]["returnable_base_quantity"] == "7000"
    assert (
        await client.patch(
            f"/api/v1/purchasing/returns/{draft['id']}",
            headers=headers,
            json={"note": "late edit"},
        )
    ).status_code == 409
    assert (
        await client.post(f"/api/v1/purchasing/receipts/{receipt['id']}/reverse", headers=headers)
    ).status_code == 409

    excessive = await client.post(
        "/api/v1/purchasing/returns",
        headers=headers,
        json={
            "supplier_id": supplier_body["id"],
            "location_id": str(location_id),
            "warehouse_id": warehouse_id,
            "goods_receipt_id": receipt["id"],
            "returned_at": datetime.now(UTC).isoformat(),
            "lines": [
                {
                    "goods_receipt_line_id": receipt["lines"][0]["id"],
                    "inventory_item_id": item_id,
                    "quantity": "8",
                }
            ],
        },
    )
    assert excessive.status_code == 409

    reversed_response = await client.post(
        f"/api/v1/purchasing/returns/{draft['id']}/reverse", headers=headers
    )
    assert reversed_response.status_code == 200, reversed_response.text
    assert reversed_response.json()["status"] == "REVERSED"
    stock = await client.get(
        f"/api/v1/inventory/items/{item_id}/stock",
        headers=headers,
        params={"warehouse_id": warehouse_id},
    )
    assert stock.json()["quantity"] == "10000"
    receipt_availability = await client.get(
        f"/api/v1/purchasing/receipts/{receipt['id']}", headers=headers
    )
    assert receipt_availability.json()["lines"][0]["returned_base_quantity"] == "0"
    assert (
        await client.post(f"/api/v1/purchasing/returns/{draft['id']}/reverse", headers=headers)
    ).status_code == 409

    other_auth = await authenticated_user(client, "supplier-return-other@example.com")
    other_headers, _, _ = await workspace(client, other_auth, "Other Return Tenant")
    assert (
        await client.get(f"/api/v1/purchasing/returns/{draft['id']}", headers=other_headers)
    ).status_code == 404
    async with sessions() as session:
        names = (
            await session.scalars(
                select(OutboxEventModel.event_name)
                .where(OutboxEventModel.aggregate_id == UUID(draft["id"]))
                .order_by(OutboxEventModel.created_at, OutboxEventModel.id)
            )
        ).all()
    assert len(names) == 3
    assert set(names) == {
        "purchasing.supplier_return_created",
        "purchasing.supplier_return_posted",
        "purchasing.supplier_return_reversed",
    }

    overflow = await client.post(
        "/api/v1/purchasing/returns",
        headers=headers,
        json={
            "supplier_id": supplier_body["id"],
            "location_id": str(location_id),
            "warehouse_id": warehouse_id,
            "returned_at": datetime.now(UTC).isoformat(),
            "lines": [
                {
                    "inventory_item_id": item_id,
                    "quantity": "10000000000000",
                    "purchase_unit": "g",
                    "unit_price": "10000000000000",
                }
            ],
        },
    )
    assert overflow.status_code == 422

    atomic = await client.post(
        "/api/v1/purchasing/returns",
        headers=headers,
        json={
            "supplier_id": supplier_body["id"],
            "location_id": str(location_id),
            "warehouse_id": warehouse_id,
            "goods_receipt_id": receipt["id"],
            "returned_at": datetime.now(UTC).isoformat(),
            "lines": [
                {
                    "goods_receipt_line_id": receipt["lines"][0]["id"],
                    "inventory_item_id": item_id,
                    "quantity": "1",
                }
            ],
        },
    )
    assert atomic.status_code == 201

    async def fail_outbox(*args, **kwargs):
        raise RuntimeError("forced outbox failure")

    monkeypatch.setattr(OutboxRepository, "add_many", fail_outbox)
    with pytest.raises(RuntimeError, match="forced outbox failure"):
        await client.post(f"/api/v1/purchasing/returns/{atomic.json()['id']}/post", headers=headers)
    unchanged = await client.get(
        f"/api/v1/purchasing/returns/{atomic.json()['id']}", headers=headers
    )
    assert unchanged.json()["status"] == "DRAFT"
    stock = await client.get(
        f"/api/v1/inventory/items/{item_id}/stock",
        headers=headers,
        params={"warehouse_id": warehouse_id},
    )
    assert stock.json()["quantity"] == "10000"
