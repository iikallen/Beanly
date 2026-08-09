from decimal import Decimal
from uuid import UUID

import pytest
from httpx import AsyncClient


async def _setup(client: AsyncClient, email: str, name: str = "Menu Coffee"):
    password = "correct-horse-battery-staple"
    assert (
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": password,
                "first_name": "Menu",
                "last_name": "Owner",
            },
        )
    ).status_code == 201
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    auth = {"authorization": f"Bearer {login.json()['access_token']}"}
    workspace = await client.post(
        "/api/v1/organizations",
        headers=auth,
        json={
            "name": name,
            "country_code": "KZ",
            "currency_code": "KZT",
            "first_location": {"name": "Dostyk", "timezone": "Asia/Almaty"},
        },
    )
    organization_id = UUID(workspace.json()["organization"]["id"])
    location_id = UUID(workspace.json()["location"]["id"])
    headers = {**auth, "X-Organization-ID": str(organization_id)}
    warehouse = await client.post(
        "/api/v1/inventory/warehouses",
        headers=headers,
        json={"location_id": str(location_id), "name": "Main"},
    )
    return headers, organization_id, location_id, UUID(warehouse.json()["id"])


async def _item(client: AsyncClient, headers: dict[str, str], name: str, unit: str) -> UUID:
    response = await client.post(
        "/api/v1/inventory/items",
        headers=headers,
        json={"name": name, "base_unit": unit},
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


async def _category_product(client: AsyncClient, headers: dict[str, str]):
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
    assert product.json()["status"] == "DRAFT"
    product = await client.patch(
        f"/api/v1/menu/products/{product.json()['id']}",
        headers=headers,
        json={"status": "ACTIVE"},
    )
    assert product.status_code == 200, product.text
    return (
        UUID(category.json()["id"]),
        UUID(product.json()["id"]),
        UUID(product.json()["variants"][0]["id"]),
    )


@pytest.mark.anyio
async def test_menu_recipe_cost_location_and_visibility(app_client) -> None:
    client, _ = app_client
    headers, _, location_id, warehouse_id = await _setup(client, "menu-cost@example.com")
    _, product_id, variant_id = await _category_product(client, headers)
    cannot_clear_default = await client.patch(
        f"/api/v1/menu/variants/{variant_id}",
        headers=headers,
        json={"is_default": False},
    )
    assert cannot_clear_default.status_code == 409
    ingredients = [
        ("Coffee", "g", "18", "8.5"),
        ("Milk", "ml", "230", "0.7"),
        ("Cup", "pcs", "1", "35"),
        ("Lid", "pcs", "1", "15"),
    ]
    item_ids = [await _item(client, headers, name, unit) for name, unit, _, _ in ingredients]
    recipe = await client.put(
        f"/api/v1/menu/variants/{variant_id}/recipe",
        headers=headers,
        json={
            "components": [
                {
                    "inventory_item_id": str(item_id),
                    "quantity": quantity,
                    "unit": unit,
                    "sort_order": index,
                }
                for index, (item_id, (_, unit, quantity, _)) in enumerate(
                    zip(item_ids, ingredients, strict=True)
                )
            ]
        },
    )
    assert recipe.status_code == 200, recipe.text

    opening = await client.post(
        "/api/v1/inventory/opening-balances",
        headers={**headers, "Idempotency-Key": "menu-cost-opening"},
        json={
            "warehouse_id": str(warehouse_id),
            "items": [
                {
                    "inventory_item_id": str(item_id),
                    "quantity": "1000",
                    "unit_code": unit,
                    "unit_cost_amount": cost,
                }
                for item_id, (_, unit, _, cost) in zip(item_ids, ingredients, strict=True)
            ],
        },
    )
    assert opening.status_code == 201, opening.text
    cost = await client.get(
        f"/api/v1/menu/variants/{variant_id}/cost",
        headers=headers,
        params={"warehouse_id": str(warehouse_id)},
    )
    assert cost.status_code == 200, cost.text
    body = cost.json()
    assert body["price_minor"] == "180000"
    assert body["recipe_cost"] == "364"
    assert body["gross_profit"] == "1436"
    assert body["food_cost_percent"] == "20.222222"
    assert body["gross_margin_percent"] == "79.777778"
    assert body["status"] == "COMPLETE"

    override = await client.put(
        f"/api/v1/menu/variants/{variant_id}/prices/{location_id}",
        headers=headers,
        json={"price_minor": 210000},
    )
    assert override.json()["price_minor"] == "210000"
    projected = await client.get(
        f"/api/v1/menu/products/{product_id}",
        headers=headers,
        params={"location_id": str(location_id)},
    )
    projected_variant = projected.json()["variants"][0]
    assert projected_variant["base_price_minor"] == "180000"
    assert projected_variant["location_price_minor"] == "210000"
    assert projected_variant["effective_price_minor"] == "210000"
    assert (
        await client.get(
            "/api/v1/menu/costs",
            headers=headers,
            params={"warehouse_id": str(warehouse_id), "location_id": str(location_id)},
        )
    ).json()["variants"][0]["price_minor"] == "210000"

    setting = await client.put(
        f"/api/v1/menu/products/{product_id}/locations/{location_id}",
        headers=headers,
        json={"is_available": False, "is_visible": True},
    )
    assert setting.status_code == 200
    listed = await client.get(
        "/api/v1/menu/products",
        headers=headers,
        params={"location_id": str(location_id)},
    )
    assert listed.json()[0]["is_available"] is False
    menu = await client.get(
        "/api/v1/menu", headers=headers, params={"location_id": str(location_id)}
    )
    assert menu.json()["categories"][0]["products"] == []


@pytest.mark.anyio
async def test_recipe_conversion_missing_zero_and_tenant_atomicity(app_client) -> None:
    client, _ = app_client
    headers_a, _, _, warehouse_id = await _setup(client, "menu-a@example.com", "A")
    headers_b, _, _, _ = await _setup(client, "menu-b@example.com", "B")
    _, _, variant_id = await _category_product(client, headers_a)
    milk = await _item(client, headers_a, "Milk", "ml")
    foreign = await _item(client, headers_b, "Foreign Milk", "ml")

    saved = await client.put(
        f"/api/v1/menu/variants/{variant_id}/recipe",
        headers=headers_a,
        json={
            "components": [
                {
                    "inventory_item_id": str(milk),
                    "quantity": "0.2",
                    "unit": "l",
                }
            ]
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["components"][0]["quantity"] == "200"
    missing = await client.get(
        f"/api/v1/menu/variants/{variant_id}/cost",
        headers=headers_a,
        params={"warehouse_id": str(warehouse_id)},
    )
    assert missing.json()["status"] == "INCOMPLETE"
    assert missing.json()["recipe_cost"] is None

    rejected = await client.put(
        f"/api/v1/menu/variants/{variant_id}/recipe",
        headers=headers_a,
        json={
            "components": [
                {"inventory_item_id": str(milk), "quantity": "220", "unit": "ml"},
                {"inventory_item_id": str(foreign), "quantity": "1", "unit": "ml"},
            ]
        },
    )
    assert rejected.status_code == 404
    unchanged = await client.get(f"/api/v1/menu/variants/{variant_id}/recipe", headers=headers_a)
    assert unchanged.json()["components"][0]["quantity"] == "200"

    zero = await client.post(
        "/api/v1/inventory/opening-balances",
        headers={**headers_a, "Idempotency-Key": "menu-zero-cost"},
        json={
            "warehouse_id": str(warehouse_id),
            "items": [
                {
                    "inventory_item_id": str(milk),
                    "quantity": "1",
                    "unit_code": "ml",
                    "unit_cost_amount": "0",
                }
            ],
        },
    )
    assert zero.status_code == 201, zero.text
    complete = await client.get(
        f"/api/v1/menu/variants/{variant_id}/cost",
        headers=headers_a,
        params={"warehouse_id": str(warehouse_id)},
    )
    assert complete.json()["status"] == "COMPLETE"
    assert Decimal(complete.json()["recipe_cost"]) == 0
