from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from beanly.core.events import CollectingDomainEventSink
from beanly.modules.inventory.application.commands import (
    CreateAndPostCommand,
    CreateDraftCommand,
    QuantityInput,
)
from beanly.modules.inventory.application.services import InventoryService
from beanly.modules.inventory.domain.enums import InventoryTransactionType
from beanly.modules.inventory.domain.events import StockAdjusted, StockWentNegative
from beanly.modules.inventory.domain.exceptions import InvalidInventoryOperation
from beanly.modules.inventory.domain.value_objects import (
    UnitCode,
    decimal_string,
    to_base_quantity,
)
from beanly.modules.inventory.infrastructure.db.repositories import (
    SqlAlchemyInventoryRepository,
)
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.infrastructure.db.models import (
    MembershipLocationModel,
    OrganizationMembershipModel,
)
from beanly.modules.organizations.infrastructure.db.repositories import (
    SqlAlchemyOrganizationRepository,
)


async def authenticated_user(client: AsyncClient, email: str) -> tuple[dict[str, str], UUID]:
    payload = {
        "email": email,
        "password": "correct-horse-battery-staple",
        "first_name": "Inventory",
        "last_name": "User",
    }
    assert (await client.post("/api/v1/auth/register", json=payload)).status_code == 201
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": payload["password"]},
    )
    headers = {"authorization": f"Bearer {login.json()['access_token']}"}
    me = await client.get("/api/v1/auth/me", headers=headers)
    return headers, UUID(me.json()["id"])


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


async def create_warehouse(
    client: AsyncClient, headers: dict[str, str], location_id: UUID, name: str = "Main"
) -> UUID:
    response = await client.post(
        "/api/v1/inventory/warehouses",
        headers=headers,
        json={"location_id": str(location_id), "name": name},
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


async def create_item(
    client: AsyncClient,
    headers: dict[str, str],
    name: str,
    base_unit: str,
    sku: str | None = None,
) -> UUID:
    response = await client.post(
        "/api/v1/inventory/items",
        headers=headers,
        json={"name": name, "base_unit": base_unit, "sku": sku},
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


def test_decimal_strings_preserve_integer_zeros() -> None:
    assert decimal_string(Decimal("1000")) == "1000"
    assert decimal_string(Decimal("6720")) == "6720"
    assert decimal_string(Decimal("-12000")) == "-12000"
    assert decimal_string(Decimal("0.100000")) == "0.1"
    assert to_base_quantity(Decimal("0.100001"), UnitCode.G, UnitCode.G) == Decimal("0.100001")
    assert to_base_quantity(Decimal("0.200002"), UnitCode.G, UnitCode.G) == Decimal("0.200002")
    with pytest.raises(ValueError):
        to_base_quantity(Decimal("0"), UnitCode.G, UnitCode.G)
    with pytest.raises(ValueError):
        to_base_quantity(Decimal("0.0000001"), UnitCode.G, UnitCode.G)
    with pytest.raises(ValueError):
        to_base_quantity(Decimal("1"), UnitCode.KG, UnitCode.ML)


@pytest.mark.anyio
async def test_opening_adjustment_conversion_history_and_reversal(app_client) -> None:
    client, _ = app_client
    auth, _ = await authenticated_user(client, "ledger-owner@example.com")
    headers, _, location_id = await workspace(client, auth, "Ledger Coffee")
    warehouse_id = await create_warehouse(client, headers, location_id)
    coffee_id = await create_item(client, headers, "Coffee", "g", "COFFEE")
    milk_id = await create_item(client, headers, "Milk", "ml")

    opening = await client.post(
        "/api/v1/inventory/opening-balances",
        headers={**headers, "Idempotency-Key": "opening:ledger-coffee"},
        json={
            "warehouse_id": str(warehouse_id),
            "items": [
                {
                    "inventory_item_id": str(coffee_id),
                    "quantity": "2.5",
                    "unit_code": "kg",
                },
                {
                    "inventory_item_id": str(milk_id),
                    "quantity": "1.25",
                    "unit_code": "l",
                },
            ],
        },
    )
    assert opening.status_code == 201, opening.text
    assert [line["quantity_delta"] for line in opening.json()["lines"]] == [
        "2500",
        "1250",
    ] or sorted(line["quantity_delta"] for line in opening.json()["lines"]) == [
        "1250",
        "2500",
    ]
    milk_stock = await client.get(
        f"/api/v1/inventory/items/{milk_id}/stock",
        params={"warehouse_id": str(warehouse_id)},
        headers=headers,
    )
    assert milk_stock.status_code == 200
    assert milk_stock.json()["quantity"] == "1250"

    adjustment = await client.post(
        "/api/v1/inventory/adjustments",
        headers={**headers, "Idempotency-Key": "adjust:spillage"},
        json={
            "warehouse_id": str(warehouse_id),
            "reason": "Spillage",
            "lines": [
                {
                    "inventory_item_id": str(coffee_id),
                    "quantity": "-0.1",
                    "unit_code": "kg",
                }
            ],
        },
    )
    assert adjustment.status_code == 201, adjustment.text
    assert adjustment.json()["lines"][0]["quantity_delta"] == "-100"

    stock = await client.get(
        f"/api/v1/inventory/items/{coffee_id}/stock",
        params={"warehouse_id": str(warehouse_id)},
        headers=headers,
    )
    assert stock.status_code == 200
    assert stock.json()["quantity"] == "2400"

    movements = await client.get(
        f"/api/v1/inventory/items/{coffee_id}/movements",
        params={"warehouse_id": str(warehouse_id)},
        headers=headers,
    )
    assert [movement["quantity_delta"] for movement in movements.json()] == [
        "-100",
        "2500",
    ]

    reversal = await client.post(
        f"/api/v1/inventory/transactions/{adjustment.json()['id']}/reverse",
        headers={**headers, "Idempotency-Key": "reverse:spillage"},
    )
    assert reversal.status_code == 201, reversal.text
    assert reversal.json()["reversal_of_id"] == adjustment.json()["id"]
    assert reversal.json()["lines"][0]["quantity_delta"] == "100"
    original = await client.get(
        f"/api/v1/inventory/transactions/{adjustment.json()['id']}", headers=headers
    )
    assert original.json()["status"] == "REVERSED"
    restored = await client.get(
        f"/api/v1/inventory/items/{coffee_id}/stock",
        params={"warehouse_id": str(warehouse_id)},
        headers=headers,
    )
    assert restored.json()["quantity"] == "2500"


@pytest.mark.anyio
async def test_wac_snapshots_and_valuation_api(app_client) -> None:
    client, _ = app_client
    auth, _ = await authenticated_user(client, "valuation-owner@example.com")
    headers, organization_id, location_id = await workspace(
        client, auth, "Valuation Coffee"
    )
    warehouse_id = await create_warehouse(client, headers, location_id)
    item_id = await create_item(client, headers, "Valued Coffee", "g")

    opening = await client.post(
        "/api/v1/inventory/opening-balances",
        headers={**headers, "Idempotency-Key": "opening:valued-coffee"},
        json={
            "warehouse_id": str(warehouse_id),
            "items": [
                {
                    "inventory_item_id": str(item_id),
                    "quantity": "1",
                    "unit_code": "kg",
                    "unit_cost_amount": "8000",
                }
            ],
        },
    )
    assert opening.status_code == 201, opening.text
    opening_line = opening.json()["lines"][0]
    assert opening_line["unit_cost_amount"] == "8"
    assert opening_line["total_cost_amount"] == "8000"
    assert opening_line["quantity_after"] == "1000"
    assert opening_line["average_unit_cost_after"] == "8"

    increase = await client.post(
        "/api/v1/inventory/adjustments",
        headers={**headers, "Idempotency-Key": "adjust:valued-coffee"},
        json={
            "warehouse_id": str(warehouse_id),
            "reason": "Count correction",
            "lines": [
                {
                    "inventory_item_id": str(item_id),
                    "quantity": "0.5",
                    "unit_code": "kg",
                }
            ],
        },
    )
    assert increase.status_code == 201, increase.text
    assert increase.json()["lines"][0]["unit_cost_amount"] == "8"
    assert increase.json()["lines"][0]["average_unit_cost_after"] == "8"

    valuation = await client.get(
        "/api/v1/inventory/valuation",
        params={"warehouse_id": str(warehouse_id), "location_id": str(location_id)},
        headers=headers,
    )
    assert valuation.status_code == 200, valuation.text
    assert valuation.json()["currency_code"] == "KZT"
    assert valuation.json()["total_inventory_value"] == "12000"
    assert valuation.json()["items"][0]["quantity"] == "1500"
    assert valuation.json()["items"][0]["average_unit_cost"] == "8"
    assert valuation.json()["items"][0]["inventory_value"] == "12000"

    movements = await client.get(
        f"/api/v1/inventory/items/{item_id}/movements",
        params={"warehouse_id": str(warehouse_id)},
        headers=headers,
    )
    assert movements.status_code == 200
    assert movements.json()[0]["quantity_after"] == "1500"
    assert movements.json()[0]["average_unit_cost_after"] == "8"

    decrease = await client.post(
        "/api/v1/inventory/adjustments",
        headers={**headers, "Idempotency-Key": "adjust:valued-coffee:outflow"},
        json={
            "warehouse_id": str(warehouse_id),
            "reason": "Spillage",
            "lines": [
                {
                    "inventory_item_id": str(item_id),
                    "quantity": "-0.25",
                    "unit_code": "kg",
                }
            ],
        },
    )
    assert decrease.status_code == 201, decrease.text
    decrease_line = decrease.json()["lines"][0]
    assert decrease_line["unit_cost_amount"] == "8"
    assert decrease_line["total_cost_amount"] == "-2000"
    assert decrease_line["quantity_after"] == "1250"
    assert decrease_line["average_unit_cost_after"] == "8"

    currency_change = await client.patch(
        f"/api/v1/organizations/{organization_id}",
        headers=auth,
        json={"currency_code": "USD"},
    )
    assert currency_change.status_code == 409


@pytest.mark.anyio
async def test_idempotency_reuses_same_payload_and_rejects_mismatch(app_client) -> None:
    client, sessions = app_client
    auth, _ = await authenticated_user(client, "idempotent-owner@example.com")
    headers, _, location_id = await workspace(client, auth, "Idempotent Coffee")
    warehouse_id = await create_warehouse(client, headers, location_id)
    item_id = await create_item(client, headers, "Cups", "pcs")
    request = {
        "warehouse_id": str(warehouse_id),
        "reason": "Count correction",
        "lines": [
            {
                "inventory_item_id": str(item_id),
                "quantity": "10",
                "unit_code": "pcs",
                "unit_cost_amount": "1",
            }
        ],
    }
    key_headers = {**headers, "Idempotency-Key": "adjust:count:1"}
    first = await client.post("/api/v1/inventory/adjustments", headers=key_headers, json=request)
    second = await client.post("/api/v1/inventory/adjustments", headers=key_headers, json=request)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    mismatch = await client.post(
        "/api/v1/inventory/adjustments",
        headers=key_headers,
        json={
            **request,
            "lines": [{**request["lines"][0], "quantity": "11"}],
        },
    )
    assert mismatch.status_code == 409
    stock = await client.get(
        f"/api/v1/inventory/items/{item_id}/stock",
        params={"warehouse_id": str(warehouse_id)},
        headers=headers,
    )
    assert stock.json()["quantity"] == "10"

    async with sessions() as session:
        service = InventoryService(
            SqlAlchemyInventoryRepository(session),
            OrganizationService(SqlAlchemyOrganizationRepository(session)),
        )
        context = await service.organizations.tenant_context(
            UUID(first.json()["created_by"]), UUID(headers["X-Organization-ID"])
        )
        draft = await service.create_draft(
            context,
            CreateDraftCommand(
                context.organization_id,
                context.user_id,
                warehouse_id,
                InventoryTransactionType.ADJUSTMENT,
                "Draft",
                (QuantityInput(item_id, Decimal("1"), UnitCode.PCS),),
            ),
        )
        await service.post_transaction(context, draft.transaction.id)
        with pytest.raises(InvalidInventoryOperation):
            await service.add_line(
                context,
                draft.transaction.id,
                QuantityInput(item_id, Decimal("1"), UnitCode.PCS),
            )


@pytest.mark.anyio
async def test_negative_stock_events_and_request_validation(app_client) -> None:
    client, sessions = app_client
    auth, user_id = await authenticated_user(client, "events-owner@example.com")
    headers, organization_id, location_id = await workspace(client, auth, "Events Coffee")
    warehouse_id = await create_warehouse(client, headers, location_id)
    item_id = await create_item(client, headers, "Beans", "g")

    numeric_json = await client.post(
        "/api/v1/inventory/adjustments",
        headers=headers,
        json={
            "warehouse_id": str(warehouse_id),
            "reason": "Invalid numeric JSON",
            "lines": [
                {
                    "inventory_item_id": str(item_id),
                    "quantity": 1.5,
                    "unit_code": "kg",
                }
            ],
        },
    )
    assert numeric_json.status_code == 422
    blank_reason = await client.post(
        "/api/v1/inventory/adjustments",
        headers=headers,
        json={
            "warehouse_id": str(warehouse_id),
            "reason": "   ",
            "lines": [
                {
                    "inventory_item_id": str(item_id),
                    "quantity": "-1",
                    "unit_code": "g",
                }
            ],
        },
    )
    assert blank_reason.status_code == 422
    negative_opening = await client.post(
        "/api/v1/inventory/opening-balances",
        headers=headers,
        json={
            "warehouse_id": str(warehouse_id),
            "items": [
                {
                    "inventory_item_id": str(item_id),
                    "quantity": "-1",
                    "unit_code": "g",
                }
            ],
        },
    )
    assert negative_opening.status_code == 422, negative_opening.text

    sink = CollectingDomainEventSink()
    async with sessions() as session:
        organizations = OrganizationService(SqlAlchemyOrganizationRepository(session))
        service = InventoryService(SqlAlchemyInventoryRepository(session), organizations, sink)
        context = await organizations.tenant_context(user_id, organization_id)
        await service.create_and_post(
            context,
            CreateAndPostCommand(
                organization_id,
                user_id,
                warehouse_id,
                InventoryTransactionType.ADJUSTMENT,
                "Negative test",
                (QuantityInput(item_id, Decimal("-5"), UnitCode.G),),
            ),
        )
    assert any(isinstance(event, StockWentNegative) for event in sink.events)
    assert any(isinstance(event, StockAdjusted) for event in sink.events)


@pytest.mark.anyio
async def test_tenant_and_selected_location_isolation(app_client) -> None:
    client, sessions = app_client
    owner, _ = await authenticated_user(client, "scope-owner@example.com")
    owner_headers, organization_id, assigned_location = await workspace(
        client, owner, "Scoped Coffee"
    )
    second_location_response = await client.post(
        f"/api/v1/organizations/{organization_id}/locations",
        headers=owner,
        json={"name": "Airport", "timezone": "Asia/Almaty"},
    )
    second_location = UUID(second_location_response.json()["id"])
    assigned_warehouse = await create_warehouse(
        client, owner_headers, assigned_location, "Assigned"
    )
    forbidden_warehouse = await create_warehouse(
        client, owner_headers, second_location, "Forbidden"
    )
    item_id = await create_item(client, owner_headers, "Scoped Item", "pcs")
    member, member_user_id = await authenticated_user(client, "scope-manager@example.com")

    membership_id = uuid4()
    async with sessions() as session:
        now = datetime.now(UTC)
        session.add(
            OrganizationMembershipModel(
                id=membership_id,
                organization_id=organization_id,
                user_id=member_user_id,
                role="MANAGER",
                status="ACTIVE",
                location_access="SELECTED",
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            MembershipLocationModel(
                membership_id=membership_id,
                location_id=assigned_location,
                created_at=now,
            )
        )
        await session.commit()

    member_headers = {**member, "X-Organization-ID": str(organization_id)}
    listed = await client.get("/api/v1/inventory/warehouses", headers=member_headers)
    assert [UUID(value["id"]) for value in listed.json()] == [assigned_warehouse]
    forbidden = await client.post(
        "/api/v1/inventory/adjustments",
        headers=member_headers,
        json={
            "warehouse_id": str(forbidden_warehouse),
            "reason": "Must not cross location scope",
            "lines": [
                {
                    "inventory_item_id": str(item_id),
                    "quantity": "1",
                    "unit_code": "pcs",
                }
            ],
        },
    )
    assert forbidden.status_code == 404

    foreign_owner, _ = await authenticated_user(client, "foreign-owner@example.com")
    foreign_headers, _, _ = await workspace(client, foreign_owner, "Foreign Coffee")
    foreign_item = await create_item(client, foreign_headers, "Foreign Item", "pcs")
    foreign_use = await client.post(
        "/api/v1/inventory/adjustments",
        headers=owner_headers,
        json={
            "warehouse_id": str(assigned_warehouse),
            "reason": "Foreign item",
            "lines": [
                {
                    "inventory_item_id": str(foreign_item),
                    "quantity": "1",
                    "unit_code": "pcs",
                }
            ],
        },
    )
    assert foreign_use.status_code == 404


@pytest.mark.anyio
async def test_movements_use_posting_order_and_sink_failure_rolls_back(
    app_client,
) -> None:
    client, sessions = app_client
    auth, user_id = await authenticated_user(client, "order-owner@example.com")
    headers, organization_id, location_id = await workspace(client, auth, "Posting Order Coffee")
    warehouse_id = await create_warehouse(client, headers, location_id)
    item_id = await create_item(client, headers, "Ordered Beans", "g")

    async with sessions() as session:
        organizations = OrganizationService(SqlAlchemyOrganizationRepository(session))
        context = await organizations.tenant_context(user_id, organization_id)
        service = InventoryService(SqlAlchemyInventoryRepository(session), organizations)
        delayed = await service.create_draft(
            context,
            CreateDraftCommand(
                organization_id,
                user_id,
                warehouse_id,
                InventoryTransactionType.ADJUSTMENT,
                "Created first, posted last",
                (QuantityInput(item_id, Decimal("1"), UnitCode.G, Decimal("1")),),
            ),
        )
        posted_first = await service.create_and_post(
            context,
            CreateAndPostCommand(
                organization_id,
                user_id,
                warehouse_id,
                InventoryTransactionType.ADJUSTMENT,
                "Posted first",
                (QuantityInput(item_id, Decimal("2"), UnitCode.G, Decimal("1")),),
            ),
        )
        await service.post_transaction(context, delayed.transaction.id)
        with pytest.raises(
            InvalidInventoryOperation,
            match="Referenced source aggregate is not available",
        ):
            await service.create_and_post(
                context,
                CreateAndPostCommand(
                    organization_id,
                    user_id,
                    warehouse_id,
                    InventoryTransactionType.ADJUSTMENT,
                    "Unverified source",
                    (QuantityInput(item_id, Decimal("10"), UnitCode.G),),
                    reference_type="ORDER",
                    reference_id=uuid4(),
                ),
            )

    class FailingSink:
        async def stage(self, event: object) -> None:
            del event
            raise RuntimeError("outbox unavailable")

        async def stage_many(self, events: tuple[object, ...]) -> None:
            assert events
            raise RuntimeError("outbox unavailable")

    async with sessions() as session:
        organizations = OrganizationService(SqlAlchemyOrganizationRepository(session))
        context = await organizations.tenant_context(user_id, organization_id)
        with pytest.raises(RuntimeError, match="outbox unavailable"):
            await InventoryService(
                SqlAlchemyInventoryRepository(session), organizations, FailingSink()
            ).create_and_post(
                context,
                CreateAndPostCommand(
                    organization_id,
                    user_id,
                    warehouse_id,
                    InventoryTransactionType.ADJUSTMENT,
                    "Must roll back with outbox",
                    (QuantityInput(item_id, Decimal("10"), UnitCode.G),),
                ),
            )

    movements = await client.get(f"/api/v1/inventory/items/{item_id}/movements", headers=headers)
    assert movements.status_code == 200
    assert [row["transaction_id"] for row in movements.json()] == [
        str(delayed.transaction.id),
        str(posted_first.transaction.id),
    ]
    stock = await client.get(
        f"/api/v1/inventory/items/{item_id}/stock",
        params={"warehouse_id": str(warehouse_id)},
        headers=headers,
    )
    assert stock.json()["quantity"] == "3"
