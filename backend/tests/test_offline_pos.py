import asyncio
import os
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from beanly.core.database.session import get_session
from beanly.core.events.outbox.models import OutboxEventModel
from beanly.core.security.audit import SecurityAuditEventModel
from beanly.main import app
from beanly.modules.identity.api.dependencies import SessionDep
from beanly.modules.inventory.infrastructure.db.models import (
    InventoryTransactionModel,
    StockBalanceModel,
)
from beanly.modules.offline_pos.api.dependencies import sync_service as sync_service_dependency
from beanly.modules.offline_pos.infrastructure.db.models import (
    PosCatalogSnapshotModel,
    PosDeviceModel,
    PosOfflineOrderSyncModel,
    PosOfflineSessionModel,
)
from beanly.modules.payments.infrastructure.db.models import PaymentModel
from beanly.modules.sales.infrastructure.db.models import SalesOrderModel


@pytest_asyncio.fixture
async def postgres_offline_app():
    source_url = os.getenv("POSTGRES_TEST_URL")
    if not source_url:
        pytest.skip("POSTGRES_TEST_URL is required for the PostgreSQL integration gate")
    database_name = f"beanly_offline_{uuid4().hex}"
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
            yield client, sessions, database_url
    finally:
        app.dependency_overrides.clear()
        if engine is not None:
            await engine.dispose()
        async with admin_engine.connect() as connection:
            await connection.exec_driver_sql(
                f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)'
            )
        await admin_engine.dispose()


class _BrokenSink:
    async def stage(self, event: object, *, occurred_at=None) -> None:
        del event, occurred_at
        raise RuntimeError("forced outbox failure")

    async def stage_many(self, events: tuple[object, ...], *, occurred_at=None) -> None:
        del events, occurred_at
        raise RuntimeError("forced outbox failure")


async def _workspace(
    client: AsyncClient, email: str, name: str
) -> tuple[dict[str, str], UUID, UUID, UUID]:
    password = "correct-horse-battery-staple"
    registered = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": password,
            "first_name": "Offline",
            "last_name": "Owner",
        },
    )
    assert registered.status_code == 201, registered.text
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
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


async def _register_shift(
    client: AsyncClient,
    headers: dict[str, str],
    location_id: UUID,
    warehouse_id: UUID,
) -> tuple[dict, dict]:
    register = await client.post(
        "/api/v1/sales/registers",
        headers=headers,
        json={"location_id": str(location_id), "name": "Offline counter"},
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
    return register.json(), shift.json()


async def _catalog(client: AsyncClient, headers: dict[str, str]) -> tuple[UUID, UUID]:
    item = await client.post(
        "/api/v1/inventory/items",
        headers=headers,
        json={"name": "Offline beans", "base_unit": "pcs"},
    )
    assert item.status_code == 201, item.text
    category = await client.post(
        "/api/v1/menu/categories", headers=headers, json={"name": "Coffee"}
    )
    product = await client.post(
        "/api/v1/menu/products",
        headers=headers,
        json={
            "category_id": category.json()["id"],
            "name": "Offline cappuccino",
            "default_variant": {
                "name": "Default",
                "base_price_minor": 180000,
                "is_default": True,
            },
        },
    )
    variant_id = UUID(product.json()["variants"][0]["id"])
    recipe = await client.put(
        f"/api/v1/menu/variants/{variant_id}/recipe",
        headers=headers,
        json={
            "components": [
                {
                    "inventory_item_id": item.json()["id"],
                    "quantity": "1",
                    "unit": "pcs",
                }
            ]
        },
    )
    assert recipe.status_code == 200, recipe.text
    activated = await client.patch(
        f"/api/v1/menu/products/{product.json()['id']}",
        headers=headers,
        json={"status": "ACTIVE"},
    )
    assert activated.status_code == 200, activated.text
    return variant_id, UUID(item.json()["id"])


def _cookie(response) -> tuple[str, str]:
    header = response.headers["set-cookie"]
    credential = response.cookies["beanly_pos_device"]
    assert "HttpOnly" in header
    assert "Secure" in header
    assert "SameSite=strict" in header
    assert "Path=/api/v1/pos/offline" in header
    return credential, f"beanly_pos_device={credential}"


def _keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | set().union(*(_keys(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(_keys(item) for item in value))
    return set()


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.utcoffset() is None else value.astimezone(UTC)


@pytest.mark.anyio
async def test_offline_pos_security_atomic_sync_and_idempotency(app_client) -> None:
    client, sessions = app_client
    headers, organization_id, location_id, warehouse_id = await _workspace(
        client, "offline-owner@example.com", "Offline Coffee"
    )
    register, shift = await _register_shift(client, headers, location_id, warehouse_id)
    variant_id, inventory_item_id = await _catalog(client, headers)

    paired = await client.post(
        "/api/v1/pos/offline/devices/pair",
        headers=headers,
        json={"register_id": register["id"], "name": "Dostyk POS 1"},
    )
    assert paired.status_code == 201, paired.text
    assert "credential_hash" not in paired.json()
    credential, cookie = _cookie(paired)
    async with sessions() as session:
        device = await session.get(PosDeviceModel, UUID(paired.json()["id"]))
        assert device is not None
        assert device.credential_hash == sha256(credential.encode()).hexdigest()
        assert device.credential_hash != credential

    duplicate = await client.post(
        "/api/v1/pos/offline/devices/pair",
        headers=headers,
        json={"register_id": register["id"], "name": "Duplicate"},
    )
    assert duplicate.status_code == 409, duplicate.text

    other_headers, _, _, _ = await _workspace(client, "offline-other@example.com", "Other Coffee")
    cross_tenant = await client.post(
        "/api/v1/pos/offline/sessions/start",
        headers={**other_headers, "cookie": cookie},
        json={"shift_id": shift["id"]},
    )
    assert cross_tenant.status_code == 404, cross_tenant.text

    opening = await client.post(
        "/api/v1/inventory/opening-balances",
        headers={**headers, "Idempotency-Key": "opening:offline-pos"},
        json={
            "warehouse_id": str(warehouse_id),
            "items": [
                {
                    "inventory_item_id": str(inventory_item_id),
                    "quantity": "10",
                    "unit_code": "pcs",
                    "unit_cost_amount": "8",
                }
            ],
        },
    )
    assert opening.status_code == 201, opening.text

    started = await client.post(
        "/api/v1/pos/offline/sessions/start",
        headers={**headers, "cookie": cookie},
        json={"shift_id": shift["id"]},
    )
    assert started.status_code == 201, started.text
    offline_session = started.json()
    public = offline_session["catalog_snapshot"]["payload"]
    assert {
        "components",
        "inventory_item_id",
        "inventory_item_name",
        "recipe",
    }.isdisjoint(_keys(public))
    async with sessions() as session:
        snapshot = await session.get(
            PosCatalogSnapshotModel,
            UUID(offline_session["catalog_snapshot"]["id"]),
        )
        assert snapshot is not None
        assert "components" in _keys(snapshot.private_payload)
        assert snapshot.organization_id == organization_id
        assert snapshot.location_id == location_id
        assert snapshot.warehouse_id == warehouse_id

    adjustment = await client.post(
        "/api/v1/inventory/adjustments",
        headers={**headers, "Idempotency-Key": "adjust:offline-pos"},
        json={
            "warehouse_id": str(warehouse_id),
            "reason": "Cost changed while POS was offline",
            "lines": [
                {
                    "inventory_item_id": str(inventory_item_id),
                    "quantity": "1",
                    "unit_code": "pcs",
                }
            ],
        },
    )
    assert adjustment.status_code == 201, adjustment.text

    completed_at = offline_session["started_at"]
    client_order_id = str(uuid4())
    client_payment_id = str(uuid4())
    order = {
        "client_order_id": client_order_id,
        "revision": 1,
        "base_server_version": None,
        "catalog_snapshot_id": offline_session["catalog_snapshot"]["id"],
        "offline_display_number": 1,
        "created_at": completed_at,
        "updated_at": completed_at,
        "order_type": "TAKEAWAY",
        "status": "PAID",
        "items": [
            {
                "client_item_id": str(uuid4()),
                "variant_id": str(variant_id),
                "selected_option_ids": [],
                "quantity": 2,
            }
        ],
        "payment": {
            "client_payment_id": client_payment_id,
            "completed_at": completed_at,
            "lines": [
                {
                    "method": "CASH",
                    "amount_minor": "360000",
                    "cash_received_minor": "400000",
                }
            ],
        },
    }
    payload = {"session_id": offline_session["id"], "orders": [order]}
    synced = await client.post(
        "/api/v1/pos/offline/sync",
        headers={"cookie": cookie},
        json=payload,
    )
    assert synced.status_code == 200, synced.text
    assert synced.json()["results"][0]["status"] == "SYNCED"

    async def counts() -> tuple[int, int, int, int]:
        async with sessions() as session:
            return (
                await session.scalar(select(func.count(SalesOrderModel.id))),
                await session.scalar(select(func.count(PaymentModel.id))),
                await session.scalar(
                    select(func.count(InventoryTransactionModel.id)).where(
                        InventoryTransactionModel.type == "SALE"
                    )
                ),
                await session.scalar(select(func.count(PosOfflineOrderSyncModel.id))),
            )

    assert await counts() == (1, 1, 1, 1)
    repeated = await client.post(
        "/api/v1/pos/offline/sync", headers={"cookie": cookie}, json=payload
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["results"] == synced.json()["results"]
    assert await counts() == (1, 1, 1, 1)

    tampered = {**order, "items": [{**order["items"][0], "quantity": 1}]}
    conflict = await client.post(
        "/api/v1/pos/offline/sync",
        headers={"cookie": cookie},
        json={"session_id": offline_session["id"], "orders": [tampered]},
    )
    assert conflict.status_code == 200, conflict.text
    assert conflict.json()["results"][0]["code"] == "OFFLINE_REVISION_CONFLICT"
    original_again = await client.post(
        "/api/v1/pos/offline/sync", headers={"cookie": cookie}, json=payload
    )
    assert original_again.json()["results"][0]["status"] == "SYNCED"
    assert await counts() == (1, 1, 1, 1)

    open_order = {
        **order,
        "client_order_id": str(uuid4()),
        "status": "OPEN",
        "items": [{**order["items"][0], "client_item_id": str(uuid4()), "quantity": 1}],
        "payment": None,
    }
    open_synced = await client.post(
        "/api/v1/pos/offline/sync",
        headers={"cookie": cookie},
        json={"session_id": offline_session["id"], "orders": [open_order]},
    )
    assert open_synced.status_code == 200, open_synced.text
    server_version = open_synced.json()["results"][0]["server_version"]
    higher_revision = {
        **open_order,
        "revision": 2,
        "base_server_version": server_version + 1,
        "items": [{**open_order["items"][0], "quantity": 2}],
    }
    higher_conflict = await client.post(
        "/api/v1/pos/offline/sync",
        headers={"cookie": cookie},
        json={"session_id": offline_session["id"], "orders": [higher_revision]},
    )
    assert higher_conflict.status_code == 200, higher_conflict.text
    assert higher_conflict.json()["results"][0]["code"] == "ORDER_CHANGED_ON_SERVER"
    async with sessions() as session:
        conflict_events = await session.scalar(
            select(func.count(OutboxEventModel.id)).where(
                OutboxEventModel.event_name == "pos.offline_sync_conflict"
            )
        )
        receipt = await session.scalar(
            select(PosOfflineOrderSyncModel).where(
                PosOfflineOrderSyncModel.client_order_id == UUID(open_order["client_order_id"])
            )
        )
        assert receipt is not None
        assert (receipt.last_client_revision, receipt.status, receipt.last_error_code) == (
            2,
            "CONFLICT",
            "ORDER_CHANGED_ON_SERVER",
        )
    repeated_conflict = await client.post(
        "/api/v1/pos/offline/sync",
        headers={"cookie": cookie},
        json={"session_id": offline_session["id"], "orders": [higher_revision]},
    )
    assert repeated_conflict.json()["results"] == higher_conflict.json()["results"]
    async with sessions() as session:
        assert (
            await session.scalar(
                select(func.count(OutboxEventModel.id)).where(
                    OutboxEventModel.event_name == "pos.offline_sync_conflict"
                )
            )
            == conflict_events
        )

    failed_order = {
        **open_order,
        "client_order_id": str(uuid4()),
        "items": [{**open_order["items"][0], "client_item_id": str(uuid4())}],
    }

    def broken_sync_service(session: SessionDep):
        service = sync_service_dependency(session)
        service.sink = _BrokenSink()
        return service

    app.dependency_overrides[sync_service_dependency] = broken_sync_service
    try:
        with pytest.raises(RuntimeError, match="forced outbox failure"):
            await client.post(
                "/api/v1/pos/offline/sync",
                headers={"cookie": cookie},
                json={"session_id": offline_session["id"], "orders": [failed_order]},
            )
    finally:
        app.dependency_overrides.pop(sync_service_dependency, None)
    async with sessions() as session:
        assert (
            await session.scalar(
                select(func.count(SalesOrderModel.id)).where(
                    SalesOrderModel.client_order_id == UUID(failed_order["client_order_id"])
                )
            )
            == 0
        )
        assert (
            await session.scalar(
                select(func.count(PosOfflineOrderSyncModel.id)).where(
                    PosOfflineOrderSyncModel.client_order_id
                    == UUID(failed_order["client_order_id"])
                )
            )
            == 0
        )

    async with sessions() as session:
        payment = await session.scalar(
            select(PaymentModel).where(PaymentModel.client_payment_id == UUID(client_payment_id))
        )
        sales_order = await session.scalar(
            select(SalesOrderModel).where(SalesOrderModel.client_order_id == UUID(client_order_id))
        )
        balance = await session.scalar(
            select(StockBalanceModel).where(
                StockBalanceModel.warehouse_id == warehouse_id,
                StockBalanceModel.inventory_item_id == inventory_item_id,
            )
        )
        payment_event = await session.scalar(
            select(OutboxEventModel).where(OutboxEventModel.event_name == "payment.completed")
        )
        assert payment is not None and sales_order is not None and balance is not None
        business_time = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
        assert _utc(payment.completed_at) == business_time
        assert _utc(payment.created_at) > _utc(payment.completed_at)
        assert payment_event is not None
        assert _utc(payment_event.occurred_at) == business_time
        assert _utc(payment_event.created_at) > _utc(payment_event.occurred_at)
        assert sales_order.status == "PAID"
        assert sales_order.cogs_status == "ESTIMATED"
        assert str(balance.quantity) == "9.000000"

    async with sessions() as session:
        offline_session_row = await session.get(
            PosOfflineSessionModel, UUID(offline_session["id"])
        )
        assert offline_session_row is not None
        offline_session_row.status = "EXPIRED"
        offline_session_row.expires_at = datetime.now(UTC) - timedelta(hours=1)
        await session.commit()
    grace_retry = await client.post(
        "/api/v1/pos/offline/sync", headers={"cookie": cookie}, json=payload
    )
    assert grace_retry.status_code == 200, grace_retry.text
    assert grace_retry.json()["results"][0]["status"] == "SYNCED"
    async with sessions() as session:
        offline_session_row = await session.get(
            PosOfflineSessionModel, UUID(offline_session["id"])
        )
        assert offline_session_row is not None
        offline_session_row.expires_at = datetime.now(UTC) - timedelta(days=8)
        await session.commit()
    grace_elapsed = await client.post(
        "/api/v1/pos/offline/sync", headers={"cookie": cookie}, json=payload
    )
    assert grace_elapsed.status_code == 409, grace_elapsed.text

    other_register = await client.post(
        "/api/v1/sales/registers",
        headers=headers,
        json={"location_id": str(location_id), "name": "Other counter"},
    )
    assert other_register.status_code == 201, other_register.text
    other_device = await client.post(
        "/api/v1/pos/offline/devices/pair",
        headers=headers,
        json={"register_id": other_register.json()["id"], "name": "Other device"},
    )
    assert other_device.status_code == 201, other_device.text
    revoked_other = await client.post(
        f"/api/v1/pos/offline/devices/{other_device.json()['id']}/revoke",
        headers={**headers, "cookie": cookie},
    )
    assert revoked_other.status_code == 200, revoked_other.text
    assert "set-cookie" not in revoked_other.headers
    assert (
        await client.get("/api/v1/pos/offline/ping", headers={"cookie": cookie})
    ).status_code == 200

    revoked = await client.post(
        f"/api/v1/pos/offline/devices/{paired.json()['id']}/revoke",
        headers={**headers, "cookie": cookie},
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["status"] == "REVOKED"
    assert "Max-Age=0" in revoked.headers["set-cookie"]
    assert (
        await client.get("/api/v1/pos/offline/ping", headers={"cookie": cookie})
    ).status_code == 401
    async with sessions() as session:
        actions = set(await session.scalars(select(SecurityAuditEventModel.action)))
        assert {
            "POS_DEVICE_PAIRED",
            "POS_DEVICE_REVOKED",
            "OFFLINE_SESSION_STARTED",
        } <= actions


@pytest.mark.anyio
async def test_postgres_offline_sync_serializes_idempotency_stock_and_outbox(
    postgres_offline_app,
) -> None:
    client, sessions, _ = postgres_offline_app
    headers, _, location_id, warehouse_id = await _workspace(
        client, "offline-pg@example.com", "Offline PG"
    )
    register, shift = await _register_shift(client, headers, location_id, warehouse_id)
    variant_id, inventory_item_id = await _catalog(client, headers)
    opening = await client.post(
        "/api/v1/inventory/opening-balances",
        headers=headers,
        json={
            "warehouse_id": str(warehouse_id),
            "items": [
                {
                    "inventory_item_id": str(inventory_item_id),
                    "quantity": "5",
                    "unit_code": "pcs",
                    "unit_cost_amount": "8",
                }
            ],
        },
    )
    assert opening.status_code == 201, opening.text
    paired = await client.post(
        "/api/v1/pos/offline/devices/pair",
        headers=headers,
        json={"register_id": register["id"], "name": "Concurrent terminal"},
    )
    assert paired.status_code == 201, paired.text
    _, cookie = _cookie(paired)
    started = await client.post(
        "/api/v1/pos/offline/sessions/start",
        headers={**headers, "cookie": cookie},
        json={"shift_id": shift["id"]},
    )
    assert started.status_code == 201, started.text
    offline_session = started.json()

    def paid_order(quantity: int, display_number: int) -> dict:
        timestamp = offline_session["server_time"]
        return {
            "client_order_id": str(uuid4()),
            "revision": 1,
            "catalog_snapshot_id": offline_session["catalog_snapshot_id"],
            "offline_display_number": display_number,
            "created_at": timestamp,
            "updated_at": timestamp,
            "order_type": "TAKEAWAY",
            "status": "PAID",
            "items": [
                {
                    "client_item_id": str(uuid4()),
                    "variant_id": str(variant_id),
                    "quantity": quantity,
                }
            ],
            "payment": {
                "client_payment_id": str(uuid4()),
                "completed_at": timestamp,
                "lines": [
                    {
                        "method": "CASH",
                        "amount_minor": str(180000 * quantity),
                        "cash_received_minor": str(180000 * quantity),
                    }
                ],
            },
        }

    exact = paid_order(1, 1)
    exact_payload = {"session_id": offline_session["id"], "orders": [exact]}
    first, retry = await asyncio.gather(
        client.post("/api/v1/pos/offline/sync", headers={"cookie": cookie}, json=exact_payload),
        client.post("/api/v1/pos/offline/sync", headers={"cookie": cookie}, json=exact_payload),
    )
    assert first.status_code == retry.status_code == 200
    assert first.json()["results"] == retry.json()["results"]

    distinct = [paid_order(2, 2), paid_order(2, 3)]
    distinct_results = await asyncio.gather(
        *(
            client.post(
                "/api/v1/pos/offline/sync",
                headers={"cookie": cookie},
                json={"session_id": offline_session["id"], "orders": [order]},
            )
            for order in distinct
        )
    )
    assert [response.status_code for response in distinct_results] == [200, 200]
    assert [response.json()["results"][0]["status"] for response in distinct_results] == [
        "SYNCED",
        "SYNCED",
    ]

    async with sessions() as database:
        assert await database.scalar(select(func.count(SalesOrderModel.id))) == 3
        assert await database.scalar(select(func.count(PaymentModel.id))) == 3
        assert await database.scalar(select(func.count(PosOfflineOrderSyncModel.id))) == 3
        balance = await database.scalar(
            select(StockBalanceModel).where(
                StockBalanceModel.warehouse_id == warehouse_id,
                StockBalanceModel.inventory_item_id == inventory_item_id,
            )
        )
        assert balance is not None and balance.quantity == 0
        assert (
            await database.scalar(
                select(func.count(OutboxEventModel.id)).where(
                    OutboxEventModel.event_name == "pos.offline_order_synced"
                )
            )
            == 3
        )

    broken = paid_order(1, 4)
    broken["status"] = "OPEN"
    broken["payment"] = None

    def broken_sync(session: SessionDep):
        service = sync_service_dependency(session)
        service.sink = _BrokenSink()
        return service

    app.dependency_overrides[sync_service_dependency] = broken_sync
    try:
        with pytest.raises(RuntimeError, match="forced outbox failure"):
            await client.post(
                "/api/v1/pos/offline/sync",
                headers={"cookie": cookie},
                json={"session_id": offline_session["id"], "orders": [broken]},
            )
    finally:
        app.dependency_overrides.pop(sync_service_dependency, None)
    async with sessions() as database:
        assert (
            await database.scalar(
                select(func.count(SalesOrderModel.id)).where(
                    SalesOrderModel.client_order_id == UUID(broken["client_order_id"])
                )
            )
            == 0
        )
        assert (
            await database.scalar(
                select(func.count(PosOfflineOrderSyncModel.id)).where(
                    PosOfflineOrderSyncModel.client_order_id == UUID(broken["client_order_id"])
                )
            )
            == 0
        )


@pytest.mark.anyio
async def test_postgres_offline_migration_maps_estimated_on_downgrade_and_reupgrades(
    postgres_offline_app,
) -> None:
    client, sessions, database_url = postgres_offline_app
    headers, organization_id, location_id, warehouse_id = await _workspace(
        client, "offline-migration@example.com", "Offline migration"
    )
    register, shift = await _register_shift(client, headers, location_id, warehouse_id)
    variant_id, inventory_item_id = await _catalog(client, headers)
    zero_price = await client.patch(
        f"/api/v1/menu/variants/{variant_id}",
        headers=headers,
        json={"base_price_minor": 0},
    )
    assert zero_price.status_code == 200, zero_price.text
    opening = await client.post(
        "/api/v1/inventory/opening-balances",
        headers=headers,
        json={
            "warehouse_id": str(warehouse_id),
            "items": [
                {
                    "inventory_item_id": str(inventory_item_id),
                    "quantity": "2",
                    "unit_code": "pcs",
                    "unit_cost_amount": "8",
                }
            ],
        },
    )
    assert opening.status_code == 201, opening.text
    paired = await client.post(
        "/api/v1/pos/offline/devices/pair",
        headers=headers,
        json={"register_id": register["id"], "name": "Migration terminal"},
    )
    _, cookie = _cookie(paired)
    started = await client.post(
        "/api/v1/pos/offline/sessions/start",
        headers={**headers, "cookie": cookie},
        json={"shift_id": shift["id"]},
    )
    offline_session = started.json()
    adjustment = await client.post(
        "/api/v1/inventory/adjustments",
        headers={**headers, "Idempotency-Key": "adjust:migration-estimated"},
        json={
            "warehouse_id": str(warehouse_id),
            "reason": "Cost changes after snapshot",
            "lines": [
                {
                    "inventory_item_id": str(inventory_item_id),
                    "quantity": "1",
                    "unit_code": "pcs",
                }
            ],
        },
    )
    assert adjustment.status_code == 201, adjustment.text
    timestamp = offline_session["server_time"]
    order = {
        "client_order_id": str(uuid4()),
        "revision": 1,
        "catalog_snapshot_id": offline_session["catalog_snapshot_id"],
        "created_at": timestamp,
        "updated_at": timestamp,
        "order_type": "TAKEAWAY",
        "status": "PAID",
        "items": [
            {
                "client_item_id": str(uuid4()),
                "variant_id": str(variant_id),
                "quantity": 1,
            }
        ],
        "payment": {
            "client_payment_id": str(uuid4()),
            "completed_at": timestamp,
            "lines": [],
        },
    }
    synced = await client.post(
        "/api/v1/pos/offline/sync",
        headers={"cookie": cookie},
        json={"session_id": offline_session["id"], "orders": [order]},
    )
    assert synced.status_code == 200, synced.text
    server_order_id = synced.json()["results"][0]["server_order_id"]
    finance_entry_id = uuid4()
    async with sessions() as database:
        assert (
            await database.scalar(
                text("SELECT cogs_status FROM sales_orders WHERE id = :id"),
                {"id": UUID(server_order_id)},
            )
            == "ESTIMATED"
        )
        await database.execute(
            text(
                """
                INSERT INTO finance_entries (
                    id, organization_id, location_id, entry_type, amount,
                    currency_code, effective_at, description, expense_category_id,
                    source_type, source_id, source_event_id, entry_role,
                    reversal_of_id, quality_status, created_at
                ) VALUES (
                    :id, :organization_id, :location_id, 'COGS', 8,
                    'KZT', now(), 'Offline estimated COGS', NULL,
                    'payment', :source_id, :source_event_id, 'cogs',
                    NULL, 'ESTIMATED', now()
                )
                """
            ),
            {
                "id": finance_entry_id,
                "organization_id": organization_id,
                "location_id": location_id,
                "source_id": UUID(synced.json()["results"][0]["payment_id"]),
                "source_event_id": uuid4(),
            },
        )
        await database.commit()

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    await asyncio.to_thread(command.downgrade, config, "0019_production_hardening")
    async with sessions() as database:
        assert (
            await database.scalar(
                text("SELECT cogs_status FROM sales_orders WHERE id = :id"),
                {"id": UUID(server_order_id)},
            )
            == "INCOMPLETE"
        )
        assert (
            await database.scalar(
                text("SELECT quality_status FROM finance_entries WHERE id = :id"),
                {"id": finance_entry_id},
            )
            == "INCOMPLETE"
        )
        assert await database.scalar(text("SELECT to_regclass('public.pos_devices')")) is None

    await asyncio.to_thread(command.upgrade, config, "head")
    await asyncio.to_thread(command.check, config)
    async with sessions() as database:
        assert await database.scalar(text("SELECT version_num FROM alembic_version")) == (
            "0020_offline_pos"
        )
        assert await database.scalar(text("SELECT to_regclass('public.pos_devices')")) == (
            "pos_devices"
        )
