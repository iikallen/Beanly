from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient


async def _user(client: AsyncClient, email: str) -> dict[str, str]:
    password = "correct-horse-battery-staple"
    created = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": password,
            "first_name": "Sales",
            "last_name": "User",
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200, login.text
    return {"authorization": f"Bearer {login.json()['access_token']}"}


async def _workspace(
    client: AsyncClient, email: str, name: str
) -> tuple[dict[str, str], UUID, UUID, UUID]:
    auth = await _user(client, email)
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
    location_id = UUID(created.json()["location"]["id"])
    headers = {**auth, "X-Organization-ID": str(organization_id)}
    warehouse = await client.post(
        "/api/v1/inventory/warehouses",
        headers=headers,
        json={"location_id": str(location_id), "name": "Main"},
    )
    assert warehouse.status_code == 201, warehouse.text
    return headers, organization_id, location_id, UUID(warehouse.json()["id"])


async def _item(
    client: AsyncClient, headers: dict[str, str], name: str, unit: str
) -> UUID:
    response = await client.post(
        "/api/v1/inventory/items",
        headers=headers,
        json={"name": name, "base_unit": unit},
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


async def _sellable_cappuccino(
    client: AsyncClient, headers: dict[str, str]
) -> tuple[UUID, UUID, dict[str, UUID]]:
    category = await client.post(
        "/api/v1/menu/categories", headers=headers, json={"name": "Coffee"}
    )
    assert category.status_code == 201, category.text
    product = await client.post(
        "/api/v1/menu/products",
        headers=headers,
        json={
            "category_id": category.json()["id"],
            "name": "Cappuccino",
            "default_variant": {
                "name": "350 ml",
                "base_price_minor": 180000,
                "is_default": True,
            },
        },
    )
    assert product.status_code == 201, product.text
    product = await client.patch(
        f"/api/v1/menu/products/{product.json()['id']}",
        headers=headers,
        json={"status": "ACTIVE"},
    )
    assert product.status_code == 200, product.text
    product_id = UUID(product.json()["id"])
    variant_id = UUID(product.json()["variants"][0]["id"])
    specs = (("Coffee", "g"), ("Milk", "ml"), ("Oat Milk", "ml"), ("Cup", "pcs"), ("Lid", "pcs"))
    item_ids = {name: await _item(client, headers, name, unit) for name, unit in specs}
    recipe = await client.put(
        f"/api/v1/menu/variants/{variant_id}/recipe",
        headers=headers,
        json={
            "components": [
                {"inventory_item_id": str(item_ids["Coffee"]), "quantity": "18", "unit": "g"},
                {"inventory_item_id": str(item_ids["Milk"]), "quantity": "230", "unit": "ml"},
                {"inventory_item_id": str(item_ids["Cup"]), "quantity": "1", "unit": "pcs"},
                {"inventory_item_id": str(item_ids["Lid"]), "quantity": "1", "unit": "pcs"},
            ]
        },
    )
    assert recipe.status_code == 200, recipe.text

    milk_group = await client.post(
        f"/api/v1/menu/variants/{variant_id}/modifier-groups",
        headers=headers,
        json={
            "name": "Milk",
            "selection_type": "SINGLE",
            "min_selections": 1,
            "max_selections": 1,
        },
    )
    extras_group = await client.post(
        f"/api/v1/menu/variants/{variant_id}/modifier-groups",
        headers=headers,
        json={
            "name": "Extras",
            "selection_type": "MULTIPLE",
            "min_selections": 0,
            "max_selections": 3,
        },
    )
    assert milk_group.status_code == extras_group.status_code == 201

    async def option(group_id: str, name: str, price: int, default: bool = False) -> UUID:
        response = await client.post(
            f"/api/v1/menu/modifier-groups/{group_id}/options",
            headers=headers,
            json={
                "name": name,
                "base_price_delta_minor": price,
                "is_default": default,
            },
        )
        assert response.status_code == 201, response.text
        return UUID(response.json()["id"])

    regular = await option(milk_group.json()["id"], "Regular", 0, True)
    oat = await option(milk_group.json()["id"], "Oat", 30000)
    shot = await option(extras_group.json()["id"], "Extra shot", 50000)
    oat_components = await client.put(
        f"/api/v1/menu/modifier-options/{oat}/components",
        headers=headers,
        json={
            "components": [
                {
                    "inventory_item_id": str(item_ids["Milk"]),
                    "quantity_delta": "-230",
                    "unit": "ml",
                },
                {
                    "inventory_item_id": str(item_ids["Oat Milk"]),
                    "quantity_delta": "230",
                    "unit": "ml",
                },
            ]
        },
    )
    shot_components = await client.put(
        f"/api/v1/menu/modifier-options/{shot}/components",
        headers=headers,
        json={
            "components": [
                {"inventory_item_id": str(item_ids["Coffee"]), "quantity_delta": "18", "unit": "g"}
            ]
        },
    )
    assert oat_components.status_code == shot_components.status_code == 200
    return product_id, variant_id, {
        **item_ids,
        "regular": regular,
        "oat": oat,
        "shot": shot,
    }


async def _register_and_shift(
    client: AsyncClient,
    headers: dict[str, str],
    location_id: UUID,
    warehouse_id: UUID,
) -> tuple[dict, dict]:
    register = await client.post(
        "/api/v1/sales/registers",
        headers=headers,
        json={"location_id": str(location_id), "name": "Front counter"},
    )
    assert register.status_code == 201, register.text
    shift = await client.post(
        "/api/v1/sales/shifts/open",
        headers=headers,
        json={"register_id": register.json()["id"], "warehouse_id": str(warehouse_id)},
    )
    assert shift.status_code == 201, shift.text
    return register.json(), shift.json()


def _coded_error(response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.json()["detail"]["code"] == code


@pytest.mark.anyio
async def test_sales_order_snapshots_mutations_idempotency_and_no_side_effects(app_client) -> None:
    client, _ = app_client
    headers, _, location_id, warehouse_id = await _workspace(
        client, "sales-order@example.com", "Sales Order"
    )
    product_id, variant_id, ids = await _sellable_cappuccino(client, headers)
    register, shift = await _register_and_shift(
        client, headers, location_id, warehouse_id
    )
    warehouses = await client.get(
        "/api/v1/sales/warehouses",
        headers=headers,
        params={"location_id": str(location_id)},
    )
    assert warehouses.status_code == 200, warehouses.text
    assert warehouses.json() == [
        {"id": str(warehouse_id), "location_id": str(location_id), "name": "Main"}
    ]
    assert shift["location_id"] == str(location_id)
    assert shift["warehouse_id"] == str(warehouse_id)
    assert (
        await client.get(
            "/api/v1/sales/shifts/current",
            headers=headers,
            params={"register_id": register["id"]},
        )
    ).json()["id"] == shift["id"]

    second_open = await client.post(
        "/api/v1/sales/shifts/open",
        headers=headers,
        json={"register_id": register["id"], "warehouse_id": str(warehouse_id)},
    )
    assert second_open.status_code == 409
    client_order_id = uuid4()
    payload = {
        "client_order_id": str(client_order_id),
        "shift_id": shift["id"],
        "order_type": "TAKEAWAY",
        "guest_count": None,
        "table_label": None,
        "note": None,
    }
    created = await client.post("/api/v1/sales/orders", headers=headers, json=payload)
    assert created.status_code == 201, created.text
    same = await client.post("/api/v1/sales/orders", headers=headers, json=payload)
    assert same.status_code == 201, same.text
    assert same.json()["id"] == created.json()["id"]
    assert int(created.json()["number"]) > 0
    assert created.json()["location_id"] == str(location_id)
    assert created.json()["warehouse_id"] == str(warehouse_id)
    order_id = created.json()["id"]
    assert len((await client.get("/api/v1/sales/orders", headers=headers)).json()) == 1

    cannot_close = await client.post(
        f"/api/v1/cash/drawers/{shift['drawer_session_id']}/close",
        headers=headers,
        json={"client_close_id": str(uuid4()), "actual_cash_minor": "0"},
    )
    _coded_error(cannot_close, 409, "SHIFT_CLOSE_SYNC_PENDING")
    client_item_id = uuid4()
    added = await client.post(
        f"/api/v1/sales/orders/{order_id}/items",
        headers=headers,
        json={
            "client_item_id": str(client_item_id),
            "variant_id": str(variant_id),
            "selected_option_ids": [str(ids["oat"]), str(ids["shot"])],
            "quantity": 2,
            "note": "Extra hot",
        },
    )
    assert added.status_code == 201, added.text
    order = added.json()
    assert order["subtotal_minor"] == order["total_minor"] == "520000"
    assert len(order["items"]) == 1
    item = order["items"][0]
    item_id = item["id"]
    assert item["client_item_id"] == str(client_item_id)
    assert item["product_name"] == "Cappuccino"
    assert item["variant_name"] == "350 ml"
    assert item["base_price_minor"] == "180000"
    assert item["modifier_price_minor"] == "80000"
    assert item["unit_price_minor"] == "260000"
    assert item["quantity"] == 2
    assert item["line_total_minor"] == "520000"
    assert {value["modifier_option_name"] for value in item["modifiers"]} == {
        "Oat",
        "Extra shot",
    }
    components = {
        value["inventory_item_name"]: value["quantity_per_unit"]
        for value in item["components"]
    }
    assert components == {
        "Coffee": "36",
        "Oat Milk": "230",
        "Cup": "1",
        "Lid": "1",
    }

    duplicate_item = await client.post(
        f"/api/v1/sales/orders/{order_id}/items",
        headers=headers,
        json={
            "client_item_id": str(client_item_id),
            "variant_id": str(variant_id),
            "selected_option_ids": [str(ids["regular"])],
            "quantity": 99,
        },
    )
    assert duplicate_item.status_code == 201, duplicate_item.text
    assert len(duplicate_item.json()["items"]) == 1
    assert duplicate_item.json()["items"][0]["line_total_minor"] == "520000"

    renamed = await client.patch(
        f"/api/v1/menu/products/{product_id}",
        headers=headers,
        json={"name": "Renamed Cappuccino"},
    )
    repriced = await client.patch(
        f"/api/v1/menu/variants/{variant_id}",
        headers=headers,
        json={"base_price_minor": 200000},
    )
    rerecipe = await client.put(
        f"/api/v1/menu/variants/{variant_id}/recipe",
        headers=headers,
        json={
            "components": [
                {"inventory_item_id": str(ids["Coffee"]), "quantity": "20", "unit": "g"},
                {"inventory_item_id": str(ids["Milk"]), "quantity": "230", "unit": "ml"},
                {"inventory_item_id": str(ids["Cup"]), "quantity": "1", "unit": "pcs"},
                {"inventory_item_id": str(ids["Lid"]), "quantity": "1", "unit": "pcs"},
            ]
        },
    )
    assert renamed.status_code == repriced.status_code == rerecipe.status_code == 200
    assert (
        await client.post(
            f"/api/v1/menu/modifier-options/{ids['shot']}/archive", headers=headers
        )
    ).status_code == 200
    stable = (await client.get(f"/api/v1/sales/orders/{order_id}", headers=headers)).json()
    stable_item = stable["items"][0]
    assert stable_item["product_name"] == "Cappuccino"
    assert stable_item["unit_price_minor"] == "260000"
    assert stable_item["components"] == item["components"]
    assert stable_item["modifiers"] == item["modifiers"]

    quantity = await client.patch(
        f"/api/v1/sales/orders/{order_id}/items/{item_id}",
        headers=headers,
        json={"quantity": 3},
    )
    assert quantity.status_code == 200, quantity.text
    assert quantity.json()["items"][0]["unit_price_minor"] == "260000"
    assert quantity.json()["items"][0]["line_total_minor"] == "780000"
    assert quantity.json()["total_minor"] == "780000"

    reconfigured = await client.put(
        f"/api/v1/sales/orders/{order_id}/items/{item_id}/configuration",
        headers=headers,
        json={"selected_option_ids": [str(ids["regular"])]},
    )
    assert reconfigured.status_code == 200, reconfigured.text
    assert reconfigured.json()["items"][0]["unit_price_minor"] == "200000"
    assert reconfigured.json()["items"][0]["line_total_minor"] == "600000"
    assert reconfigured.json()["total_minor"] == "600000"

    removed = await client.delete(
        f"/api/v1/sales/orders/{order_id}/items/{item_id}", headers=headers
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["items"] == []
    assert removed.json()["subtotal_minor"] == removed.json()["total_minor"] == "0"
    cancelled = await client.post(
        f"/api/v1/sales/orders/{order_id}/cancel",
        headers=headers,
        json={"reason": "Customer cancelled"},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "CANCELLED"
    immutable = await client.patch(
        f"/api/v1/sales/orders/{order_id}", headers=headers, json={"note": "No"}
    )
    _coded_error(immutable, 409, "ORDER_IMMUTABLE")
    closed = await client.post(
        f"/api/v1/cash/drawers/{shift['drawer_session_id']}/close",
        headers=headers,
        json={"client_close_id": str(uuid4()), "actual_cash_minor": "0"},
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["drawer"]["status"] == "CLOSED"
    closed_order = await client.post(
        "/api/v1/sales/orders",
        headers=headers,
        json={**payload, "client_order_id": str(uuid4())},
    )
    assert closed_order.status_code == 409

    movements = await client.get("/api/v1/inventory/transactions", headers=headers)
    assert movements.status_code == 200, movements.text
    assert movements.json() == []


@pytest.mark.anyio
async def test_sales_tenant_location_rbac_register_and_product_availability(
    app_client, monkeypatch
) -> None:
    client, _ = app_client
    headers_a, organization_a, location_a, warehouse_a = await _workspace(
        client, "sales-a@example.com", "Sales A"
    )
    headers_b, _, location_b, warehouse_b = await _workspace(
        client, "sales-b@example.com", "Sales B"
    )
    product_a, variant_a, ids = await _sellable_cappuccino(client, headers_a)
    second_location = await client.post(
        f"/api/v1/organizations/{organization_a}/locations",
        headers=headers_a,
        json={"name": "Mega", "timezone": "Asia/Almaty"},
    )
    assert second_location.status_code == 201, second_location.text
    second_warehouse = await client.post(
        "/api/v1/inventory/warehouses",
        headers=headers_a,
        json={"location_id": second_location.json()["id"], "name": "Mega Main"},
    )
    assert second_warehouse.status_code == 201, second_warehouse.text
    inactive_register = await client.post(
        "/api/v1/sales/registers",
        headers=headers_a,
        json={"location_id": str(location_a), "name": "Inactive"},
    )
    assert inactive_register.status_code == 201, inactive_register.text
    deactivated = await client.post(
        f"/api/v1/sales/registers/{inactive_register.json()['id']}/deactivate",
        headers=headers_a,
    )
    assert deactivated.status_code == 200, deactivated.text
    inactive_shift = await client.post(
        "/api/v1/sales/shifts/open",
        headers=headers_a,
        json={
            "register_id": inactive_register.json()["id"],
            "warehouse_id": str(warehouse_a),
        },
    )
    assert inactive_shift.status_code == 409
    wrong_warehouse_register = await client.post(
        "/api/v1/sales/registers",
        headers=headers_a,
        json={"location_id": str(location_a), "name": "Wrong warehouse"},
    )
    assert wrong_warehouse_register.status_code == 201
    wrong_location = await client.post(
        "/api/v1/sales/shifts/open",
        headers=headers_a,
        json={
            "register_id": wrong_warehouse_register.json()["id"],
            "warehouse_id": second_warehouse.json()["id"],
        },
    )
    assert wrong_location.status_code == 409
    register_a, shift_a = await _register_and_shift(
        client, headers_a, location_a, warehouse_a
    )
    _, second_shift = await _register_and_shift(
        client,
        headers_a,
        UUID(second_location.json()["id"]),
        UUID(second_warehouse.json()["id"]),
    )
    second_location_order = await client.post(
        "/api/v1/sales/orders",
        headers=headers_a,
        json={
            "client_order_id": str(uuid4()),
            "shift_id": second_shift["id"],
            "order_type": "DELIVERY",
            "note": "Second location",
        },
    )
    assert second_location_order.status_code == 201, second_location_order.text
    register_b, shift_b = await _register_and_shift(
        client, headers_b, location_b, warehouse_b
    )
    foreign_location = await client.post(
        "/api/v1/sales/registers",
        headers=headers_a,
        json={"location_id": str(location_b), "name": "Foreign"},
    )
    assert foreign_location.status_code in {403, 404}
    foreign_warehouse = await client.post(
        "/api/v1/sales/shifts/open",
        headers=headers_a,
        json={"register_id": register_a["id"], "warehouse_id": str(warehouse_b)},
    )
    assert foreign_warehouse.status_code in {403, 404, 409}
    assert (
        await client.get(
            f"/api/v1/sales/orders/{uuid4()}", headers=headers_a
        )
    ).status_code == 404
    foreign_shift = await client.post(
        "/api/v1/sales/orders",
        headers=headers_a,
        json={
            "client_order_id": str(uuid4()),
            "shift_id": shift_b["id"],
            "order_type": "TAKEAWAY",
        },
    )
    assert foreign_shift.status_code == 404

    order = await client.post(
        "/api/v1/sales/orders",
        headers=headers_a,
        json={
            "client_order_id": str(uuid4()),
            "shift_id": shift_a["id"],
            "order_type": "DINE_IN",
            "guest_count": 2,
            "table_label": "A1",
        },
    )
    assert order.status_code == 201, order.text
    assert (
        await client.get(
            f"/api/v1/sales/orders/{order.json()['id']}", headers=headers_b
        )
    ).status_code == 404

    hidden = await client.put(
        f"/api/v1/menu/products/{product_a}/locations/{location_a}",
        headers=headers_a,
        json={"is_available": True, "is_visible": False},
    )
    assert hidden.status_code == 200, hidden.text
    hidden_sale = await client.post(
        f"/api/v1/sales/orders/{order.json()['id']}/items",
        headers=headers_a,
        json={
            "client_item_id": str(uuid4()),
            "variant_id": str(variant_a),
            "selected_option_ids": [str(ids["regular"])],
            "quantity": 1,
        },
    )
    assert hidden_sale.status_code == 201, hidden_sale.text
    hidden_item_id = hidden_sale.json()["items"][0]["id"]
    assert (await client.get("/api/v1/inventory/transactions", headers=headers_a)).json() == []
    unavailable = await client.put(
        f"/api/v1/menu/products/{product_a}/locations/{location_a}",
        headers=headers_a,
        json={"is_available": False, "is_visible": True},
    )
    assert unavailable.status_code == 200, unavailable.text
    rejected = await client.post(
        f"/api/v1/sales/orders/{order.json()['id']}/items",
        headers=headers_a,
        json={
            "client_item_id": str(uuid4()),
            "variant_id": str(variant_a),
            "selected_option_ids": [str(ids["regular"])],
            "quantity": 1,
        },
    )
    _coded_error(rejected, 422, "PRODUCT_UNAVAILABLE")
    cancelled = await client.post(
        f"/api/v1/sales/orders/{order.json()['id']}/cancel",
        headers=headers_a,
        json={"reason": "No sale"},
    )
    assert cancelled.status_code == 200, cancelled.text
    for response in (
        await client.patch(
            f"/api/v1/sales/orders/{order.json()['id']}/items/{hidden_item_id}",
            headers=headers_a,
            json={"quantity": 2},
        ),
        await client.put(
            f"/api/v1/sales/orders/{order.json()['id']}/items/{hidden_item_id}/configuration",
            headers=headers_a,
            json={"selected_option_ids": [str(ids["regular"])]},
        ),
        await client.delete(
            f"/api/v1/sales/orders/{order.json()['id']}/items/{hidden_item_id}",
            headers=headers_a,
        ),
    ):
        _coded_error(response, 409, "ORDER_IMMUTABLE")
    assert (await client.get("/api/v1/inventory/transactions", headers=headers_a)).json() == []

    invitation_tokens = iter(
        (
            "sales-cashier-invitation-token-with-more-than-thirty-two-characters",
            "sales-barista-invitation-token-with-more-than-thirty-two-characters",
            "sales-manager-invitation-token-with-more-than-thirty-two-characters",
        )
    )

    def token_pair():
        token = next(invitation_tokens)
        return token, sha256(token.encode()).hexdigest()

    monkeypatch.setattr(
        "beanly.modules.organizations.application.services.invitation_service.create_invitation_token",
        token_pair,
    )
    cashier = await _user(client, "sales-cashier@example.com")
    invited = await client.post(
        "/api/v1/team/invitations",
        headers=headers_a,
        json={
            "email": "sales-cashier@example.com",
            "role": "CASHIER",
            "location_ids": [str(location_a)],
        },
    )
    assert invited.status_code == 201, invited.text
    cashier_token = "sales-cashier-invitation-token-with-more-than-thirty-two-characters"
    assert (
        await client.post(f"/api/v1/invitations/{cashier_token}/accept", headers=cashier)
    ).status_code == 204
    cashier_headers = {**cashier, "X-Organization-ID": str(organization_a)}
    context = await client.get("/api/v1/organizations/context", headers=cashier_headers)
    assert "sales.read_own" in context.json()["permissions"]
    assert "sales.register.manage" not in context.json()["permissions"]
    barista = await _user(client, "sales-barista@example.com")
    barista_invited = await client.post(
        "/api/v1/team/invitations",
        headers=headers_a,
        json={
            "email": "sales-barista@example.com",
            "role": "BARISTA",
            "location_ids": [str(location_a)],
        },
    )
    assert barista_invited.status_code == 201, barista_invited.text
    barista_token = "sales-barista-invitation-token-with-more-than-thirty-two-characters"
    assert (
        await client.post(f"/api/v1/invitations/{barista_token}/accept", headers=barista)
    ).status_code == 204
    barista_headers = {**barista, "X-Organization-ID": str(organization_a)}
    for staff_headers in (cashier_headers, barista_headers):
        registers = await client.get(
            "/api/v1/sales/registers",
            headers=staff_headers,
            params={"location_id": str(location_a)},
        )
        assert registers.status_code == 200, registers.text
        assert register_a["id"] in {value["id"] for value in registers.json()}
        assert (
            await client.get(
                f"/api/v1/sales/orders/{order.json()['id']}", headers=staff_headers
            )
        ).status_code == 403
        assert (
            await client.get(
                f"/api/v1/sales/orders/{second_location_order.json()['id']}",
                headers=staff_headers,
            )
        ).status_code == 403
        assert (
            await client.post(
                "/api/v1/sales/registers",
                headers=staff_headers,
                json={"location_id": str(location_a), "name": "Forbidden"},
            )
        ).status_code == 403
        assert (
            await client.patch(
                f"/api/v1/sales/registers/{register_a['id']}",
                headers=staff_headers,
                json={"name": "Forbidden"},
            )
        ).status_code == 403
        assert (
            await client.post(
                f"/api/v1/sales/registers/{register_a['id']}/deactivate",
                headers=staff_headers,
            )
        ).status_code == 403

    cashier_order = await client.post(
        "/api/v1/sales/orders",
        headers=cashier_headers,
        json={
            "client_order_id": str(uuid4()),
            "shift_id": shift_a["id"],
            "order_type": "TAKEAWAY",
        },
    )
    assert cashier_order.status_code == 201, cashier_order.text
    cashier_orders = await client.get("/api/v1/sales/orders", headers=cashier_headers)
    assert cashier_orders.status_code == 200, cashier_orders.text
    assert [value["id"] for value in cashier_orders.json()] == [cashier_order.json()["id"]]

    manager = await _user(client, "sales-manager@example.com")
    manager_invited = await client.post(
        "/api/v1/team/invitations",
        headers=headers_a,
        json={
            "email": "sales-manager@example.com",
            "role": "MANAGER",
            "location_ids": [str(location_a), second_location.json()["id"]],
        },
    )
    assert manager_invited.status_code == 201, manager_invited.text
    manager_token = "sales-manager-invitation-token-with-more-than-thirty-two-characters"
    assert (
        await client.post(f"/api/v1/invitations/{manager_token}/accept", headers=manager)
    ).status_code == 204
    manager_headers = {**manager, "X-Organization-ID": str(organization_a)}
    manager_orders = await client.get("/api/v1/sales/orders", headers=manager_headers)
    assert manager_orders.status_code == 200, manager_orders.text
    assert {
        order.json()["id"],
        second_location_order.json()["id"],
        cashier_order.json()["id"],
    } <= {value["id"] for value in manager_orders.json()}


def test_sales_openapi_never_accepts_client_money_or_snapshots() -> None:
    from beanly.main import app

    document = app.openapi()
    paths = document["paths"]
    expected = {
        "/api/v1/sales/registers": {"get", "post"},
        "/api/v1/sales/registers/{register_id}": {"patch"},
        "/api/v1/sales/registers/{register_id}/deactivate": {"post"},
        "/api/v1/sales/warehouses": {"get"},
        "/api/v1/sales/shifts/open": {"post"},
        "/api/v1/sales/shifts/current": {"get"},
        "/api/v1/sales/shifts/{shift_id}/close": {"post"},
        "/api/v1/sales/orders": {"get", "post"},
        "/api/v1/sales/orders/{order_id}": {"get", "patch"},
        "/api/v1/sales/orders/{order_id}/cancel": {"post"},
        "/api/v1/sales/orders/{order_id}/items": {"post"},
        "/api/v1/sales/orders/{order_id}/items/{item_id}": {"patch", "delete"},
        "/api/v1/sales/orders/{order_id}/items/{item_id}/configuration": {"put"},
    }
    for path, operations in expected.items():
        assert operations <= paths[path].keys()
    assert "delete" not in paths["/api/v1/sales/orders/{order_id}"]
    add_item_operation = paths["/api/v1/sales/orders/{order_id}/items"]["post"]
    schema_ref = add_item_operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    schema = document["components"]["schemas"][schema_ref.rsplit("/", 1)[-1]]
    forbidden = {
        "product_name",
        "variant_name",
        "base_price_minor",
        "modifier_price_minor",
        "unit_price_minor",
        "line_total_minor",
        "modifiers",
        "components",
    }
    assert not forbidden & schema["properties"].keys()
