from collections.abc import Iterable
from uuid import UUID

import pytest
from httpx import AsyncClient


async def _workspace(
    client: AsyncClient, email: str, name: str
) -> tuple[dict[str, str], UUID, UUID, UUID]:
    password = "correct-horse-battery-staple"
    registered = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": password,
            "first_name": "Modifier",
            "last_name": "Owner",
        },
    )
    assert registered.status_code == 201, registered.text
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


async def _active_variant(
    client: AsyncClient, headers: dict[str, str]
) -> tuple[UUID, UUID]:
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
    return UUID(product.json()["id"]), UUID(product.json()["variants"][0]["id"])


async def _group(
    client: AsyncClient,
    headers: dict[str, str],
    variant_id: UUID,
    name: str,
    selection_type: str,
    minimum: int,
    maximum: int,
) -> UUID:
    response = await client.post(
        f"/api/v1/menu/variants/{variant_id}/modifier-groups",
        headers=headers,
        json={
            "name": name,
            "selection_type": selection_type,
            "min_selections": minimum,
            "max_selections": maximum,
        },
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


async def _option(
    client: AsyncClient,
    headers: dict[str, str],
    group_id: UUID,
    name: str,
    price: int = 0,
    *,
    default: bool = False,
) -> UUID:
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


async def _components(
    client: AsyncClient,
    headers: dict[str, str],
    option_id: UUID,
    values: Iterable[tuple[UUID, str, str]],
):
    response = await client.put(
        f"/api/v1/menu/modifier-options/{option_id}/components",
        headers=headers,
        json={
            "components": [
                {
                    "inventory_item_id": str(item_id),
                    "quantity_delta": quantity,
                    "unit": unit,
                    "sort_order": index,
                }
                for index, (item_id, quantity, unit) in enumerate(values)
            ]
        },
    )
    return response


def _modifier_error(response, code: str) -> None:
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == code


@pytest.mark.anyio
async def test_modifier_customization_pricing_recipe_cost_and_safe_menu_projection(
    app_client,
) -> None:
    client, _ = app_client
    headers, _, location_id, warehouse_id = await _workspace(
        client, "modifier-happy@example.com", "Modifier Happy"
    )
    product_id, variant_id = await _active_variant(client, headers)

    invalid_single = await client.post(
        f"/api/v1/menu/variants/{variant_id}/modifier-groups",
        headers=headers,
        json={
            "name": "Invalid single",
            "selection_type": "SINGLE",
            "min_selections": 0,
            "max_selections": 2,
        },
    )
    assert invalid_single.status_code == 422
    invalid_limits = await client.post(
        f"/api/v1/menu/variants/{variant_id}/modifier-groups",
        headers=headers,
        json={
            "name": "Invalid limits",
            "selection_type": "MULTIPLE",
            "min_selections": 2,
            "max_selections": 1,
        },
    )
    assert invalid_limits.status_code == 422

    milk_group = await _group(client, headers, variant_id, "Milk", "SINGLE", 1, 1)
    extras_group = await _group(client, headers, variant_id, "Extras", "MULTIPLE", 0, 3)
    regular = await _option(client, headers, milk_group, "Regular", default=True)
    oat = await _option(client, headers, milk_group, "Oat", 30000)
    extra_shot = await _option(client, headers, extras_group, "Extra shot", 50000)
    vanilla = await _option(client, headers, extras_group, "Vanilla", 20000)
    caramel = await _option(client, headers, extras_group, "Caramel", 20000)
    cinnamon = await _option(client, headers, extras_group, "Cinnamon", 10000)
    zero_cost_extra = await _option(client, headers, extras_group, "Zero-cost note")

    item_specs = (
        ("Coffee", "g", "18", "8.5"),
        ("Milk", "ml", "230", "0.7"),
        ("Cup", "pcs", "1", "35"),
        ("Lid", "pcs", "1", "15"),
        ("Oat Milk", "ml", None, "1.2"),
        ("Zero-cost marker", "pcs", None, "0"),
    )
    item_ids = {
        name: await _item(client, headers, name, unit) for name, unit, _, _ in item_specs
    }
    recipe = await client.put(
        f"/api/v1/menu/variants/{variant_id}/recipe",
        headers=headers,
        json={
            "components": [
                {
                    "inventory_item_id": str(item_ids[name]),
                    "quantity": quantity,
                    "unit": unit,
                }
                for name, unit, quantity, _ in item_specs
                if quantity is not None
            ]
        },
    )
    assert recipe.status_code == 200, recipe.text
    oat_components = await _components(
        client,
        headers,
        oat,
        (
            (item_ids["Milk"], "-230", "ml"),
            (item_ids["Oat Milk"], "0.23", "l"),
        ),
    )
    assert oat_components.status_code == 200, oat_components.text
    assert [item["quantity_delta"] for item in oat_components.json()["components"]] == [
        "-230",
        "230",
    ]
    assert (
        await _components(
            client, headers, extra_shot, ((item_ids["Coffee"], "18", "g"),)
        )
    ).status_code == 200
    assert (
        await _components(
            client,
            headers,
            zero_cost_extra,
            ((item_ids["Zero-cost marker"], "1", "pcs"),),
        )
    ).status_code == 200

    zero_delta = await _components(
        client, headers, vanilla, ((item_ids["Coffee"], "0", "g"),)
    )
    assert zero_delta.status_code == 422
    duplicate_item = await _components(
        client,
        headers,
        vanilla,
        (
            (item_ids["Coffee"], "1", "g"),
            (item_ids["Coffee"], "2", "g"),
        ),
    )
    assert duplicate_item.status_code == 409
    empty_components = await _components(client, headers, vanilla, ())
    assert empty_components.status_code == 200
    assert empty_components.json()["components"] == []

    opening = await client.post(
        "/api/v1/inventory/opening-balances",
        headers={**headers, "Idempotency-Key": "modifier-costs"},
        json={
            "warehouse_id": str(warehouse_id),
            "items": [
                {
                    "inventory_item_id": str(item_ids[name]),
                    "quantity": "1000",
                    "unit_code": unit,
                    "unit_cost_amount": cost,
                }
                for name, unit, _, cost in item_specs
            ],
        },
    )
    assert opening.status_code == 201, opening.text

    missing_required = await client.post(
        f"/api/v1/menu/variants/{variant_id}/customization-preview",
        headers=headers,
        params={"warehouse_id": str(warehouse_id), "location_id": str(location_id)},
        json={"selected_option_ids": []},
    )
    _modifier_error(missing_required, "INVALID_MODIFIER_SELECTION")
    duplicate_selection = await client.post(
        f"/api/v1/menu/variants/{variant_id}/customization-preview",
        headers=headers,
        params={"warehouse_id": str(warehouse_id), "location_id": str(location_id)},
        json={"selected_option_ids": [str(regular), str(regular)]},
    )
    _modifier_error(duplicate_selection, "INVALID_MODIFIER_SELECTION")
    too_many_single = await client.post(
        f"/api/v1/menu/variants/{variant_id}/customization-preview",
        headers=headers,
        params={"warehouse_id": str(warehouse_id), "location_id": str(location_id)},
        json={"selected_option_ids": [str(regular), str(oat)]},
    )
    _modifier_error(too_many_single, "INVALID_MODIFIER_SELECTION")
    too_many_extras = await client.post(
        f"/api/v1/menu/variants/{variant_id}/customization-preview",
        headers=headers,
        params={"warehouse_id": str(warehouse_id), "location_id": str(location_id)},
        json={
            "selected_option_ids": [
                str(regular),
                str(extra_shot),
                str(vanilla),
                str(caramel),
                str(cinnamon),
            ]
        },
    )
    _modifier_error(too_many_extras, "INVALID_MODIFIER_SELECTION")

    preview = await client.post(
        f"/api/v1/menu/variants/{variant_id}/customization-preview",
        headers=headers,
        params={"warehouse_id": str(warehouse_id), "location_id": str(location_id)},
        json={"selected_option_ids": [str(oat), str(extra_shot)]},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["base_price_minor"] == "180000"
    assert body["modifier_price_minor"] == "80000"
    assert body["final_price_minor"] == "260000"
    assert body["base_recipe_cost"] == "364"
    assert body["modifier_cost_delta"] == "268"
    assert body["final_cost"] == "632"
    assert body["food_cost_percent"] == "24.307692"
    assert body["gross_profit"] == "1968"
    assert body["gross_margin_percent"] == "75.692308"
    assert body["status"] == "COMPLETE"
    quantities = {
        UUID(value["inventory_item_id"]): value["quantity"]
        for value in body["effective_components"]
    }
    assert quantities[item_ids["Coffee"]] == "36"
    assert quantities[item_ids["Milk"]] == "0"
    assert quantities[item_ids["Oat Milk"]] == "230"
    zero_wac = await client.post(
        f"/api/v1/menu/variants/{variant_id}/customization-preview",
        headers=headers,
        params={"warehouse_id": str(warehouse_id), "location_id": str(location_id)},
        json={"selected_option_ids": [str(regular), str(zero_cost_extra)]},
    )
    assert zero_wac.status_code == 200, zero_wac.text
    assert zero_wac.json()["status"] == "COMPLETE"
    zero_component = next(
        value
        for value in zero_wac.json()["effective_components"]
        if value["inventory_item_id"] == str(item_ids["Zero-cost marker"])
    )
    assert zero_component["unit_cost"] == "0"
    assert zero_component["cost"] == "0"

    price = await client.put(
        f"/api/v1/menu/modifier-options/{oat}/prices/{location_id}",
        headers=headers,
        json={"price_delta_minor": 45000},
    )
    assert price.status_code == 200, price.text
    airport_preview = await client.post(
        f"/api/v1/menu/variants/{variant_id}/customization-preview",
        headers=headers,
        params={"warehouse_id": str(warehouse_id), "location_id": str(location_id)},
        json={"selected_option_ids": [str(oat), str(extra_shot)]},
    )
    assert airport_preview.json()["modifier_price_minor"] == "95000"
    assert airport_preview.json()["final_price_minor"] == "275000"
    removed = await client.delete(
        f"/api/v1/menu/modifier-options/{oat}/prices/{location_id}", headers=headers
    )
    assert removed.status_code == 200
    assert removed.json()["price_delta_minor"] is None
    base_fallback = await client.post(
        f"/api/v1/menu/variants/{variant_id}/customization-preview",
        headers=headers,
        params={"warehouse_id": str(warehouse_id), "location_id": str(location_id)},
        json={"selected_option_ids": [str(oat), str(extra_shot)]},
    )
    assert base_fallback.json()["modifier_price_minor"] == "80000"
    assert base_fallback.json()["final_price_minor"] == "260000"

    unavailable = await client.put(
        f"/api/v1/menu/modifier-options/{oat}/locations/{location_id}",
        headers=headers,
        json={"is_available": False},
    )
    assert unavailable.status_code == 200
    rejected = await client.post(
        f"/api/v1/menu/variants/{variant_id}/customization-preview",
        headers=headers,
        params={"warehouse_id": str(warehouse_id), "location_id": str(location_id)},
        json={"selected_option_ids": [str(oat)]},
    )
    _modifier_error(rejected, "INVALID_MODIFIER_SELECTION")
    unavailable_menu = await client.get(
        "/api/v1/menu", headers=headers, params={"location_id": str(location_id)}
    )
    unavailable_variants = unavailable_menu.json()["categories"][0]["products"][0]["variants"]
    unavailable_oat = next(
        option
        for group in unavailable_variants[0]["modifier_groups"]
        for option in group["options"]
        if option["id"] == str(oat)
    )
    assert unavailable_oat["is_available"] is False
    assert (
        await client.put(
            f"/api/v1/menu/modifier-options/{oat}/locations/{location_id}",
            headers=headers,
            json={"is_available": True},
        )
    ).status_code == 200

    menu = await client.get(
        "/api/v1/menu", headers=headers, params={"location_id": str(location_id)}
    )
    assert menu.status_code == 200, menu.text
    projected_variant = menu.json()["categories"][0]["products"][0]["variants"][0]
    assert projected_variant["id"] == str(variant_id)
    assert len(projected_variant["modifier_groups"]) == 2
    projected_option = projected_variant["modifier_groups"][0]["options"][0]
    assert "components" not in projected_option
    assert {
        "id",
        "name",
        "effective_price_delta_minor",
        "is_available",
    } <= projected_option.keys()
    product = await client.get(f"/api/v1/menu/products/{product_id}", headers=headers)
    assert product.status_code == 200


@pytest.mark.anyio
async def test_modifier_negative_recipe_missing_wac_tenant_isolation_and_atomic_replacement(
    app_client,
) -> None:
    client, _ = app_client
    headers_a, _, location_a, warehouse_a = await _workspace(
        client, "modifier-a@example.com", "Modifier A"
    )
    headers_b, _, location_b, _ = await _workspace(
        client, "modifier-b@example.com", "Modifier B"
    )
    _, variant_a = await _active_variant(client, headers_a)
    _, variant_b = await _active_variant(client, headers_b)
    milk = await _item(client, headers_a, "Milk", "ml")
    syrup = await _item(client, headers_a, "Syrup", "ml")
    foreign = await _item(client, headers_b, "Foreign Milk", "ml")
    recipe = await client.put(
        f"/api/v1/menu/variants/{variant_a}/recipe",
        headers=headers_a,
        json={
            "components": [
                {"inventory_item_id": str(milk), "quantity": "230", "unit": "ml"}
            ]
        },
    )
    assert recipe.status_code == 200, recipe.text
    opening = await client.post(
        "/api/v1/inventory/opening-balances",
        headers={**headers_a, "Idempotency-Key": "modifier-a-cost"},
        json={
            "warehouse_id": str(warehouse_a),
            "items": [
                {
                    "inventory_item_id": str(milk),
                    "quantity": "1000",
                    "unit_code": "ml",
                    "unit_cost_amount": "0.7",
                }
            ],
        },
    )
    assert opening.status_code == 201, opening.text
    group = await _group(client, headers_a, variant_a, "Changes", "MULTIPLE", 0, 2)
    negative = await _option(client, headers_a, group, "Remove too much")
    missing = await _option(client, headers_a, group, "Syrup")
    saved = await _components(client, headers_a, negative, ((milk, "-500", "ml"),))
    assert saved.status_code == 200, saved.text
    assert (
        await _components(client, headers_a, missing, ((syrup, "10", "ml"),))
    ).status_code == 200

    negative_preview = await client.post(
        f"/api/v1/menu/variants/{variant_a}/customization-preview",
        headers=headers_a,
        params={"warehouse_id": str(warehouse_a), "location_id": str(location_a)},
        json={"selected_option_ids": [str(negative)]},
    )
    _modifier_error(negative_preview, "INVALID_MODIFIER_RECIPE")
    incomplete = await client.post(
        f"/api/v1/menu/variants/{variant_a}/customization-preview",
        headers=headers_a,
        params={"warehouse_id": str(warehouse_a), "location_id": str(location_a)},
        json={"selected_option_ids": [str(missing)]},
    )
    assert incomplete.status_code == 200, incomplete.text
    assert incomplete.json()["status"] == "INCOMPLETE"
    assert incomplete.json()["final_cost"] is None
    assert incomplete.json()["missing_cost_items"] == ["Syrup"]

    foreign_group = await client.post(
        f"/api/v1/menu/variants/{variant_b}/modifier-groups",
        headers=headers_a,
        json={
            "name": "Cross tenant",
            "selection_type": "SINGLE",
            "min_selections": 0,
            "max_selections": 1,
        },
    )
    assert foreign_group.status_code == 404
    rejected_components = await _components(
        client,
        headers_a,
        missing,
        ((milk, "20", "ml"), (foreign, "5", "ml")),
    )
    assert rejected_components.status_code == 404
    unchanged = await client.get(
        f"/api/v1/menu/variants/{variant_a}/modifier-groups", headers=headers_a
    )
    option = next(
        value
        for value in unchanged.json()[0]["options"]
        if value["id"] == str(missing)
    )
    assert option["components"] == [
        {
            "inventory_item_id": str(syrup),
            "item_name": "Syrup",
            "base_unit": "ml",
            "quantity_delta": "10",
            "sort_order": 0,
        }
    ]
    cross_location = await client.put(
        f"/api/v1/menu/modifier-options/{missing}/prices/{location_b}",
        headers=headers_a,
        json={"price_delta_minor": 100},
    )
    assert cross_location.status_code == 403

    archived = await client.post(
        f"/api/v1/menu/modifier-options/{missing}/archive", headers=headers_a
    )
    assert archived.status_code == 200
    assert archived.json()["is_active"] is False
    cannot_mutate = await _components(client, headers_a, missing, ())
    assert cannot_mutate.status_code == 409
    archived_group = await client.post(
        f"/api/v1/menu/modifier-groups/{group}/archive", headers=headers_a
    )
    assert archived_group.status_code == 200
    assert archived_group.json()["is_active"] is False


def test_modifier_openapi_contract_and_read_model_hide_recipe_deltas() -> None:
    from beanly.main import app

    paths = app.openapi()["paths"]
    expected = {
        "/api/v1/menu/variants/{variant_id}/modifier-groups": {"get", "post"},
        "/api/v1/menu/modifier-groups/{group_id}": {"patch"},
        "/api/v1/menu/modifier-groups/{group_id}/archive": {"post"},
        "/api/v1/menu/modifier-groups/{group_id}/options": {"post"},
        "/api/v1/menu/modifier-options/{option_id}": {"patch"},
        "/api/v1/menu/modifier-options/{option_id}/archive": {"post"},
        "/api/v1/menu/modifier-options/{option_id}/components": {"put"},
        "/api/v1/menu/modifier-options/{option_id}/prices/{location_id}": {
            "put",
            "delete",
        },
        "/api/v1/menu/modifier-options/{option_id}/locations/{location_id}": {"put"},
        "/api/v1/menu/variants/{variant_id}/customization-preview": {"post"},
    }
    for path, operations in expected.items():
        assert path in paths
        assert operations <= paths[path].keys()

    menu_schema = app.openapi()["components"]["schemas"]["ModifierOptionMenuResponse"]
    assert "components" not in menu_schema["properties"]
