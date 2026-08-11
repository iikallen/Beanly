from hashlib import sha256
from uuid import uuid4

import pytest
from httpx import AsyncClient


async def _user(client: AsyncClient, email: str, first_name: str) -> dict[str, str]:
    password = "correct-horse-battery-staple"
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": password,
            "first_name": first_name,
            "last_name": "Beanly",
        },
    )
    assert response.status_code == 201
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200
    return {"authorization": f"Bearer {login.json()['access_token']}"}


async def _workspace(client: AsyncClient, owner: dict[str, str]) -> tuple[dict[str, str], str, str]:
    response = await client.post(
        "/api/v1/organizations",
        headers=owner,
        json={
            "name": "RBAC Coffee",
            "country_code": "KZ",
            "currency_code": "KZT",
            "first_location": {
                "name": "Dostyk",
                "timezone": "Asia/Almaty",
            },
        },
    )
    assert response.status_code == 201
    body = response.json()
    organization_id = body["organization"]["id"]
    location_id = body["location"]["id"]
    return (
        {**owner, "X-Organization-ID": organization_id},
        organization_id,
        location_id,
    )


async def _invite_and_accept(
    client: AsyncClient,
    owner_headers: dict[str, str],
    member_headers: dict[str, str],
    email: str,
    role: str,
    location_id: str,
    token: str,
) -> None:
    invited = await client.post(
        "/api/v1/team/invitations",
        headers=owner_headers,
        json={"email": email, "role": role, "location_ids": [location_id]},
    )
    assert invited.status_code == 201
    accepted = await client.post(f"/api/v1/invitations/{token}/accept", headers=member_headers)
    assert accepted.status_code == 204


@pytest.mark.anyio
async def test_owner_admin_manager_and_barista_api_permissions(app_client, monkeypatch) -> None:
    client, _ = app_client
    raw_tokens = iter(
        [
            "rbac-admin-token-with-more-than-thirty-two-characters",
            "rbac-manager-token-with-more-than-thirty-two-characters",
            "rbac-barista-token-with-more-than-thirty-two-characters",
            "rbac-accountant-token-with-more-than-thirty-two-characters",
            "rbac-cashier-token-with-more-than-thirty-two-characters",
            "rbac-admin-created-invite-with-more-than-thirty-two-characters",
            "rbac-forbidden-location-invite-with-more-than-thirty-two-characters",
        ]
    )

    def token_pair() -> tuple[str, str]:
        token = next(raw_tokens)
        return token, sha256(token.encode()).hexdigest()

    monkeypatch.setattr(
        "beanly.modules.organizations.application.services.invitation_service."
        "create_invitation_token",
        token_pair,
    )

    owner = await _user(client, "rbac-owner@example.com", "Owner")
    owner_headers, organization_id, location_id = await _workspace(client, owner)
    second_location = await client.post(
        f"/api/v1/organizations/{organization_id}/locations",
        headers=owner,
        json={"name": "Mega", "timezone": "Asia/Almaty"},
    )
    assert second_location.status_code == 201
    second_location_id = second_location.json()["id"]
    admin = await _user(client, "rbac-admin@example.com", "Admin")
    manager = await _user(client, "rbac-manager@example.com", "Manager")
    barista = await _user(client, "rbac-barista@example.com", "Barista")
    accountant = await _user(client, "rbac-accountant@example.com", "Accountant")
    cashier = await _user(client, "rbac-cashier@example.com", "Cashier")

    await _invite_and_accept(
        client,
        owner_headers,
        admin,
        "rbac-admin@example.com",
        "ADMIN",
        location_id,
        "rbac-admin-token-with-more-than-thirty-two-characters",
    )
    await _invite_and_accept(
        client,
        owner_headers,
        manager,
        "rbac-manager@example.com",
        "MANAGER",
        location_id,
        "rbac-manager-token-with-more-than-thirty-two-characters",
    )
    await _invite_and_accept(
        client,
        owner_headers,
        barista,
        "rbac-barista@example.com",
        "BARISTA",
        location_id,
        "rbac-barista-token-with-more-than-thirty-two-characters",
    )
    await _invite_and_accept(
        client,
        owner_headers,
        accountant,
        "rbac-accountant@example.com",
        "ACCOUNTANT",
        location_id,
        "rbac-accountant-token-with-more-than-thirty-two-characters",
    )
    await _invite_and_accept(
        client,
        owner_headers,
        cashier,
        "rbac-cashier@example.com",
        "CASHIER",
        location_id,
        "rbac-cashier-token-with-more-than-thirty-two-characters",
    )

    admin_headers = {**admin, "X-Organization-ID": organization_id}
    manager_headers = {**manager, "X-Organization-ID": organization_id}
    barista_headers = {**barista, "X-Organization-ID": organization_id}
    accountant_headers = {**accountant, "X-Organization-ID": organization_id}
    cashier_headers = {**cashier, "X-Organization-ID": organization_id}

    for headers, role in (
        (owner_headers, "Owner"),
        (admin_headers, "Admin"),
        (accountant_headers, "Accountant"),
    ):
        assert (await client.get("/api/v1/finance/accounts", headers=headers)).status_code == 200
        assert (
            await client.post(
                "/api/v1/finance/expense-categories",
                headers=headers,
                json={"name": f"{role} finance"},
            )
        ).status_code == 201
    for headers in (manager_headers, cashier_headers, barista_headers):
        assert (await client.get("/api/v1/finance/accounts", headers=headers)).status_code == 403
        assert (
            await client.post(
                "/api/v1/finance/expense-categories",
                headers=headers,
                json={"name": "Forbidden finance"},
            )
        ).status_code == 403

    for headers, role in (
        (accountant_headers, "ACCOUNTANT"),
        (cashier_headers, "CASHIER"),
        (barista_headers, "BARISTA"),
    ):
        own_context = await client.get("/api/v1/organizations/context", headers=headers)
        assert own_context.status_code == 200, own_context.text
        assert own_context.json()["role"] == role
        assert own_context.json()["organization_id"] == organization_id
        assert own_context.json()["location_ids"] == [location_id]
        assert "menu.read" in own_context.json()["permissions"]
        assert "team.read" not in own_context.json()["permissions"]
        assert (await client.get("/api/v1/team", headers=headers)).status_code == 403

    warehouse = await client.post(
        "/api/v1/inventory/warehouses",
        headers=owner_headers,
        json={"location_id": location_id, "name": "RBAC Main"},
    )
    assert warehouse.status_code == 201
    item = await client.post(
        "/api/v1/inventory/items",
        headers=owner_headers,
        json={"name": "RBAC Beans", "base_unit": "g"},
    )
    assert item.status_code == 201
    opening = await client.post(
        "/api/v1/inventory/opening-balances",
        headers=owner_headers,
        json={
            "warehouse_id": warehouse.json()["id"],
            "items": [
                {
                    "inventory_item_id": item.json()["id"],
                    "quantity": "1000",
                    "unit_code": "g",
                }
            ],
        },
    )
    assert opening.status_code == 201
    assert (
        await client.get("/api/v1/inventory/warehouses", headers=barista_headers)
    ).status_code == 200
    assert (await client.get("/api/v1/inventory/items", headers=barista_headers)).status_code == 200
    limited_stock = await client.get("/api/v1/inventory/stock", headers=barista_headers)
    assert limited_stock.status_code == 200
    assert limited_stock.json()[0]["average_unit_cost"] is None
    assert limited_stock.json()[0]["inventory_value"] is None
    limited_item = await client.get(
        f"/api/v1/inventory/items/{item.json()['id']}/stock",
        params={"warehouse_id": warehouse.json()["id"]},
        headers=barista_headers,
    )
    assert limited_item.status_code == 200
    assert limited_item.json()["average_unit_cost"] is None
    assert (
        await client.get("/api/v1/inventory/valuation", headers=barista_headers)
    ).status_code == 403
    assert (
        await client.get(
            f"/api/v1/inventory/items/{item.json()['id']}/movements",
            headers=barista_headers,
        )
    ).status_code == 403
    assert (
        await client.get("/api/v1/inventory/transactions", headers=barista_headers)
    ).status_code == 403
    assert (
        await client.get(
            f"/api/v1/inventory/transactions/{opening.json()['id']}",
            headers=barista_headers,
        )
    ).status_code == 403

    assert (await client.get("/api/v1/team", headers=manager_headers)).status_code == 200
    manager_locations = await client.get(
        f"/api/v1/organizations/{organization_id}/locations", headers=manager
    )
    assert manager_locations.status_code == 200
    assert [location["id"] for location in manager_locations.json()] == [location_id]
    assert (
        await client.get(
            f"/api/v1/organizations/{organization_id}/locations/{second_location_id}",
            headers=manager,
        )
    ).status_code == 404
    assert (
        await client.patch(
            f"/api/v1/organizations/{organization_id}",
            headers=manager,
            json={"name": "Escalated Coffee"},
        )
    ).status_code == 403
    assert (
        await client.post(
            "/api/v1/team/invitations",
            headers=manager_headers,
            json={
                "email": "owner-escalation@example.com",
                "role": "OWNER",
                "location_ids": [location_id],
            },
        )
    ).status_code == 403

    admin_invite = await client.post(
        "/api/v1/team/invitations",
        headers=admin_headers,
        json={
            "email": "admin-created@example.com",
            "role": "CASHIER",
            "location_ids": [location_id],
        },
    )
    assert admin_invite.status_code == 201
    assert (
        await client.post(
            "/api/v1/team/invitations",
            headers=admin_headers,
            json={
                "email": "admin-outside-location@example.com",
                "role": "CASHIER",
                "location_ids": [second_location_id],
            },
        )
    ).status_code == 422

    assert (
        await client.post(
            "/api/v1/employees",
            headers=admin_headers,
            json={
                "first_name": "Outside",
                "last_name": "Location",
                "location_ids": [second_location_id],
            },
        )
    ).status_code == 422
    assigned_employee = await client.post(
        "/api/v1/employees",
        headers=admin_headers,
        json={
            "first_name": "Assigned",
            "last_name": "Location",
            "location_ids": [location_id],
        },
    )
    assert assigned_employee.status_code == 201
    assert (
        await client.patch(
            f"/api/v1/employees/{assigned_employee.json()['id']}",
            headers=admin_headers,
            json={"location_ids": [second_location_id]},
        )
    ).status_code == 422
    unchanged_employee = await client.get(
        f"/api/v1/employees/{assigned_employee.json()['id']}",
        headers=admin_headers,
    )
    assert unchanged_employee.status_code == 200
    assert unchanged_employee.json()["location_ids"] == [location_id]
    unchanged_team = await client.get("/api/v1/team", headers=admin_headers)
    assert unchanged_team.status_code == 200
    assert not any(member["first_name"] == "Outside" for member in unchanged_team.json()["members"])
    assert not any(
        invitation["email"] == "admin-outside-location@example.com"
        for invitation in unchanged_team.json()["invitations"]
    )

    assert (
        await client.post(
            "/api/v1/team/invitations",
            headers=admin_headers,
            json={
                "email": "admin-escalation@example.com",
                "role": "ADMIN",
                "location_ids": [location_id],
            },
        )
    ).status_code == 422

    assert (
        await client.post(
            "/api/v1/team/invitations",
            headers=barista_headers,
            json={
                "email": "forbidden@example.com",
                "role": "BARISTA",
                "location_ids": [location_id],
            },
        )
    ).status_code == 403
    assert (
        await client.patch(
            f"/api/v1/employees/{admin_invite.json()['id']}",
            headers=barista_headers,
            json={"position": "Admin"},
        )
    ).status_code == 403
    assert (await client.get("/api/v1/team", headers=barista_headers)).status_code == 403
    manager_supplier = await client.post(
        "/api/v1/suppliers",
        headers=manager_headers,
        json={"name": "Manager Supplier"},
    )
    assert manager_supplier.status_code == 201
    assert (await client.get("/api/v1/suppliers", headers=manager_headers)).status_code == 200
    assert (await client.get("/api/v1/suppliers", headers=admin_headers)).status_code == 200
    assert (await client.get("/api/v1/suppliers", headers=barista_headers)).status_code == 403

    menu_category = await client.post(
        "/api/v1/menu/categories",
        headers=owner_headers,
        json={"name": "Coffee"},
    )
    assert menu_category.status_code == 201
    menu_product = await client.post(
        "/api/v1/menu/products",
        headers=owner_headers,
        json={
            "category_id": menu_category.json()["id"],
            "name": "RBAC Cappuccino",
            "default_variant": {"base_price_minor": 180000},
        },
    )
    assert menu_product.status_code == 201
    variant_id = menu_product.json()["variants"][0]["id"]
    assert (await client.get("/api/v1/menu/categories", headers=barista_headers)).status_code == 200
    assert (
        await client.post(
            "/api/v1/menu/categories",
            headers=barista_headers,
            json={"name": "Forbidden"},
        )
    ).status_code == 403
    assert (
        await client.patch(
            f"/api/v1/menu/variants/{variant_id}",
            headers=manager_headers,
            json={"base_price_minor": 190000},
        )
    ).status_code == 200
    assert (
        await client.patch(
            f"/api/v1/menu/variants/{variant_id}",
            headers=barista_headers,
            json={"base_price_minor": 1},
        )
    ).status_code == 403
    recipe = await client.put(
        f"/api/v1/menu/variants/{variant_id}/recipe",
        headers=owner_headers,
        json={
            "components": [
                {"inventory_item_id": item.json()["id"], "quantity": "1", "unit": "g"}
            ]
        },
    )
    assert recipe.status_code == 200, recipe.text
    activated = await client.patch(
        f"/api/v1/menu/products/{menu_product.json()['id']}",
        headers=manager_headers,
        json={"status": "ACTIVE"},
    )
    assert activated.status_code == 200
    modifier_group = await client.post(
        f"/api/v1/menu/variants/{variant_id}/modifier-groups",
        headers=manager_headers,
        json={
            "name": "Milk",
            "selection_type": "SINGLE",
            "min_selections": 0,
            "max_selections": 1,
        },
    )
    assert modifier_group.status_code == 201, modifier_group.text
    assert (
        await client.post(
            f"/api/v1/menu/variants/{variant_id}/modifier-groups",
            headers=barista_headers,
            json={
                "name": "Forbidden",
                "selection_type": "SINGLE",
                "min_selections": 0,
                "max_selections": 1,
            },
        )
    ).status_code == 403
    option = await client.post(
        f"/api/v1/menu/modifier-groups/{modifier_group.json()['id']}/options",
        headers=admin_headers,
        json={"name": "Regular", "base_price_delta_minor": 0, "is_default": True},
    )
    assert option.status_code == 201, option.text
    for read_headers in (accountant_headers, cashier_headers, barista_headers):
        menu = await client.get(
            "/api/v1/menu",
            headers=read_headers,
            params={"location_id": location_id},
        )
        assert menu.status_code == 200, menu.text
        projected = menu.json()["categories"][0]["products"][0]["variants"][0]
        assert projected["modifier_groups"][0]["name"] == "Milk"
        assert projected["modifier_groups"][0]["options"][0]["name"] == "Regular"
        assert (
            await client.get(
                f"/api/v1/menu/variants/{variant_id}/modifier-groups",
                headers=read_headers,
            )
        ).status_code == 403
        assert (
            await client.post(
                f"/api/v1/menu/variants/{variant_id}/customization-preview",
                headers=read_headers,
                params={"warehouse_id": warehouse.json()["id"], "location_id": location_id},
                json={"selected_option_ids": []},
            )
        ).status_code == 403
    assert (
        await client.get(
            f"/api/v1/menu/variants/{variant_id}/recipe",
            headers=barista_headers,
        )
    ).status_code == 403

    devices: list[tuple[dict[str, str], dict, str]] = []
    for index, pair_headers in enumerate((owner_headers, admin_headers, manager_headers), start=1):
        register = await client.post(
            "/api/v1/sales/registers",
            headers=owner_headers,
            json={"location_id": location_id, "name": f"Offline RBAC {index}"},
        )
        assert register.status_code == 201, register.text
        shift = await client.post(
            "/api/v1/sales/shifts/open",
            headers=owner_headers,
            json={
                "register_id": register.json()["id"],
                "warehouse_id": warehouse.json()["id"],
            },
        )
        assert shift.status_code == 201, shift.text
        paired = await client.post(
            "/api/v1/pos/offline/devices/pair",
            headers=pair_headers,
            json={"register_id": register.json()["id"], "name": f"Device {index}"},
        )
        assert paired.status_code == 201, paired.text
        devices.append((paired.json(), shift.json(), paired.cookies["beanly_pos_device"]))

    for headers in (cashier_headers, barista_headers):
        denied_pair = await client.post(
            "/api/v1/pos/offline/devices/pair",
            headers=headers,
            json={"register_id": devices[2][0]["register_id"], "name": "Forbidden"},
        )
        assert denied_pair.status_code == 403, denied_pair.text
        denied_revoke = await client.post(
            f"/api/v1/pos/offline/devices/{devices[2][0]['id']}/revoke",
            headers=headers,
        )
        assert denied_revoke.status_code == 403, denied_revoke.text

    started_sessions = []
    for headers, (_, shift, credential) in zip(
        (cashier_headers, barista_headers, manager_headers), devices, strict=True
    ):
        started = await client.post(
            "/api/v1/pos/offline/sessions/start",
            headers={**headers, "cookie": f"beanly_pos_device={credential}"},
            json={"shift_id": shift["id"]},
        )
        assert started.status_code == 201, started.text
        started_sessions.append((started.json(), credential))

    async def sync_as(index: int, status: str, *, payment: bool = False):
        offline_session, credential = started_sessions[index]
        timestamp = offline_session["server_time"]
        order = {
            "client_order_id": str(uuid4()),
            "revision": 1,
            "catalog_snapshot_id": offline_session["catalog_snapshot_id"],
            "created_at": timestamp,
            "updated_at": timestamp,
            "order_type": "DINE_IN",
            "status": status,
            "items": [
                {
                    "client_item_id": str(uuid4()),
                    "variant_id": variant_id,
                    "selected_option_ids": [option.json()["id"]],
                    "quantity": 1,
                }
            ],
        }
        if payment:
            order["payment"] = {
                "client_payment_id": str(uuid4()),
                "completed_at": timestamp,
                "lines": [{"method": "CASH", "amount_minor": "190000"}],
            }
        response = await client.post(
            "/api/v1/pos/offline/sync",
            headers={"cookie": f"beanly_pos_device={credential}"},
            json={"session_id": offline_session["id"], "orders": [order]},
        )
        assert response.status_code == 200, response.text
        return response.json()["results"][0]

    assert (await sync_as(2, "OPEN"))["code"] == "OFFLINE_PERMISSION_DENIED"
    assert (await sync_as(1, "PAID", payment=True))["code"] == "OFFLINE_PERMISSION_DENIED"
    assert (await sync_as(0, "CANCELLED"))["code"] == "OFFLINE_PERMISSION_DENIED"
    cashier_open = await sync_as(0, "OPEN")
    assert cashier_open["status"] == "SYNCED", cashier_open
    barista_open = await sync_as(1, "OPEN")
    assert barista_open["status"] == "SYNCED", barista_open
