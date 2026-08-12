import asyncio
from hashlib import sha256
from io import BytesIO
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from openpyxl import Workbook
from sqlalchemy import func, select

from beanly.modules.inventory.infrastructure.db.models import (
    InventoryItemModel,
    WarehouseModel,
)
from beanly.modules.menu.infrastructure.db.models import MenuCategoryModel, ProductModel
from beanly.modules.onboarding.infrastructure.db.models import (
    OnboardingImportRunModel,
    OnboardingStateModel,
)
from beanly.modules.sales.infrastructure.db.models import PosRegisterModel


def _inspect_workbook() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Menu"
    sheet.append(["Наименование", "Группа", "Цена"])
    sheet.append(["Latte", "Coffee", 1700])
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


async def _workspace(client: AsyncClient, email: str, name: str):
    password = "correct-horse-battery-staple"
    assert (
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": password,
                "first_name": "Stage",
                "last_name": "TwentyThree",
            },
        )
    ).status_code == 201
    login = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    auth = {"authorization": f"Bearer {login.json()['access_token']}"}
    response = await client.post(
        "/api/v1/organizations",
        headers=auth,
        json={
            "name": name,
            "country_code": "KZ",
            "currency_code": "KZT",
            "first_location": {"name": "Dostyk", "timezone": "Asia/Almaty"},
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    organization_id = UUID(body["organization"]["id"])
    location_id = UUID(body["location"]["id"])
    return (
        {**auth, "X-Organization-ID": str(organization_id)},
        organization_id,
        location_id,
    )


@pytest.mark.anyio
async def test_bootstrap_reuses_custom_active_resources_and_is_idempotent(app_client) -> None:
    client, sessions = app_client
    headers, organization_id, location_id = await _workspace(
        client, "stage23-bootstrap@example.com", "Bootstrap Coffee"
    )
    warehouse = await client.post(
        "/api/v1/inventory/warehouses",
        headers=headers,
        json={"location_id": str(location_id), "name": "Склад Dostyk"},
    )
    register = await client.post(
        "/api/v1/sales/registers",
        headers=headers,
        json={"location_id": str(location_id), "name": "Касса 1"},
    )
    assert warehouse.status_code == register.status_code == 201

    first = await client.post("/api/v1/onboarding/bootstrap", headers=headers, json={})
    assert first.status_code == 200, first.text
    assert first.json()["warehouse_id"] == warehouse.json()["id"]
    assert first.json()["register_id"] == register.json()["id"]
    assert first.json()["created"] == {"warehouse": False, "register": False}
    second = await client.post("/api/v1/onboarding/bootstrap", headers=headers, json={})
    assert second.status_code == 200, second.text
    assert second.json()["warehouse_id"] == first.json()["warehouse_id"]
    assert second.json()["register_id"] == first.json()["register_id"]

    async with sessions() as session:
        warehouse_count = await session.scalar(
            select(func.count()).select_from(WarehouseModel).where(
                WarehouseModel.organization_id == organization_id
            )
        )
        register_count = await session.scalar(
            select(func.count()).select_from(PosRegisterModel).where(
                PosRegisterModel.organization_id == organization_id
            )
        )
    assert warehouse_count == register_count == 1


@pytest.mark.anyio
async def test_template_preview_is_tenant_scoped_and_has_no_business_writes(app_client) -> None:
    client, sessions = app_client
    headers_a, organization_a, location_a = await _workspace(
        client, "stage23-a@example.com", "Tenant A"
    )
    _, _, location_b = await _workspace(client, "stage23-b@example.com", "Tenant B")

    payload = {
        "client_import_id": str(uuid4()),
        "version": 1,
        "location_id": str(location_a),
        "options": {},
    }
    preview = await client.post(
        "/api/v1/onboarding/templates/classic_coffee_shop/preview",
        headers=headers_a,
        json=payload,
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["status"] in {"NEEDS_REVIEW", "READY"}
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(MenuCategoryModel)) == 0
        assert await session.scalar(select(func.count()).select_from(ProductModel)) == 0
        assert await session.scalar(select(func.count()).select_from(InventoryItemModel)) == 0

    cross_tenant = dict(payload)
    cross_tenant["client_import_id"] = str(uuid4())
    cross_tenant["location_id"] = str(location_b)
    rejected = await client.post(
        "/api/v1/onboarding/templates/classic_coffee_shop/preview",
        headers=headers_a,
        json=cross_tenant,
    )
    assert rejected.status_code in {404, 409}
    async with sessions() as session:
        runs = await session.scalar(
            select(func.count()).select_from(OnboardingImportRunModel).where(
                OnboardingImportRunModel.organization_id == organization_a
            )
        )
    assert runs == 1


@pytest.mark.anyio
async def test_inspect_requires_mapping_but_writes_no_database_facts(app_client) -> None:
    client, sessions = app_client
    headers, organization_id, _ = await _workspace(
        client, "stage23-inspect@example.com", "Inspect Coffee"
    )
    response = await client.post(
        "/api/v1/onboarding/imports/inspect",
        headers=headers,
        data={"source_type": "AUTO"},
        files={
            "file": (
                "generic.xlsx",
                _inspect_workbook(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["mapping_required"] is True
    assert {"наименование", "группа", "цена"} <= set(
        response.json()["sheets"][0]["columns"]
    )
    async with sessions() as session:
        assert await session.scalar(
            select(func.count()).select_from(OnboardingImportRunModel).where(
                OnboardingImportRunModel.organization_id == organization_id
            )
        ) == 0
        assert await session.scalar(select(func.count()).select_from(MenuCategoryModel)) == 0
        assert await session.scalar(select(func.count()).select_from(ProductModel)) == 0
        assert await session.scalar(select(func.count()).select_from(InventoryItemModel)) == 0


@pytest.mark.anyio
async def test_existing_ready_organization_without_state_is_discovered_and_persisted_once(
    app_client, monkeypatch
) -> None:
    client, sessions = app_client
    headers, organization_id, location_id = await _workspace(
        client, "stage23-existing@example.com", "Existing Coffee"
    )
    warehouse = await client.post(
        "/api/v1/inventory/warehouses",
        headers=headers,
        json={"location_id": str(location_id), "name": "Existing Warehouse"},
    )
    register = await client.post(
        "/api/v1/sales/registers",
        headers=headers,
        json={"location_id": str(location_id), "name": "Existing Register"},
    )
    category = await client.post(
        "/api/v1/menu/categories", headers=headers, json={"name": "Coffee"}
    )
    product = await client.post(
        "/api/v1/menu/products",
        headers=headers,
        json={
            "category_id": category.json()["id"],
            "name": "Espresso",
            "default_variant": {
                "name": "Default",
                "base_price_minor": 90000,
                "is_default": True,
            },
        },
    )
    activated = await client.patch(
        f"/api/v1/menu/products/{product.json()['id']}",
        headers=headers,
        json={"status": "ACTIVE"},
    )
    assert warehouse.status_code == register.status_code == category.status_code == 201
    assert product.status_code == 201 and activated.status_code == 200

    class Histogram:
        def __init__(self) -> None:
            self.values: list[float] = []

        def record(self, value: float) -> None:
            self.values.append(value)

    histogram = Histogram()
    monkeypatch.setattr(
        "beanly.modules.onboarding.application.onboarding_service.metrics.onboarding_time_to_pos_ready",
        histogram,
    )
    responses = await asyncio.gather(
        client.get("/api/v1/onboarding/status", headers=headers),
        client.get("/api/v1/onboarding/status", headers=headers),
    )
    assert [response.status_code for response in responses] == [200, 200]
    assert {response.json()["status"] for response in responses} == {"READY_FOR_POS"}
    assert {response.json()["pos_ready"] for response in responses} == {True}
    repeated = await client.get("/api/v1/onboarding/status", headers=headers)
    assert repeated.json()["status"] == "READY_FOR_POS"

    async with sessions() as session:
        states = list(
            await session.scalars(
                select(OnboardingStateModel).where(
                    OnboardingStateModel.organization_id == organization_id
                )
            )
        )
    assert len(states) == 1
    assert states[0].status == "READY_FOR_POS"
    assert len(histogram.values) == 1


@pytest.mark.anyio
async def test_selected_location_actor_cannot_list_or_get_same_org_import(
    app_client, monkeypatch
) -> None:
    client, _ = app_client
    owner, organization_id, location_a = await _workspace(
        client, "stage23-location-owner@example.com", "Location scoped Coffee"
    )
    second = await client.post(
        f"/api/v1/organizations/{organization_id}/locations",
        headers=owner,
        json={"name": "Abay", "timezone": "Asia/Almaty"},
    )
    assert second.status_code == 201, second.text
    location_b = second.json()["id"]
    hidden = await client.post(
        "/api/v1/onboarding/templates/classic_coffee_shop/preview",
        headers=owner,
        json={
            "client_import_id": str(uuid4()),
            "version": 1,
            "location_id": location_b,
            "options": {},
        },
    )
    assert hidden.status_code == 200, hidden.text

    member_auth, _, _ = await _workspace(
        client, "stage23-location-manager@example.com", "Temporary member workspace"
    )
    raw_token = "stage23-location-scope-token-with-more-than-thirty-two-characters"
    monkeypatch.setattr(
        "beanly.modules.organizations.application.services.invitation_service."
        "create_invitation_token",
        lambda: (raw_token, sha256(raw_token.encode()).hexdigest()),
    )
    invited = await client.post(
        "/api/v1/team/invitations",
        headers=owner,
        json={
            "email": "stage23-location-manager@example.com",
            "role": "MANAGER",
            "location_ids": [str(location_a)],
        },
    )
    assert invited.status_code == 201, invited.text
    accepted = await client.post(
        f"/api/v1/invitations/{raw_token}/accept", headers=member_auth
    )
    assert accepted.status_code == 204, accepted.text
    scoped = {
        "authorization": member_auth["authorization"],
        "X-Organization-ID": str(organization_id),
    }

    listed = await client.get("/api/v1/onboarding/imports", headers=scoped)
    assert listed.status_code == 200, listed.text
    assert listed.json()["items"] == []
    assert listed.json()["total"] == 0
    assert (
        await client.get(
            f"/api/v1/onboarding/imports/{hidden.json()['id']}", headers=scoped
        )
    ).status_code == 404
