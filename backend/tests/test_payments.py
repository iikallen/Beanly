from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update

from beanly.core.events.outbox.models import OutboxEventModel
from beanly.core.money import MAX_NUMERIC_20_6_MINOR
from beanly.modules.inventory.infrastructure.db.models import InventoryTransactionModel
from beanly.modules.payments.application.payment_service import _idempotent, _NormalizedLine
from beanly.modules.payments.domain.entities import Payment, PaymentLine
from beanly.modules.payments.domain.enums import PaymentMethod
from beanly.modules.payments.domain.exceptions import PaymentIdempotencyConflict
from beanly.modules.payments.infrastructure.db.models import PaymentModel
from beanly.modules.sales.infrastructure.db.models import RegisterShiftModel, SalesOrderModel


def test_offline_payment_idempotency_includes_business_time_and_session() -> None:
    now = datetime.now(UTC)
    order_id = uuid4()
    payment_id = uuid4()
    offline_session_id = uuid4()
    line = PaymentLine(
        uuid4(),
        payment_id,
        PaymentMethod.CARD,
        180000,
        None,
        0,
        "terminal-1",
        0,
        now,
    )
    payment = Payment(
        payment_id,
        uuid4(),
        uuid4(),
        order_id,
        uuid4(),
        uuid4(),
        "KZT",
        180000,
        uuid4(),
        now,
        now,
        now,
        (line,),
        offline_session_id,
    )
    requested = (_NormalizedLine(PaymentMethod.CARD, 180000, None, 0, "terminal-1"),)

    assert _idempotent(payment, order_id, requested, now, offline_session_id) is payment
    with pytest.raises(PaymentIdempotencyConflict):
        _idempotent(payment, order_id, requested, now + timedelta(seconds=1), offline_session_id)
    with pytest.raises(PaymentIdempotencyConflict):
        _idempotent(payment, order_id, requested, now, uuid4())


async def _user(client: AsyncClient, email: str) -> dict[str, str]:
    password = "correct-horse-battery-staple"
    created = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": password,
            "first_name": "Payment",
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


async def _register_shift(
    client: AsyncClient,
    headers: dict[str, str],
    location_id: UUID,
    warehouse_id: UUID,
    name: str = "Front counter",
) -> dict:
    register = await client.post(
        "/api/v1/sales/registers",
        headers=headers,
        json={"location_id": str(location_id), "name": name},
    )
    assert register.status_code == 201, register.text
    shift = await client.post(
        "/api/v1/sales/shifts/open",
        headers=headers,
        json={
            "register_id": register.json()["id"],
            "warehouse_id": str(warehouse_id),
        },
    )
    assert shift.status_code == 201, shift.text
    return shift.json()


async def _variant(
    client: AsyncClient, headers: dict[str, str], name: str, price: int
) -> UUID:
    category = await client.post(
        "/api/v1/menu/categories", headers=headers, json={"name": f"{name} category"}
    )
    assert category.status_code == 201, category.text
    product = await client.post(
        "/api/v1/menu/products",
        headers=headers,
        json={
            "category_id": category.json()["id"],
            "name": name,
            "default_variant": {
                "name": "Default",
                "base_price_minor": price,
                "is_default": True,
            },
        },
    )
    assert product.status_code == 201, product.text
    activated = await client.patch(
        f"/api/v1/menu/products/{product.json()['id']}",
        headers=headers,
        json={"status": "ACTIVE"},
    )
    assert activated.status_code == 200, activated.text
    variant_id = UUID(activated.json()["variants"][0]["id"])
    inventory_item = await client.post(
        "/api/v1/inventory/items",
        headers=headers,
        json={"name": f"{name} component", "base_unit": "pcs"},
    )
    assert inventory_item.status_code == 201, inventory_item.text
    recipe = await client.put(
        f"/api/v1/menu/variants/{variant_id}/recipe",
        headers=headers,
        json={
            "components": [
                {
                    "inventory_item_id": inventory_item.json()["id"],
                    "quantity": "1",
                    "unit": "pcs",
                }
            ]
        },
    )
    assert recipe.status_code == 200, recipe.text
    return variant_id


async def _order(
    client: AsyncClient,
    headers: dict[str, str],
    shift_id: str,
    variant_id: UUID | None,
) -> dict:
    created = await client.post(
        "/api/v1/sales/orders",
        headers=headers,
        json={
            "client_order_id": str(uuid4()),
            "shift_id": shift_id,
            "order_type": "TAKEAWAY",
        },
    )
    assert created.status_code == 201, created.text
    if variant_id is None:
        return created.json()
    added = await client.post(
        f"/api/v1/sales/orders/{created.json()['id']}/items",
        headers=headers,
        json={
            "client_item_id": str(uuid4()),
            "variant_id": str(variant_id),
            "selected_option_ids": [],
            "quantity": 1,
        },
    )
    assert added.status_code == 201, added.text
    return added.json()


def _coded(response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.json()["detail"]["code"] == code


@pytest.mark.anyio
@pytest.mark.parametrize("method", ["CASH", "CARD", "OTHER"])
async def test_full_single_method_payment(app_client, method: str) -> None:
    client, _ = app_client
    headers, _, location_id, warehouse_id = await _workspace(
        client, f"payments-{method.casefold()}@example.com", f"Payments {method}"
    )
    shift = await _register_shift(client, headers, location_id, warehouse_id)
    variant_id = await _variant(client, headers, f"{method} order", 320000)
    order = await _order(client, headers, shift["id"], variant_id)
    line = {"method": method, "amount_minor": 320000}
    if method == "CASH":
        line["cash_received_minor"] = 500000
    response = await client.post(
        f"/api/v1/payments/orders/{order['id']}/complete",
        headers=headers,
        json={"client_payment_id": str(uuid4()), "lines": [line]},
    )
    assert response.status_code == 201, response.text
    assert response.json()["amount_minor"] == "320000"
    assert response.json()["lines"][0]["method"] == method
    assert response.json()["lines"][0]["change_minor"] == (
        "180000" if method == "CASH" else "0"
    )


@pytest.mark.anyio
async def test_payment_finance_numeric_limit_is_atomic(app_client) -> None:
    client, sessions = app_client
    headers, _, location_id, warehouse_id = await _workspace(
        client, "payments-finance-limit@example.com", "Payment finance limit"
    )
    shift = await _register_shift(client, headers, location_id, warehouse_id)

    maximum_variant = await _variant(
        client, headers, "Maximum finance amount", MAX_NUMERIC_20_6_MINOR
    )
    maximum_order = await _order(client, headers, shift["id"], maximum_variant)
    maximum = await client.post(
        f"/api/v1/payments/orders/{maximum_order['id']}/complete",
        headers=headers,
        json={
            "client_payment_id": str(uuid4()),
            "lines": [
                {"method": "CARD", "amount_minor": MAX_NUMERIC_20_6_MINOR}
            ],
        },
    )
    assert maximum.status_code == 201, maximum.text
    assert maximum.json()["amount_minor"] == str(MAX_NUMERIC_20_6_MINOR)

    overflow_variant = await _variant(
        client, headers, "Finance amount overflow", MAX_NUMERIC_20_6_MINOR + 1
    )
    overflow_order = await _order(client, headers, shift["id"], overflow_variant)
    rejected = await client.post(
        f"/api/v1/payments/orders/{overflow_order['id']}/complete",
        headers=headers,
        json={
            "client_payment_id": str(uuid4()),
            "lines": [
                {
                    "method": "CARD",
                    "amount_minor": MAX_NUMERIC_20_6_MINOR + 1,
                }
            ],
        },
    )
    assert rejected.status_code == 422, rejected.text
    async with sessions() as session:
        persisted = await session.get(SalesOrderModel, UUID(overflow_order["id"]))
        assert persisted is not None
        assert persisted.status == "OPEN"
        assert persisted.paid_at is None
        assert persisted.inventory_transaction_id is None
        assert await session.scalar(
            select(func.count(PaymentModel.id)).where(
                PaymentModel.order_id == UUID(overflow_order["id"])
            )
        ) == 0
        assert await session.scalar(
            select(func.count(OutboxEventModel.id)).where(
                OutboxEventModel.event_name == "payment.completed"
            )
        ) == 1


@pytest.mark.anyio
async def test_payment_flow_validation_idempotency_summary_and_sale_posting(
    app_client,
) -> None:
    client, sessions = app_client
    headers, organization_id, location_id, warehouse_id = await _workspace(
        client, "payments-owner@example.com", "Payments"
    )
    shift = await _register_shift(client, headers, location_id, warehouse_id)
    variant_id = await _variant(client, headers, "Split order", 670000)

    methods = await client.get("/api/v1/payments/methods", headers=headers)
    assert methods.status_code == 200, methods.text
    assert methods.json() == [
        {"code": "CASH", "name": "Cash"},
        {"code": "CARD", "name": "Card"},
        {"code": "OTHER", "name": "Other"},
    ]

    order = await _order(client, headers, shift["id"], variant_id)
    endpoint = f"/api/v1/payments/orders/{order['id']}/complete"
    invalid_requests = (
        (
            {
                "client_payment_id": str(uuid4()),
                "lines": [{"method": "CARD", "amount_minor": 669999}],
            },
            422,
            "PAYMENT_AMOUNT_MISMATCH",
        ),
        (
            {
                "client_payment_id": str(uuid4()),
                "lines": [{"method": "CARD", "amount_minor": 670001}],
            },
            422,
            "PAYMENT_AMOUNT_MISMATCH",
        ),
        (
            {
                "client_payment_id": str(uuid4()),
                "lines": [
                    {
                        "method": "CASH",
                        "amount_minor": 670000,
                        "cash_received_minor": 669999,
                    }
                ],
            },
            422,
            "INVALID_PAYMENT",
        ),
        (
            {
                "client_payment_id": str(uuid4()),
                "lines": [
                    {
                        "method": "CARD",
                        "amount_minor": 670000,
                        "cash_received_minor": 670000,
                    }
                ],
            },
            422,
            "INVALID_PAYMENT",
        ),
    )
    for payload, status, code in invalid_requests:
        _coded(await client.post(endpoint, headers=headers, json=payload), status, code)

    too_large = await client.post(
        endpoint,
        headers=headers,
        json={
            "client_payment_id": str(uuid4()),
            "lines": [{"method": "CARD", "amount_minor": 9223372036854775808}],
        },
    )
    assert too_large.status_code == 422, too_large.text

    client_payment_id = uuid4()
    payload = {
        "client_payment_id": str(client_payment_id),
        "lines": [
            {
                "method": "CASH",
                "amount_minor": 200000,
                "cash_received_minor": 250000,
                "reference": "  drawer  ",
            },
            {"method": "CARD", "amount_minor": 300000, "reference": "terminal"},
            {"method": "OTHER", "amount_minor": 170000},
        ],
    }
    completed = await client.post(endpoint, headers=headers, json=payload)
    assert completed.status_code == 201, completed.text
    payment = completed.json()
    assert payment["organization_id"] == str(organization_id)
    assert payment["location_id"] == str(location_id)
    assert payment["shift_id"] == shift["id"]
    assert payment["order_id"] == order["id"]
    assert payment["currency_code"] == "KZT"
    assert payment["amount_minor"] == "670000"
    assert [line["method"] for line in payment["lines"]] == ["CASH", "CARD", "OTHER"]
    assert payment["lines"][0]["cash_received_minor"] == "250000"
    assert payment["lines"][0]["change_minor"] == "50000"
    assert payment["lines"][0]["reference"] == "drawer"
    assert all(line["change_minor"] == "0" for line in payment["lines"][1:])

    retried = await client.post(endpoint, headers=headers, json=payload)
    assert retried.status_code == 201, retried.text
    assert retried.json() == payment
    changed = {
        **payload,
        "lines": [
            *payload["lines"][:1],
            {**payload["lines"][1], "reference": "other"},
            payload["lines"][2],
        ],
    }
    _coded(
        await client.post(endpoint, headers=headers, json=changed),
        409,
        "PAYMENT_IDEMPOTENCY_CONFLICT",
    )
    reordered = {**payload, "lines": list(reversed(payload["lines"]))}
    _coded(
        await client.post(endpoint, headers=headers, json=reordered),
        409,
        "PAYMENT_IDEMPOTENCY_CONFLICT",
    )
    _coded(
        await client.post(
            endpoint,
            headers=headers,
            json={
                "client_payment_id": str(uuid4()),
                "lines": [{"method": "CARD", "amount_minor": 670000}],
            },
        ),
        409,
        "ORDER_ALREADY_PAID",
    )

    immutable = await client.patch(
        f"/api/v1/sales/orders/{order['id']}", headers=headers, json={"note": "no"}
    )
    _coded(immutable, 409, "ORDER_IMMUTABLE")
    paid_order = (
        await client.get(f"/api/v1/sales/orders/{order['id']}", headers=headers)
    ).json()
    assert paid_order["status"] == "PAID"
    assert paid_order["paid_at"] is not None
    assert paid_order["paid_by_user_id"] is not None
    assert {"inventory_transaction_id", "cogs_amount", "cogs_status"}.isdisjoint(
        paid_order
    )

    for response in (
        await client.get(f"/api/v1/payments/{payment['id']}", headers=headers),
        await client.get(f"/api/v1/payments/orders/{order['id']}", headers=headers),
    ):
        assert response.status_code == 200, response.text
        assert response.json()["id"] == payment["id"]
    listed = await client.get(
        "/api/v1/payments",
        headers=headers,
        params={"location_id": str(location_id), "shift_id": shift["id"], "method": "CASH"},
    )
    assert listed.status_code == 200, listed.text
    assert [value["id"] for value in listed.json()] == [payment["id"]]
    summary = await client.get(
        f"/api/v1/payments/shifts/{shift['id']}/summary", headers=headers
    )
    assert summary.status_code == 200, summary.text
    assert summary.json() == {
        "orders_paid": 1,
        "gross_amount_minor": "670000",
        "methods": [
            {"method": "CASH", "amount_minor": "200000"},
            {"method": "CARD", "amount_minor": "300000"},
            {"method": "OTHER", "amount_minor": "170000"},
        ],
    }
    closed = await client.post(
        f"/api/v1/sales/shifts/{shift['id']}/close", headers=headers
    )
    assert closed.status_code == 200, closed.text

    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(PaymentModel)) == 1
        transactions = (
            await session.execute(select(InventoryTransactionModel))
        ).scalars().all()
        assert len(transactions) == 1
        assert transactions[0].type == "SALE"
        assert transactions[0].status == "POSTED"


@pytest.mark.anyio
async def test_payment_zero_total_nonempty_tenant_and_create_only_rbac(
    app_client, monkeypatch
) -> None:
    client, sessions = app_client
    headers, organization_id, location_id, warehouse_id = await _workspace(
        client, "payments-rbac-owner@example.com", "Payments RBAC"
    )
    shift = await _register_shift(client, headers, location_id, warehouse_id)
    free_variant = await _variant(client, headers, "Complimentary", 0)

    empty = await _order(client, headers, shift["id"], None)
    _coded(
        await client.post(
            f"/api/v1/payments/orders/{empty['id']}/complete",
            headers=headers,
            json={"client_payment_id": str(uuid4()), "lines": []},
        ),
        409,
        "ORDER_NOT_PAYABLE",
    )
    cancelled = await _order(client, headers, shift["id"], free_variant)
    assert (
        await client.post(
            f"/api/v1/sales/orders/{cancelled['id']}/cancel",
            headers=headers,
            json={"reason": "No sale"},
        )
    ).status_code == 200
    _coded(
        await client.post(
            f"/api/v1/payments/orders/{cancelled['id']}/complete",
            headers=headers,
            json={"client_payment_id": str(uuid4()), "lines": []},
        ),
        409,
        "ORDER_NOT_PAYABLE",
    )

    free_order = await _order(client, headers, shift["id"], free_variant)
    free_payment_id = uuid4()
    free = await client.post(
        f"/api/v1/payments/orders/{free_order['id']}/complete",
        headers=headers,
        json={"client_payment_id": str(free_payment_id), "lines": []},
    )
    assert free.status_code == 201, free.text
    assert free.json()["amount_minor"] == "0"
    assert free.json()["lines"] == []

    closed_shift = await _register_shift(
        client, headers, location_id, warehouse_id, "Closed shift"
    )
    closed_order = await _order(client, headers, closed_shift["id"], free_variant)
    async with sessions() as session:
        await session.execute(
            update(RegisterShiftModel)
            .where(RegisterShiftModel.id == UUID(closed_shift["id"]))
            .values(status="CLOSED", closed_at=datetime.now(UTC))
        )
        await session.commit()
    _coded(
        await client.post(
            f"/api/v1/payments/orders/{closed_order['id']}/complete",
            headers=headers,
            json={"client_payment_id": str(uuid4()), "lines": []},
        ),
        409,
        "ORDER_SHIFT_CLOSED",
    )

    token = "payments-cashier-invitation-token-long-enough"
    monkeypatch.setattr(
        "beanly.modules.organizations.application.services.invitation_service.create_invitation_token",
        lambda: (token, sha256(token.encode()).hexdigest()),
    )
    cashier_auth = await _user(client, "payments-cashier@example.com")
    invitation = await client.post(
        "/api/v1/team/invitations",
        headers=headers,
        json={
            "email": "payments-cashier@example.com",
            "role": "CASHIER",
            "location_ids": [str(location_id)],
        },
    )
    assert invitation.status_code == 201, invitation.text
    assert (
        await client.post(f"/api/v1/invitations/{token}/accept", headers=cashier_auth)
    ).status_code == 204
    cashier = {**cashier_auth, "X-Organization-ID": str(organization_id)}
    assert (await client.get("/api/v1/payments/methods", headers=cashier)).status_code == 200
    assert (await client.get("/api/v1/payments", headers=cashier)).status_code == 403
    assert (
        await client.get(f"/api/v1/payments/{free.json()['id']}", headers=cashier)
    ).status_code == 403

    cashier_order = await _order(client, cashier, shift["id"], free_variant)
    cashier_paid = await client.post(
        f"/api/v1/payments/orders/{cashier_order['id']}/complete",
        headers=cashier,
        json={"client_payment_id": str(uuid4()), "lines": []},
    )
    assert cashier_paid.status_code == 201, cashier_paid.text

    second_location = await client.post(
        f"/api/v1/organizations/{organization_id}/locations",
        headers=headers,
        json={"name": "Inaccessible", "timezone": "Asia/Almaty"},
    )
    assert second_location.status_code == 201, second_location.text
    second_warehouse = await client.post(
        "/api/v1/inventory/warehouses",
        headers=headers,
        json={"location_id": second_location.json()["id"], "name": "Second"},
    )
    assert second_warehouse.status_code == 201, second_warehouse.text
    second_shift = await _register_shift(
        client,
        headers,
        UUID(second_location.json()["id"]),
        UUID(second_warehouse.json()["id"]),
        "Second counter",
    )
    inaccessible_order = await _order(
        client, headers, second_shift["id"], free_variant
    )
    inaccessible_retry = await client.post(
        f"/api/v1/payments/orders/{inaccessible_order['id']}/complete",
        headers=cashier,
        json={"client_payment_id": str(free_payment_id), "lines": []},
    )
    assert inaccessible_retry.status_code == 403, inaccessible_retry.text
    assert free.json()["order_id"] not in inaccessible_retry.text

    other_headers, _, other_location, other_warehouse = await _workspace(
        client, "payments-other@example.com", "Other Payments"
    )
    other_shift = await _register_shift(
        client, other_headers, other_location, other_warehouse, "Other counter"
    )
    other_variant = await _variant(client, other_headers, "Other item", 100)
    other_order = await _order(client, other_headers, other_shift["id"], other_variant)
    assert (
        await client.post(
            f"/api/v1/payments/orders/{other_order['id']}/complete",
            headers=headers,
            json={
                "client_payment_id": str(free_payment_id),
                "lines": [{"method": "CARD", "amount_minor": 100}],
            },
        )
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/payments/{free.json()['id']}", headers=other_headers)
    ).status_code == 404


def test_payment_openapi_keeps_completion_trust_boundary_and_refunds_read_only() -> None:
    from beanly.main import app

    paths = app.openapi()["paths"]
    expected = {
        "/api/v1/payments/methods": {"get"},
        "/api/v1/payments/orders/{order_id}/complete": {"post"},
        "/api/v1/payments/orders/{order_id}": {"get"},
        "/api/v1/payments/shifts/{shift_id}/summary": {"get"},
        "/api/v1/payments": {"get"},
        "/api/v1/payments/{payment_id}": {"get"},
        "/api/v1/payments/{payment_id}/refunds": {"get"},
    }
    for path, operations in expected.items():
        assert operations <= paths[path].keys()
    refund_operations = paths["/api/v1/payments/{payment_id}/refunds"]
    assert not {"post", "put", "patch", "delete"}.intersection(refund_operations)
    operation = paths["/api/v1/payments/orders/{order_id}/complete"]["post"]
    schema_ref = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    complete_schema = app.openapi()["components"]["schemas"][schema_ref.rsplit("/", 1)[-1]]
    assert set(complete_schema["properties"]) == {"client_payment_id", "lines"}
