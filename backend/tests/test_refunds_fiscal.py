import asyncio
import os
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, event, func, inspect, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from beanly.core.config.settings import Settings
from beanly.core.database.session import get_session
from beanly.core.events.handlers.registry import EventHandlerRegistry
from beanly.core.events.outbox.dispatcher import OutboxDispatcher
from beanly.core.events.outbox.models import OutboxEventModel
from beanly.core.events.outbox.repositories import OutboxRepository
from beanly.core.events.outbox.writer import OutboxEventSink
from beanly.main import app
from beanly.modules.analytics.application.projection_service import AnalyticsProjectionService
from beanly.modules.analytics.infrastructure.db.models import (
    AnalyticsLocationMetricsDailyModel,
    AnalyticsProductSalesDailyModel,
    AnalyticsSalesDailyModel,
)
from beanly.modules.analytics.infrastructure.db.repositories import SqlAlchemyAnalyticsRepository
from beanly.modules.analytics.infrastructure.handlers import register_analytics_handlers
from beanly.modules.analytics.infrastructure.source_reader import SqlAlchemyAnalyticsSourceReader
from beanly.modules.finance.application.projection_service import FinanceProjectionService
from beanly.modules.finance.infrastructure.db.models import CashEntryModel, FinanceEntryModel
from beanly.modules.finance.infrastructure.db.repositories import SqlAlchemyFinanceRepository
from beanly.modules.finance.infrastructure.handlers import register_finance_handlers
from beanly.modules.finance.infrastructure.source_reader import SqlAlchemyFinanceSourceReader
from beanly.modules.fiscal.domain.tax import vat_minor
from beanly.modules.fiscal.infrastructure.db.models import (
    FiscalSaleSnapshotModel,
    FiscalTaxProfileModel,
    FiscalVariantProfileModel,
)
from beanly.modules.fiscal.infrastructure.operations import SqlAlchemyFiscalOperations
from beanly.modules.identity.api.dependencies import SessionDep, SettingsDep
from beanly.modules.integrations.application.job_service import IntegrationJobService
from beanly.modules.integrations.infrastructure.crypto.fernet_cipher import (
    FernetSecretCipher,
)
from beanly.modules.integrations.infrastructure.db.models import IntegrationJobModel
from beanly.modules.integrations.infrastructure.db.repositories import (
    SqlAlchemyIntegrationRepository,
)
from beanly.modules.integrations.infrastructure.handlers import register_integration_handlers
from beanly.modules.integrations.infrastructure.providers.registry import (
    build_provider_registry,
)
from beanly.modules.integrations.infrastructure.source_reader import (
    SqlAlchemyIntegrationSourceReader,
)
from beanly.modules.inventory.infrastructure.db.models import InventoryTransactionLineModel
from beanly.modules.menu.infrastructure.db.models import RecipeComponentModel, RecipeModel
from beanly.modules.refunds.api.dependencies import refund_service as refund_service_dependency
from beanly.modules.refunds.infrastructure.db.models import RefundModel
from beanly.modules.refunds.infrastructure.db.repositories import (
    SqlAlchemyRefundRepository,
)


class _BrokenSink:
    async def stage(self, event: object, *, occurred_at=None) -> None:
        del event, occurred_at
        raise RuntimeError("forced refund outbox failure")

    async def stage_many(self, events: tuple[object, ...], *, occurred_at=None) -> None:
        del events, occurred_at
        raise RuntimeError("forced refund outbox failure")


@pytest_asyncio.fixture
async def postgres_stage21_app():
    source_url = os.getenv("POSTGRES_TEST_URL")
    if not source_url:
        pytest.skip("POSTGRES_TEST_URL is required for the PostgreSQL integration gate")
    database_name = f"beanly_stage21_{uuid4().hex}"
    source = make_url(source_url)
    admin_url = source.set(database="postgres").render_as_string(hide_password=False)
    database_url = source.set(database=database_name).render_as_string(hide_password=False)
    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    engine = None
    try:
        async with admin_engine.connect() as connection:
            await connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", database_url)
        await asyncio.to_thread(command.upgrade, config, "head")
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)

        async def override_session():
            async with sessions() as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"origin": "http://localhost:3000"},
        ) as client:
            yield client, sessions, database_url, engine
    finally:
        app.dependency_overrides.clear()
        if engine is not None:
            await engine.dispose()
        async with admin_engine.connect() as connection:
            await connection.exec_driver_sql(
                f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)'
            )
        await admin_engine.dispose()


async def _workspace(
    client: AsyncClient, email: str, name: str
) -> tuple[dict[str, str], UUID, UUID, UUID]:
    password = "correct-horse-battery-staple"
    registered = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": password,
            "first_name": "Fiscal",
            "last_name": "Owner",
        },
    )
    assert registered.status_code == 201, registered.text
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
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


async def _variant(
    client: AsyncClient, headers: dict[str, str], name: str, price: int = 180000
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


async def _paid_order(
    client: AsyncClient,
    headers: dict[str, str],
    location_id: UUID,
    warehouse_id: UUID,
    variant_id: UUID,
    *,
    method: str = "CASH",
) -> tuple[dict, dict]:
    register = await client.post(
        "/api/v1/sales/registers",
        headers=headers,
        json={"location_id": str(location_id), "name": f"Fiscal {uuid4().hex[:8]}"},
    )
    assert register.status_code == 201, register.text
    shift = await client.post(
        "/api/v1/sales/shifts/open",
        headers=headers,
        json={"register_id": register.json()["id"], "warehouse_id": str(warehouse_id)},
    )
    assert shift.status_code == 201, shift.text
    order = await client.post(
        "/api/v1/sales/orders",
        headers=headers,
        json={
            "client_order_id": str(uuid4()),
            "shift_id": shift.json()["id"],
            "order_type": "TAKEAWAY",
        },
    )
    assert order.status_code == 201, order.text
    order = await client.post(
        f"/api/v1/sales/orders/{order.json()['id']}/items",
        headers=headers,
        json={
            "client_item_id": str(uuid4()),
            "variant_id": str(variant_id),
            "selected_option_ids": [],
            "quantity": 1,
        },
    )
    assert order.status_code == 201, order.text
    payment_line = {"method": method, "amount_minor": order.json()["total_minor"]}
    if method == "CASH":
        payment_line["cash_received_minor"] = order.json()["total_minor"]
    payment = await client.post(
        f"/api/v1/payments/orders/{order.json()['id']}/complete",
        headers=headers,
        json={
            "client_payment_id": str(uuid4()),
            "lines": [payment_line],
        },
    )
    assert payment.status_code == 201, payment.text
    return order.json(), payment.json()


def _coded(response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.json()["detail"]["code"] == code


def test_vat_inclusive_rounding_is_per_line_half_up() -> None:
    assert vat_minor(180000, 16) == 24828
    assert vat_minor(3, 100) == 1
    assert vat_minor(1, 16) == 0
    assert vat_minor(180000, 0) == 0
    assert vat_minor(180000, None) == 0
    with pytest.raises(ValueError, match="exact decimal"):
        vat_minor(180000, 16.0)  # type: ignore[arg-type]


@pytest.mark.anyio
async def test_refund_public_api_is_authoritative_idempotent_and_keeps_sale_paid(
    app_client,
    monkeypatch,
) -> None:
    client, sessions = app_client
    headers, organization_id, location_id, warehouse_id = await _workspace(
        client, "refund-api@example.com", "Refund API"
    )
    other_headers, _, _, _ = await _workspace(
        client, "refund-api-other@example.com", "Other refund API"
    )
    variant_id = await _variant(client, headers, "Refund espresso")
    order, payment = await _paid_order(client, headers, location_id, warehouse_id, variant_id)
    client_refund_id = uuid4()
    payload = {
        "client_refund_id": str(client_refund_id),
        "payment_id": payment["id"],
        "reason": "QUALITY_ISSUE",
        "note": "Burnt shot",
        "lines": [
            {
                "order_item_id": order["items"][0]["id"],
                "quantity": 1,
                "restock_quantity": 0,
            }
        ],
        "payment_lines": [
            {
                "original_payment_line_id": payment["lines"][0]["id"],
                "amount_minor": 180000,
            }
        ],
    }
    preview_payload = {key: value for key, value in payload.items() if key != "client_refund_id"}
    preview = await client.post("/api/v1/refunds/preview", headers=headers, json=preview_payload)
    assert preview.status_code == 200, preview.text
    assert preview.json()["total_amount_minor"] == "180000"
    assert preview.json()["lines"][0]["available_quantity"] == 1
    assert preview.json()["payment_lines"][0]["available_amount_minor"] == "180000"

    created = await client.post("/api/v1/refunds", headers=headers, json=payload)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "COMPLETED"
    assert body["total_amount_minor"] == "180000"
    assert body["inventory_transaction_id"] is None
    assert body["cogs_reversal_amount"] == "0"
    assert body["cogs_quality_status"] is None

    retried = await client.post("/api/v1/refunds", headers=headers, json=payload)
    assert retried.status_code == 201, retried.text
    assert retried.json()["id"] == body["id"]
    changed = await client.post(
        "/api/v1/refunds", headers=headers, json={**payload, "note": "different"}
    )
    _coded(changed, 409, "REFUND_IDEMPOTENCY_CONFLICT")

    order_after = await client.get(f"/api/v1/sales/orders/{order['id']}", headers=headers)
    assert order_after.status_code == 200, order_after.text
    assert order_after.json()["status"] == "PAID"
    exceeded = await client.post(
        "/api/v1/refunds",
        headers=headers,
        json={**payload, "client_refund_id": str(uuid4()), "note": None},
    )
    _coded(exceeded, 409, "REFUND_QUANTITY_EXCEEDED")

    listed = await client.get("/api/v1/refunds", headers=headers)
    by_payment = await client.get(f"/api/v1/payments/{payment['id']}/refunds", headers=headers)
    assert [value["id"] for value in listed.json()] == [body["id"]]
    assert [value["id"] for value in by_payment.json()] == [body["id"]]

    dashboard = await client.get("/api/v1/dashboard/overview", headers=headers)
    assert dashboard.status_code == 200, dashboard.text
    overview = dashboard.json()
    assert overview["sales"]["gross_sales_minor"] == "180000"
    assert overview["sales"]["refund_amount_minor"] == "180000"
    assert overview["sales"]["net_sales_minor"] == "0"
    assert overview["sales"]["revenue"]["current"] == "0"
    assert overview["sales"]["revenue"]["previous"] == "0"
    current_trend = [row for row in overview["trend"] if row["refund_amount_minor"] == "180000"]
    assert len(current_trend) == 1
    assert current_trend[0]["gross_sales_minor"] == "180000"
    assert current_trend[0]["net_sales_minor"] == "0"
    assert overview["locations"] == [
        {
            **overview["locations"][0],
            "gross_sales_minor": "180000",
            "refund_amount_minor": "180000",
            "net_sales_minor": "0",
        }
    ]

    second_location = await client.post(
        f"/api/v1/organizations/{organization_id}/locations",
        headers=headers,
        json={"name": "Mega", "timezone": "Asia/Almaty"},
    )
    assert second_location.status_code == 201, second_location.text
    selected_auth = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "refund-selected-manager@example.com",
            "password": "correct-horse-battery-staple",
            "first_name": "Selected",
            "last_name": "Manager",
        },
    )
    assert selected_auth.status_code == 201, selected_auth.text
    selected_login = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "refund-selected-manager@example.com",
            "password": "correct-horse-battery-staple",
        },
    )
    selected_headers = {
        "authorization": f"Bearer {selected_login.json()['access_token']}",
        "X-Organization-ID": str(organization_id),
    }
    token = "stage21-selected-location-token-with-safe-length"
    monkeypatch.setattr(
        "beanly.modules.organizations.application.services.invitation_service."
        "create_invitation_token",
        lambda: (token, sha256(token.encode()).hexdigest()),
    )
    invited = await client.post(
        "/api/v1/team/invitations",
        headers=headers,
        json={
            "email": "refund-selected-manager@example.com",
            "role": "MANAGER",
            "location_ids": [second_location.json()["id"]],
        },
    )
    assert invited.status_code == 201, invited.text
    assert (
        await client.post(f"/api/v1/invitations/{token}/accept", headers=selected_headers)
    ).status_code == 204

    hidden_order, hidden_payment = await _paid_order(
        client, headers, location_id, warehouse_id, variant_id
    )
    hidden_payload = {
        "payment_id": hidden_payment["id"],
        "reason": "OTHER",
        "lines": [
            {
                "order_item_id": hidden_order["items"][0]["id"],
                "quantity": 1,
                "restock_quantity": 0,
            }
        ],
        "payment_lines": [
            {
                "original_payment_line_id": hidden_payment["lines"][0]["id"],
                "amount_minor": 180000,
            }
        ],
    }
    _coded(
        await client.post("/api/v1/refunds/preview", headers=selected_headers, json=hidden_payload),
        404,
        "REFUND_NOT_FOUND",
    )
    _coded(
        await client.post(
            "/api/v1/refunds/preview", headers=selected_headers, json=preview_payload
        ),
        404,
        "REFUND_NOT_FOUND",
    )
    _coded(
        await client.post(
            "/api/v1/refunds",
            headers=selected_headers,
            json={**preview_payload, "client_refund_id": str(uuid4())},
        ),
        404,
        "REFUND_NOT_FOUND",
    )
    _coded(
        await client.post(
            "/api/v1/refunds",
            headers=selected_headers,
            json={**hidden_payload, "client_refund_id": str(uuid4())},
        ),
        404,
        "REFUND_NOT_FOUND",
    )
    _coded(
        await client.get(f"/api/v1/refunds/{body['id']}", headers=selected_headers),
        404,
        "REFUND_NOT_FOUND",
    )
    assert (await client.get("/api/v1/refunds", headers=selected_headers)).json() == []
    assert (
        await client.get(f"/api/v1/payments/{payment['id']}/refunds", headers=selected_headers)
    ).json() == []
    _coded(
        await client.get(f"/api/v1/refunds/{body['id']}", headers=other_headers),
        404,
        "REFUND_NOT_FOUND",
    )
    async with sessions() as session:
        assert (
            await session.scalar(
                select(func.count(OutboxEventModel.id)).where(
                    OutboxEventModel.organization_id == organization_id,
                    OutboxEventModel.event_name == "refund.completed",
                    OutboxEventModel.aggregate_id == UUID(body["id"]),
                )
            )
            == 1
        )
        repository = SqlAlchemyRefundRepository(session)
        query_count = 0
        entity_count = 0

        def count_query(*_args) -> None:
            nonlocal query_count
            query_count += 1

        def count_entity(*_args) -> None:
            nonlocal entity_count
            entity_count += 1

        engine = session.get_bind()
        event.listen(engine, "before_cursor_execute", count_query)
        event.listen(session.sync_session, "loaded_as_persistent", count_entity)
        try:
            anchor = datetime.now(UTC)
            period = (anchor - timedelta(days=1), anchor + timedelta(days=1))
            summary = await repository.dashboard_summary(organization_id, (location_id,), *period)
            trend = await repository.dashboard_trend(organization_id, (location_id,), (period,))
            locations = await repository.dashboard_locations(
                organization_id, (location_id,), *period
            )
        finally:
            event.remove(engine, "before_cursor_execute", count_query)
            event.remove(session.sync_session, "loaded_as_persistent", count_entity)

        assert summary == 180000
        assert trend == (180000,)
        assert locations == ((location_id, 180000),)
        assert query_count == 3
        assert entity_count == 0
        assert await repository.dashboard_summary(uuid4(), (location_id,), *period) == 0
        assert await repository.dashboard_summary(organization_id, (uuid4(),), *period) == 0


@pytest.mark.anyio
async def test_card_preview_does_not_claim_external_settlement_but_create_requires_it(
    app_client,
) -> None:
    client, _ = app_client
    headers, _, location_id, warehouse_id = await _workspace(
        client, "refund-card@example.com", "Refund card"
    )
    variant_id = await _variant(client, headers, "Card refund")
    order, payment = await _paid_order(
        client, headers, location_id, warehouse_id, variant_id, method="CARD"
    )
    payload = {
        "payment_id": payment["id"],
        "reason": "CUSTOMER_RETURN",
        "lines": [
            {
                "order_item_id": order["items"][0]["id"],
                "quantity": 1,
                "restock_quantity": 0,
            }
        ],
        "payment_lines": [
            {
                "original_payment_line_id": payment["lines"][0]["id"],
                "amount_minor": 180000,
                "external_refund_confirmed": False,
            }
        ],
    }
    preview = await client.post("/api/v1/refunds/preview", headers=headers, json=payload)
    assert preview.status_code == 200, preview.text
    rejected = await client.post(
        "/api/v1/refunds",
        headers=headers,
        json={**payload, "client_refund_id": str(uuid4())},
    )
    _coded(rejected, 409, "EXTERNAL_REFUND_NOT_CONFIRMED")
    payload["payment_lines"][0]["external_refund_confirmed"] = True
    completed = await client.post(
        "/api/v1/refunds",
        headers=headers,
        json={**payload, "client_refund_id": str(uuid4())},
    )
    assert completed.status_code == 201, completed.text


@pytest.mark.anyio
async def test_restock_uses_original_sale_cost_after_current_wac_changes(app_client) -> None:
    client, sessions = app_client
    headers, _, location_id, warehouse_id = await _workspace(
        client, "refund-cost@example.com", "Refund original cost"
    )
    variant_id = await _variant(client, headers, "Packaged water", 100000)
    async with sessions() as session:
        inventory_item_id = await session.scalar(
            select(RecipeComponentModel.inventory_item_id)
            .join(RecipeModel, RecipeModel.id == RecipeComponentModel.recipe_id)
            .where(RecipeModel.product_variant_id == variant_id)
        )
    assert inventory_item_id is not None
    supplier = await client.post(
        "/api/v1/suppliers", headers=headers, json={"name": "Water supplier"}
    )
    assert supplier.status_code == 201, supplier.text

    async def receive(quantity: str, unit_price: str) -> None:
        receipt = await client.post(
            "/api/v1/purchasing/receipts",
            headers=headers,
            json={
                "supplier_id": supplier.json()["id"],
                "location_id": str(location_id),
                "warehouse_id": str(warehouse_id),
                "received_at": datetime.now(UTC).isoformat(),
                "lines": [
                    {
                        "inventory_item_id": str(inventory_item_id),
                        "quantity": quantity,
                        "purchase_unit": "pcs",
                        "unit_multiplier": "1",
                        "unit_price": unit_price,
                    }
                ],
            },
        )
        assert receipt.status_code == 201, receipt.text
        posted = await client.post(
            f"/api/v1/purchasing/receipts/{receipt.json()['id']}/post",
            headers=headers,
            json={"confirm_over_receipt": False},
        )
        assert posted.status_code == 200, posted.text

    await receive("10", "400")
    order, payment = await _paid_order(client, headers, location_id, warehouse_id, variant_id)
    await receive("10", "1000")
    stock = await client.get(
        f"/api/v1/inventory/items/{inventory_item_id}/stock",
        headers=headers,
        params={"warehouse_id": str(warehouse_id)},
    )
    assert stock.status_code == 200, stock.text
    assert stock.json()["average_unit_cost"] != "400"

    refund_payload = {
        "client_refund_id": str(uuid4()),
        "payment_id": payment["id"],
        "reason": "CUSTOMER_RETURN",
        "lines": [
            {
                "order_item_id": order["items"][0]["id"],
                "quantity": 1,
                "restock_quantity": 1,
            }
        ],
        "payment_lines": [
            {
                "original_payment_line_id": payment["lines"][0]["id"],
                "amount_minor": 100000,
            }
        ],
    }
    completed = await client.post("/api/v1/refunds", headers=headers, json=refund_payload)
    assert completed.status_code == 201, completed.text
    assert completed.json()["cogs_reversal_amount"] == "400.000000"
    assert completed.json()["cogs_quality_status"] == "COMPLETE"
    transaction_id = UUID(completed.json()["inventory_transaction_id"])
    async with sessions() as session:
        line = await session.scalar(
            select(InventoryTransactionLineModel).where(
                InventoryTransactionLineModel.transaction_id == transaction_id
            )
        )
        assert line is not None
        assert line.quantity_delta == 1
        assert line.unit_cost_amount == 400
        assert line.total_cost_amount == 400
        count_before_retry = await session.scalar(
            select(func.count(InventoryTransactionLineModel.id)).where(
                InventoryTransactionLineModel.transaction_id == transaction_id
            )
        )
    retried = await client.post("/api/v1/refunds", headers=headers, json=refund_payload)
    assert retried.status_code == 201, retried.text
    assert retried.json()["inventory_transaction_id"] == str(transaction_id)
    async with sessions() as session:
        assert (
            await session.scalar(
                select(func.count(InventoryTransactionLineModel.id)).where(
                    InventoryTransactionLineModel.transaction_id == transaction_id
                )
            )
            == count_before_retry
        )


def test_refund_openapi_uses_lossless_minor_amounts_and_frozen_routes() -> None:
    from beanly.main import app

    contract = app.openapi()
    paths = contract["paths"]
    assert {
        "/api/v1/refunds/preview",
        "/api/v1/refunds",
        "/api/v1/refunds/{refund_id}",
        "/api/v1/payments/{payment_id}/refunds",
        "/api/v1/fiscal/tax-profile",
        "/api/v1/fiscal/variants/{variant_id}",
        "/api/v1/fiscal/readiness",
    } <= paths.keys()
    schemas = contract["components"]["schemas"]
    for schema, fields in {
        "RefundPreviewLineResponse": (
            "unit_refund_minor",
            "total_refund_minor",
        ),
        "RefundPreviewPaymentLineResponse": (
            "original_amount_minor",
            "already_refunded_minor",
            "available_amount_minor",
            "amount_minor",
        ),
        "RefundPreviewResponse": ("total_amount_minor",),
        "RefundLineResponse": ("unit_refund_minor", "total_refund_minor"),
        "RefundPaymentLineResponse": ("amount_minor",),
        "RefundResponse": ("total_amount_minor",),
    }.items():
        for field in fields:
            assert schemas[schema]["properties"][field]["type"] == "string"


@pytest.mark.anyio
async def test_refund_event_projects_finance_analytics_and_fiscal_job_exactly_once(
    app_client,
) -> None:
    client, sessions = app_client
    headers, organization_id, location_id, warehouse_id = await _workspace(
        client, "refund-projections@example.com", "Refund projections"
    )
    variant_id = await _variant(client, headers, "Projection water", 100000)
    async with sessions() as session:
        inventory_item_id = await session.scalar(
            select(RecipeComponentModel.inventory_item_id)
            .join(RecipeModel, RecipeModel.id == RecipeComponentModel.recipe_id)
            .where(RecipeModel.product_variant_id == variant_id)
        )
    assert inventory_item_id is not None
    supplier = await client.post(
        "/api/v1/suppliers", headers=headers, json={"name": "Projection supplier"}
    )
    assert supplier.status_code == 201, supplier.text
    receipt = await client.post(
        "/api/v1/purchasing/receipts",
        headers=headers,
        json={
            "supplier_id": supplier.json()["id"],
            "location_id": str(location_id),
            "warehouse_id": str(warehouse_id),
            "received_at": datetime.now(UTC).isoformat(),
            "lines": [
                {
                    "inventory_item_id": str(inventory_item_id),
                    "quantity": "10",
                    "purchase_unit": "pcs",
                    "unit_multiplier": "1",
                    "unit_price": "400",
                }
            ],
        },
    )
    assert receipt.status_code == 201, receipt.text
    assert (
        await client.post(
            f"/api/v1/purchasing/receipts/{receipt.json()['id']}/post",
            headers=headers,
            json={"confirm_over_receipt": False},
        )
    ).status_code == 200
    assert (
        await client.put(
            "/api/v1/fiscal/tax-profile",
            headers=headers,
            json={
                "country_code": "KZ",
                "tax_regime_code": "VAT",
                "vat_registered": True,
                "default_vat_rate": "16",
                "effective_from": date.today().isoformat(),
            },
        )
    ).status_code == 200
    assert (
        await client.put(
            f"/api/v1/fiscal/variants/{variant_id}",
            headers=headers,
            json={
                "fiscal_name": "Projection water A",
                "nkt_code": "NKT-PROJECTION",
                "nkt_code_type": "NKT",
                "fiscal_unit_code": "pcs",
                "vat_rate_override": None,
                "requires_marking": False,
            },
        )
    ).status_code == 200
    connection = await client.post(
        "/api/v1/integrations/connections",
        headers=headers,
        json={
            "provider_code": "mock_fiscal",
            "display_name": "Projection fiscal",
            "credentials": {"api_key": "valid-test-key"},
        },
    )
    assert connection.status_code == 201, connection.text
    activated = await client.post(
        f"/api/v1/integrations/connections/{connection.json()['id']}/test",
        headers=headers,
    )
    assert activated.status_code == 200, activated.text
    assert activated.json()["status"] == "ACTIVE"
    binding = await client.put(
        f"/api/v1/integrations/connections/{connection.json()['id']}/locations/{location_id}",
        headers=headers,
        json={"capability": "FISCAL", "settings": {}, "is_active": True},
    )
    assert binding.status_code == 200, binding.text

    order, payment = await _paid_order(client, headers, location_id, warehouse_id, variant_id)
    refund = await client.post(
        "/api/v1/refunds",
        headers=headers,
        json={
            "client_refund_id": str(uuid4()),
            "payment_id": payment["id"],
            "reason": "CUSTOMER_RETURN",
            "lines": [
                {
                    "order_item_id": order["items"][0]["id"],
                    "quantity": 1,
                    "restock_quantity": 1,
                }
            ],
            "payment_lines": [
                {
                    "original_payment_line_id": payment["lines"][0]["id"],
                    "amount_minor": 100000,
                }
            ],
        },
    )
    assert refund.status_code == 201, refund.text
    refund_id = UUID(refund.json()["id"])

    async with sessions() as session:
        handlers = EventHandlerRegistry()
        register_finance_handlers(
            handlers,
            FinanceProjectionService(
                SqlAlchemyFinanceRepository(session),
                SqlAlchemyFinanceSourceReader(session),
            ),
        )
        register_analytics_handlers(
            handlers,
            AnalyticsProjectionService(
                SqlAlchemyAnalyticsRepository(session),
                SqlAlchemyAnalyticsSourceReader(session),
            ),
        )
        register_integration_handlers(handlers, SqlAlchemyIntegrationRepository(session))
        dispatcher = OutboxDispatcher(OutboxRepository(session), handlers, "stage21-e2e")
        assert await dispatcher.run_once() > 0
        refund_event = await session.scalar(
            select(OutboxEventModel).where(
                OutboxEventModel.event_name == "refund.completed",
                OutboxEventModel.aggregate_id == refund_id,
            )
        )
        assert refund_event is not None
        await session.execute(
            update(OutboxEventModel)
            .where(OutboxEventModel.id == refund_event.id)
            .values(processed_at=None, available_at=datetime.now(UTC))
        )
        await session.commit()
        assert await dispatcher.run_once() == 1

        integration_repository = SqlAlchemyIntegrationRepository(session)
        worker_id = "stage21-fiscal-worker"
        claimed = await integration_repository.claim_jobs(worker_id, 10, 60)
        await integration_repository.commit()
        assert {job.job_type for job in claimed} == {
            "FISCALIZE_PAYMENT",
            "FISCALIZE_REFUND",
        }
        payment_job = next(job for job in claimed if job.job_type == "FISCALIZE_PAYMENT")
        refund_job = next(job for job in claimed if job.job_type == "FISCALIZE_REFUND")
        settings = Settings(environment="test")
        job_service = IntegrationJobService(
            integration_repository,
            SqlAlchemyIntegrationSourceReader(session),
            build_provider_registry(settings),
            FernetSecretCipher(settings.integration_encryption_key_list),
            OutboxEventSink(OutboxRepository(session)),
            max_attempts=3,
        )

        await job_service.execute(refund_job, worker_id)
        pending = await integration_repository.get_job(organization_id, refund_job.id)
        assert pending is not None
        assert pending.status.value == "RETRYING"
        assert pending.last_error_code == "FISCAL_ORIGINAL_RECEIPT_PENDING"

        await job_service.execute(payment_job, worker_id)
        original = await integration_repository.get_job(organization_id, payment_job.id)
        assert original is not None and original.status.value == "SUCCESS"

        await session.execute(
            update(IntegrationJobModel)
            .where(IntegrationJobModel.id == refund_job.id)
            .values(available_at=datetime.now(UTC))
        )
        await session.commit()
        retried_jobs = await integration_repository.claim_jobs(
            "stage21-fiscal-retry-worker", 10, 60
        )
        await integration_repository.commit()
        assert [job.id for job in retried_jobs] == [refund_job.id]
        await job_service.execute(retried_jobs[0], "stage21-fiscal-retry-worker")
        completed_refund = await integration_repository.get_job(organization_id, refund_job.id)
        assert completed_refund is not None
        assert completed_refund.status.value == "SUCCESS"
        assert completed_refund.external_id is not None

    async with sessions() as session:
        finance = list(
            await session.scalars(
                select(FinanceEntryModel).where(
                    FinanceEntryModel.source_type == "REFUND",
                    FinanceEntryModel.source_id == refund_id,
                )
            )
        )
        assert {(entry.entry_role, entry.amount) for entry in finance} == {
            ("REVENUE_REFUND", -1000),
            ("COGS_REFUND_REVERSAL", 400),
        }
        cash = list(
            await session.scalars(
                select(CashEntryModel).where(
                    CashEntryModel.source_type == "REFUND",
                    CashEntryModel.source_id == refund_id,
                )
            )
        )
        assert len(cash) == 1 and cash[0].amount_minor == -100000
        sales = await session.scalar(
            select(AnalyticsSalesDailyModel).where(
                AnalyticsSalesDailyModel.organization_id == organization_id,
                AnalyticsSalesDailyModel.location_id == location_id,
            )
        )
        product = await session.scalar(
            select(AnalyticsProductSalesDailyModel).where(
                AnalyticsProductSalesDailyModel.organization_id == organization_id,
                AnalyticsProductSalesDailyModel.location_id == location_id,
                AnalyticsProductSalesDailyModel.product_variant_id == variant_id,
            )
        )
        location = await session.scalar(
            select(AnalyticsLocationMetricsDailyModel).where(
                AnalyticsLocationMetricsDailyModel.organization_id == organization_id,
                AnalyticsLocationMetricsDailyModel.location_id == location_id,
            )
        )
        assert sales is not None
        assert sales.revenue_amount == 1000
        assert sales.refund_amount == 1000
        assert sales.refund_count == 1
        assert sales.refunded_items == 1
        assert product is not None
        assert product.refund_amount == 1000
        assert product.refunded_quantity == 1
        assert product.refund_orders == 1
        assert location is not None and location.refund_amount == 1000
        jobs = list(
            await session.scalars(
                select(IntegrationJobModel).where(
                    IntegrationJobModel.organization_id == organization_id
                )
            )
        )
        assert [(job.job_type, job.source_id) for job in jobs].count(
            ("FISCALIZE_PAYMENT", UUID(payment["id"]))
        ) == 1
        assert [(job.job_type, job.source_id) for job in jobs].count(
            ("FISCALIZE_REFUND", refund_id)
        ) == 1


@pytest.mark.anyio
async def test_fiscal_profile_validation_readiness_and_tenant_isolation(app_client) -> None:
    client, _ = app_client
    headers, _, _, _ = await _workspace(client, "fiscal-profile@example.com", "Fiscal profile")
    other_headers, _, _, _ = await _workspace(
        client, "fiscal-profile-other@example.com", "Other fiscal profile"
    )
    variant_id = await _variant(client, headers, "Cappuccino")

    _coded(
        await client.get("/api/v1/fiscal/tax-profile", headers=headers),
        404,
        "TAX_PROFILE_NOT_FOUND",
    )
    invalid = await client.put(
        "/api/v1/fiscal/tax-profile",
        headers=headers,
        json={
            "country_code": "KZ",
            "tax_regime_code": "VAT",
            "vat_registered": True,
            "default_vat_rate": None,
            "effective_from": date.today().isoformat(),
        },
    )
    _coded(invalid, 422, "INVALID_TAX_PROFILE")
    exact_decimal_only = await client.put(
        "/api/v1/fiscal/tax-profile",
        headers=headers,
        json={
            "country_code": "KZ",
            "tax_regime_code": "VAT",
            "vat_registered": True,
            "default_vat_rate": 16.0,
            "effective_from": date.today().isoformat(),
        },
    )
    assert exact_decimal_only.status_code == 422, exact_decimal_only.text

    profile = await client.put(
        "/api/v1/fiscal/tax-profile",
        headers=headers,
        json={
            "country_code": "KZ",
            "tax_regime_code": "VAT",
            "vat_registered": True,
            "default_vat_rate": "16",
            "effective_from": date.today().isoformat(),
        },
    )
    assert profile.status_code == 200, profile.text
    assert profile.json()["default_vat_rate"] == "16.0000"

    readiness = await client.get("/api/v1/fiscal/readiness", headers=headers)
    assert readiness.status_code == 200, readiness.text
    assert readiness.json()["ready"] is False
    assert readiness.json()["unmapped_variants"] == [
        {
            "variant_id": str(variant_id),
            "name": "Cappuccino Default",
            "reason": "NKT_MISSING",
        }
    ]

    configured = await client.put(
        f"/api/v1/fiscal/variants/{variant_id}",
        headers=headers,
        json={
            "fiscal_name": "Cappuccino fiscal",
            "nkt_code": "123456",
            "nkt_code_type": "NKT",
            "fiscal_unit_code": "pcs",
            "vat_rate_override": None,
            "requires_marking": False,
        },
    )
    assert configured.status_code == 200, configured.text
    oversized = await client.put(
        f"/api/v1/fiscal/variants/{variant_id}",
        headers=headers,
        json={
            "fiscal_name": "x" * 301,
            "nkt_code": "x" * 101,
            "nkt_code_type": "x" * 21,
            "fiscal_unit_code": "x" * 51,
            "vat_rate_override": "1000",
            "requires_marking": False,
        },
    )
    assert oversized.status_code == 422, oversized.text
    assert (await client.get("/api/v1/fiscal/readiness", headers=headers)).json()["ready"] is True
    _coded(
        await client.get(f"/api/v1/fiscal/variants/{variant_id}", headers=other_headers),
        404,
        "FISCAL_VARIANT_NOT_FOUND",
    )


@pytest.mark.anyio
async def test_payment_commits_immutable_fiscal_snapshot_before_outbox_dispatch(
    app_client,
) -> None:
    client, sessions = app_client
    headers, organization_id, location_id, warehouse_id = await _workspace(
        client, "fiscal-snapshot@example.com", "Fiscal snapshot"
    )
    variant_id = await _variant(client, headers, "Snapshot latte")
    tax = await client.put(
        "/api/v1/fiscal/tax-profile",
        headers=headers,
        json={
            "country_code": "KZ",
            "tax_regime_code": "VAT",
            "vat_registered": True,
            "default_vat_rate": "16",
            "effective_from": date.today().isoformat(),
        },
    )
    assert tax.status_code == 200, tax.text
    configured = await client.put(
        f"/api/v1/fiscal/variants/{variant_id}",
        headers=headers,
        json={
            "fiscal_name": "Snapshot A",
            "nkt_code": "NKT-A",
            "nkt_code_type": "NKT",
            "fiscal_unit_code": "pcs",
            "vat_rate_override": None,
            "requires_marking": False,
        },
    )
    assert configured.status_code == 200, configured.text
    order, payment = await _paid_order(client, headers, location_id, warehouse_id, variant_id)

    async with sessions() as session:
        snapshot = await session.scalar(
            select(FiscalSaleSnapshotModel).where(
                FiscalSaleSnapshotModel.organization_id == organization_id,
                FiscalSaleSnapshotModel.payment_id == UUID(payment["id"]),
            )
        )
        assert snapshot is not None, "snapshot must commit in the payment transaction"
        await session.refresh(snapshot, ["lines"])
        assert snapshot.order_id == UUID(order["id"])
        assert snapshot.compliance_status == "COMPLETE"
        assert snapshot.vat_total_minor == 24828
        assert snapshot.lines[0].fiscal_name == "Snapshot A"
        assert snapshot.lines[0].nkt_code == "NKT-A"

    updated = await client.put(
        f"/api/v1/fiscal/variants/{variant_id}",
        headers=headers,
        json={
            "fiscal_name": "Snapshot B",
            "nkt_code": "NKT-B",
            "nkt_code_type": "NKT",
            "fiscal_unit_code": "pcs",
            "vat_rate_override": "12",
            "requires_marking": False,
        },
    )
    assert updated.status_code == 200, updated.text
    async with sessions() as session:
        profile = await session.scalar(
            select(FiscalVariantProfileModel).where(
                FiscalVariantProfileModel.product_variant_id == variant_id
            )
        )
        snapshot = await session.scalar(
            select(FiscalSaleSnapshotModel).where(
                FiscalSaleSnapshotModel.payment_id == UUID(payment["id"])
            )
        )
        assert profile is not None and profile.fiscal_name == "Snapshot B"
        assert snapshot is not None
        await session.refresh(snapshot, ["lines"])
        assert snapshot.lines[0].fiscal_name == "Snapshot A"
        assert snapshot.lines[0].nkt_code == "NKT-A"
        assert snapshot.lines[0].vat_rate == 16


def test_refunds_and_fiscal_layers_keep_cross_context_reads_in_gateways() -> None:
    from pathlib import Path

    for module in ("refunds", "fiscal"):
        root = Path(f"beanly/modules/{module}")
        assert root.is_dir(), f"missing Stage 21 bounded context: {root}"
        for layer in (root / "domain", root / "application"):
            for path in layer.rglob("*.py"):
                source = path.read_text(encoding="utf-8").casefold()
                assert "fastapi" not in source, path
                assert "sqlalchemy" not in source, path
                assert ".infrastructure" not in source, path

    refunds = Path("beanly/modules/refunds")
    for path in refunds.rglob("*.py"):
        source = path.read_text(encoding="utf-8").casefold()
        if "infrastructure" not in path.parts and path != refunds / "api" / "dependencies.py":
            assert "modules.sales.infrastructure" not in source, path
            assert "modules.payments.infrastructure" not in source, path
            assert "modules.inventory.infrastructure" not in source, path
            assert "modules.fiscal.infrastructure" not in source, path

    dashboard = Path("beanly/modules/dashboard")
    for layer in (dashboard / "application", dashboard / "infrastructure"):
        for path in layer.rglob("*.py"):
            source = path.read_text(encoding="utf-8").casefold()
            assert "refunds.infrastructure" not in source, path
            assert "refundmodel" not in source, path
    gateway = (dashboard / "infrastructure" / "refunds_gateway.py").read_text(encoding="utf-8")
    assert "RefundReportingService" in gateway


def test_fiscal_provider_supports_return_receipts_without_void_semantics() -> None:
    from pathlib import Path

    ports = Path("beanly/modules/integrations/application/ports.py").read_text(encoding="utf-8")
    assert "fiscalize_refund" in ports
    for forbidden in ("void_receipt", "delete_receipt", "cancel_fiscal_sale"):
        assert forbidden not in ports


@pytest.mark.anyio
async def test_stage21_postgres_refund_locking_and_idempotency(
    postgres_stage21_app,
) -> None:
    client, sessions, _, _ = postgres_stage21_app
    headers, organization_id, location_id, warehouse_id = await _workspace(
        client, "refund-pg@example.com", "Refund PostgreSQL"
    )
    variant_id = await _variant(client, headers, "Concurrent refund")

    tax_payload = {
        "country_code": "KZ",
        "tax_regime_code": "VAT",
        "vat_registered": True,
        "default_vat_rate": "16",
        "effective_from": date.today().isoformat(),
    }
    concurrent_profiles = await asyncio.gather(
        client.put("/api/v1/fiscal/tax-profile", headers=headers, json=tax_payload),
        client.put("/api/v1/fiscal/tax-profile", headers=headers, json=tax_payload),
    )
    assert sorted(response.status_code for response in concurrent_profiles) == [200, 422]
    async with sessions() as session:
        assert (
            await session.scalar(
                select(func.count(FiscalTaxProfileModel.id)).where(
                    FiscalTaxProfileModel.organization_id == organization_id,
                    FiscalTaxProfileModel.effective_to.is_(None),
                )
            )
            == 1
        )

    async def paid() -> tuple[dict, dict]:
        return await _paid_order(client, headers, location_id, warehouse_id, variant_id)

    def payload(order: dict, payment: dict, client_id: UUID) -> dict:
        return {
            "client_refund_id": str(client_id),
            "payment_id": payment["id"],
            "reason": "QUALITY_ISSUE",
            "lines": [
                {
                    "order_item_id": order["items"][0]["id"],
                    "quantity": 1,
                    "restock_quantity": 0,
                }
            ],
            "payment_lines": [
                {
                    "original_payment_line_id": payment["lines"][0]["id"],
                    "amount_minor": 180000,
                }
            ],
        }

    exact_order, exact_payment = await paid()
    exact_payment_id = UUID(exact_payment["id"])
    async with sessions() as session:
        await session.execute(
            delete(FiscalSaleSnapshotModel).where(
                FiscalSaleSnapshotModel.payment_id == exact_payment_id
            )
        )
        await session.commit()

    async def recreate_snapshot() -> UUID:
        async with sessions() as session:
            snapshot = await SqlAlchemyFiscalOperations(session).create_sale_snapshot(
                organization_id, exact_payment_id
            )
            await session.commit()
            return snapshot.id

    snapshot_ids = await asyncio.gather(recreate_snapshot(), recreate_snapshot())
    assert snapshot_ids[0] == snapshot_ids[1]
    async with sessions() as session:
        assert (
            await session.scalar(
                select(func.count(FiscalSaleSnapshotModel.id)).where(
                    FiscalSaleSnapshotModel.payment_id == exact_payment_id
                )
            )
            == 1
        )
    exact_payload = payload(exact_order, exact_payment, uuid4())
    exact = await asyncio.gather(
        client.post("/api/v1/refunds", headers=headers, json=exact_payload),
        client.post("/api/v1/refunds", headers=headers, json=exact_payload),
    )
    assert [response.status_code for response in exact] == [201, 201]
    assert len({response.json()["id"] for response in exact}) == 1

    capped_order, capped_payment = await paid()
    attempts = await asyncio.gather(
        client.post(
            "/api/v1/refunds",
            headers=headers,
            json=payload(capped_order, capped_payment, uuid4()),
        ),
        client.post(
            "/api/v1/refunds",
            headers=headers,
            json=payload(capped_order, capped_payment, uuid4()),
        ),
    )
    assert sorted(response.status_code for response in attempts) == [201, 409]
    rejected = next(response for response in attempts if response.status_code == 409)
    assert rejected.json()["detail"]["code"] == "REFUND_QUANTITY_EXCEEDED"

    first_order, first_payment = await paid()
    second_order, second_payment = await paid()
    shared_client_id = uuid4()
    cross_payment = await asyncio.gather(
        client.post(
            "/api/v1/refunds",
            headers=headers,
            json=payload(first_order, first_payment, shared_client_id),
        ),
        client.post(
            "/api/v1/refunds",
            headers=headers,
            json=payload(second_order, second_payment, shared_client_id),
        ),
    )
    assert sorted(response.status_code for response in cross_payment) == [201, 409]
    conflict = next(response for response in cross_payment if response.status_code == 409)
    assert conflict.json()["detail"]["code"] == "REFUND_IDEMPOTENCY_CONFLICT"

    async with sessions() as session:
        assert (
            await session.scalar(
                select(func.count(RefundModel.id)).where(
                    RefundModel.organization_id == organization_id
                )
            )
            == 3
        )
        assert (
            await session.scalar(
                select(func.count(OutboxEventModel.id)).where(
                    OutboxEventModel.organization_id == organization_id,
                    OutboxEventModel.event_name == "refund.completed",
                )
            )
            == 3
        )


@pytest.mark.anyio
async def test_stage21_postgres_refund_rolls_back_when_outbox_staging_fails(
    postgres_stage21_app,
) -> None:
    client, sessions, _, _ = postgres_stage21_app
    headers, organization_id, location_id, warehouse_id = await _workspace(
        client, "refund-atomic-pg@example.com", "Refund atomic PostgreSQL"
    )
    variant_id = await _variant(client, headers, "Atomic refund")
    order, payment = await _paid_order(client, headers, location_id, warehouse_id, variant_id)
    client_refund_id = uuid4()
    payload = {
        "client_refund_id": str(client_refund_id),
        "payment_id": payment["id"],
        "reason": "QUALITY_ISSUE",
        "lines": [
            {
                "order_item_id": order["items"][0]["id"],
                "quantity": 1,
                "restock_quantity": 0,
            }
        ],
        "payment_lines": [
            {
                "original_payment_line_id": payment["lines"][0]["id"],
                "amount_minor": 180000,
            }
        ],
    }

    def broken_refund_service(session: SessionDep, settings: SettingsDep):
        service = refund_service_dependency(session, settings)
        service.sink = _BrokenSink()
        return service

    app.dependency_overrides[refund_service_dependency] = broken_refund_service
    try:
        with pytest.raises(RuntimeError, match="forced refund outbox failure"):
            await client.post("/api/v1/refunds", headers=headers, json=payload)
    finally:
        app.dependency_overrides.pop(refund_service_dependency, None)

    async with sessions() as session:
        assert (
            await session.scalar(
                select(func.count(RefundModel.id)).where(
                    RefundModel.organization_id == organization_id,
                    RefundModel.client_refund_id == client_refund_id,
                )
            )
            == 0
        )
        assert (
            await session.scalar(
                select(func.count(OutboxEventModel.id)).where(
                    OutboxEventModel.organization_id == organization_id,
                    OutboxEventModel.event_name == "refund.completed",
                )
            )
            == 0
        )


@pytest.mark.anyio
async def test_stage21_postgres_migration_cycle_backfills_without_inventing_tax(
    postgres_stage21_app,
) -> None:
    client, sessions, database_url, engine = postgres_stage21_app
    headers, _, location_id, warehouse_id = await _workspace(
        client, "fiscal-migration-pg@example.com", "Fiscal migration PostgreSQL"
    )
    variant_id = await _variant(client, headers, "Legacy fiscal")
    profile = await client.put(
        "/api/v1/fiscal/tax-profile",
        headers=headers,
        json={
            "country_code": "KZ",
            "tax_regime_code": "VAT",
            "vat_registered": True,
            "default_vat_rate": "16",
            "effective_from": date.today().isoformat(),
        },
    )
    assert profile.status_code == 200, profile.text
    variant_profile = await client.put(
        f"/api/v1/fiscal/variants/{variant_id}",
        headers=headers,
        json={
            "fiscal_name": "Configured historical name",
            "nkt_code": "CONFIGURED-NKT",
            "nkt_code_type": "NKT",
            "fiscal_unit_code": "pcs",
            "vat_rate_override": None,
            "requires_marking": False,
        },
    )
    assert variant_profile.status_code == 200, variant_profile.text
    order, payment = await _paid_order(client, headers, location_id, warehouse_id, variant_id)
    async with sessions() as session:
        before = await session.scalar(
            select(FiscalSaleSnapshotModel).where(
                FiscalSaleSnapshotModel.payment_id == UUID(payment["id"])
            )
        )
        assert before is not None and before.compliance_status == "COMPLETE"

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    await engine.dispose()
    await asyncio.to_thread(command.downgrade, config, "0020_offline_pos")
    inspection_engine = create_async_engine(database_url)
    async with inspection_engine.connect() as connection:
        tables = await connection.run_sync(lambda sync: set(inspect(sync).get_table_names()))
    await inspection_engine.dispose()
    assert (
        not {
            "refunds",
            "refund_lines",
            "refund_payment_lines",
            "fiscal_tax_profiles",
            "fiscal_variant_profiles",
            "fiscal_sale_snapshots",
            "fiscal_sale_snapshot_lines",
        }
        & tables
    )

    await asyncio.to_thread(command.upgrade, config, "head")
    await asyncio.to_thread(command.check, config)
    async with sessions() as session:
        backfilled = await session.scalar(
            select(FiscalSaleSnapshotModel).where(
                FiscalSaleSnapshotModel.payment_id == UUID(payment["id"])
            )
        )
        assert backfilled is not None
        await session.refresh(backfilled, ["lines"])
        assert backfilled.compliance_status == "INCOMPLETE"
        assert backfilled.tax_profile_id is None
        assert backfilled.vat_total_minor == 0
        assert len(backfilled.lines) == 1
        assert backfilled.lines[0].fiscal_name == "Legacy fiscal - Default"
        assert backfilled.lines[0].nkt_code is None
        assert backfilled.lines[0].vat_rate is None
        assert backfilled.lines[0].marking_codes == []
        assert backfilled.order_id == UUID(order["id"])
