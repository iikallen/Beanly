import asyncio
import os
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from beanly.core.database.session import get_session
from beanly.core.events.handlers.registry import EventHandlerRegistry
from beanly.core.events.outbox.dispatcher import OutboxDispatcher
from beanly.core.events.outbox.models import OutboxEventModel
from beanly.core.events.outbox.repositories import OutboxRepository
from beanly.core.events.registry import to_envelope
from beanly.main import app
from beanly.modules.finance.application.projection_service import FinanceProjectionService
from beanly.modules.finance.backfill import FinanceBackfillService
from beanly.modules.finance.domain.entities import FinanceEntry
from beanly.modules.finance.domain.enums import FinanceEntryType
from beanly.modules.finance.infrastructure.db.models import (
    CashAccountModel,
    CashEntryModel,
    FinanceEntryModel,
)
from beanly.modules.finance.infrastructure.db.repositories import (
    SqlAlchemyFinanceRepository,
)
from beanly.modules.finance.infrastructure.handlers import register_finance_handlers
from beanly.modules.finance.infrastructure.source_reader import (
    SqlAlchemyFinanceSourceReader,
)
from beanly.modules.inventory.domain.events import InventoryTransferPosted
from beanly.modules.payments.domain.events import PaymentCompleted
from beanly.modules.purchasing.domain.events import (
    GoodsReceiptPosted,
    SupplierReturnPosted,
)

FINANCE_TABLES = {
    "expense_categories",
    "expenses",
    "finance_entries",
    "cash_accounts",
    "cash_entries",
    "cash_movements",
}


def _config(database_url: str) -> Config:
    config = Config(str(Path("alembic.ini")))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _finance_schema(sync_connection) -> dict:
    inspector = inspect(sync_connection)
    return {
        "revision": sync_connection.scalar(text("SELECT version_num FROM alembic_version")),
        "tables": set(inspector.get_table_names()),
        "columns": {
            table: {column["name"]: column for column in inspector.get_columns(table)}
            for table in FINANCE_TABLES
            if inspector.has_table(table)
        },
        "checks": {
            table: {
                constraint["name"] for constraint in inspector.get_check_constraints(table)
            }
            for table in FINANCE_TABLES
            if inspector.has_table(table)
        },
        "uniques": {
            table: {
                tuple(constraint["column_names"])
                for constraint in inspector.get_unique_constraints(table)
            }
            for table in FINANCE_TABLES
            if inspector.has_table(table)
        },
    }


@pytest.mark.anyio
async def test_0015_finance_upgrade_constraints_downgrade_and_reupgrade() -> None:
    source_url = os.getenv("POSTGRES_TEST_URL")
    if not source_url:
        pytest.skip("POSTGRES_TEST_URL is required for the PostgreSQL integration gate")

    database_name = f"beanly_finance_migration_{uuid4().hex}"
    source = make_url(source_url)
    admin_url = source.set(database="postgres").render_as_string(hide_password=False)
    test_url = source.set(database=database_name).render_as_string(hide_password=False)
    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    engine = create_async_engine(test_url)
    try:
        async with admin_engine.connect() as connection:
            await connection.execute(text(f'CREATE DATABASE "{database_name}"'))

        config = _config(test_url)
        await asyncio.to_thread(command.upgrade, config, "0015_finance")
        async with engine.connect() as connection:
            schema = await connection.run_sync(_finance_schema)

        assert schema["revision"] == "0015_finance"
        assert FINANCE_TABLES <= schema["tables"]
        assert "current_balance" not in schema["columns"]["cash_accounts"]
        assert str(schema["columns"]["finance_entries"]["amount"]["type"]) == (
            "NUMERIC(20, 6)"
        )
        assert str(schema["columns"]["cash_entries"]["amount_minor"]["type"]) == (
            "BIGINT"
        )
        assert (
            "source_event_id",
            "entry_role",
        ) in schema["uniques"]["finance_entries"]
        assert (
            "source_type",
            "source_id",
            "entry_role",
        ) in schema["uniques"]["finance_entries"]
        assert (
            "source_event_id",
            "entry_role",
        ) in schema["uniques"]["cash_entries"]
        assert (
            "source_type",
            "source_id",
            "entry_role",
        ) in schema["uniques"]["cash_entries"]
        assert "ck_finance_entry_quality" in schema["checks"]["finance_entries"]
        assert {
            "ck_cash_movement_accounts",
            "ck_cash_movement_derived_activity",
        } <= schema["checks"]["cash_movements"]

        user_id = uuid4()
        organization_id = uuid4()
        first_account_id = uuid4()
        second_account_id = uuid4()
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO users (id,email,password_hash,first_name,last_name) "
                    "VALUES (:id,:email,'unused','Schema','Owner')"
                ),
                {"id": user_id, "email": f"schema-{user_id}@example.com"},
            )
            await connection.execute(
                text(
                    "INSERT INTO organizations "
                    "(id,name,country_code,currency_code,created_by) "
                    "VALUES (:id,'Schema','KZ','KZT',:user_id)"
                ),
                {"id": organization_id, "user_id": user_id},
            )
            for account_id, name in (
                (first_account_id, "First"),
                (second_account_id, "Second"),
            ):
                await connection.execute(
                    text(
                        "INSERT INTO cash_accounts "
                        "(id,organization_id,name,type,currency_code,opening_balance_minor,"
                        "is_active,created_at,updated_at) VALUES "
                        "(:id,:organization_id,:name,'BANK','KZT',0,true,now(),now())"
                    ),
                    {
                        "id": account_id,
                        "organization_id": organization_id,
                        "name": name,
                    },
                )

        invalid_movements = (
            ("SUPPLIER_PAYMENT", None, second_account_id, "OPERATING"),
            ("OWNER_CONTRIBUTION", None, second_account_id, "OPERATING"),
            ("TRANSFER", first_account_id, None, "OPERATING"),
            ("TRANSFER", first_account_id, first_account_id, "OPERATING"),
        )
        for movement_type, from_id, to_id, activity in invalid_movements:
            with pytest.raises(IntegrityError):
                async with engine.begin() as connection:
                    await connection.execute(
                        text(
                            "INSERT INTO cash_movements "
                            "(id,organization_id,type,amount_minor,currency_code,"
                            "from_account_id,to_account_id,cash_flow_activity,occurred_at,"
                            "created_by,created_at) VALUES "
                            "(:id,:organization_id,:type,1,'KZT',:from_id,:to_id,:activity,"
                            "now(),:user_id,now())"
                        ),
                        {
                            "id": uuid4(),
                            "organization_id": organization_id,
                            "type": movement_type,
                            "from_id": from_id,
                            "to_id": to_id,
                            "activity": activity,
                            "user_id": user_id,
                        },
                    )

        for entry_type, quality in (("COGS", None), ("REVENUE", "COMPLETE")):
            with pytest.raises(IntegrityError):
                async with engine.begin() as connection:
                    await connection.execute(
                        text(
                            "INSERT INTO finance_entries "
                            "(id,organization_id,entry_type,amount,currency_code,effective_at,"
                            "source_type,source_id,entry_role,quality_status,created_at) VALUES "
                            "(:id,:organization_id,:entry_type,1,'KZT',now(),'TEST',:source_id,"
                            "'TEST',:quality,now())"
                        ),
                        {
                            "id": uuid4(),
                            "organization_id": organization_id,
                            "entry_type": entry_type,
                            "source_id": uuid4(),
                            "quality": quality,
                        },
                    )
        with pytest.raises(DBAPIError):
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO finance_entries "
                        "(id,organization_id,entry_type,amount,currency_code,effective_at,"
                        "source_type,source_id,entry_role,created_at) VALUES "
                        "(:id,:organization_id,'REVENUE',100000000000000.000000,'KZT',now(),"
                        "'TEST',:source_id,'RANGE',now())"
                    ),
                    {
                        "id": uuid4(),
                        "organization_id": organization_id,
                        "source_id": uuid4(),
                    },
                )

        await asyncio.to_thread(command.downgrade, config, "0014_inventory_operations")
        async with engine.connect() as connection:
            downgraded = await connection.run_sync(_finance_schema)
        assert downgraded["revision"] == "0014_inventory_operations"
        assert not FINANCE_TABLES & downgraded["tables"]

        await asyncio.to_thread(command.upgrade, config, "0015_finance")
        async with engine.connect() as connection:
            reupgraded = await connection.run_sync(_finance_schema)
        assert reupgraded["revision"] == "0015_finance"
        assert FINANCE_TABLES <= reupgraded["tables"]
    finally:
        await engine.dispose()
        async with admin_engine.connect() as connection:
            await connection.execute(
                text(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')
            )
        await admin_engine.dispose()


@pytest.mark.anyio
async def test_postgres_finance_handler_and_outbox_status_are_one_transaction() -> None:
    source_url = os.getenv("POSTGRES_TEST_URL")
    if not source_url:
        pytest.skip("POSTGRES_TEST_URL is required for the PostgreSQL integration gate")

    database_name = f"beanly_finance_atomic_{uuid4().hex}"
    source = make_url(source_url)
    admin_url = source.set(database="postgres").render_as_string(hide_password=False)
    test_url = source.set(database=database_name).render_as_string(hide_password=False)
    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    engine = create_async_engine(test_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    user_id = uuid4()
    organization_id = uuid4()
    location_id = uuid4()
    try:
        async with admin_engine.connect() as connection:
            await connection.execute(text(f'CREATE DATABASE "{database_name}"'))
        await asyncio.to_thread(command.upgrade, _config(test_url), "0015_finance")
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO users (id,email,password_hash,first_name,last_name) "
                    "VALUES (:id,:email,'unused','Finance','Owner')"
                ),
                {"id": user_id, "email": f"finance-{user_id}@example.com"},
            )
            await connection.execute(
                text(
                    "INSERT INTO organizations "
                    "(id,name,country_code,currency_code,created_by) "
                    "VALUES (:id,'Finance','KZ','KZT',:user_id)"
                ),
                {"id": organization_id, "user_id": user_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO locations "
                    "(id,organization_id,name,timezone) "
                    "VALUES (:id,:organization_id,'Dostyk','Asia/Almaty')"
                ),
                {"id": location_id, "organization_id": organization_id},
            )

        async def add_event():
            envelope = to_envelope(
                PaymentCompleted(
                    uuid4(), uuid4(), organization_id, uuid4(), 100_00
                )
            )
            async with sessions() as session:
                await OutboxRepository(session).add_many((envelope,))
                await session.commit()
            return envelope

        async def dispatch(envelope, *, fail: bool) -> None:
            async with sessions() as session:
                async def handler(value) -> None:
                    session.add(
                        FinanceEntryModel(
                            id=uuid4(),
                            organization_id=organization_id,
                            location_id=None,
                            entry_type="REVENUE",
                            amount=Decimal("100.000000"),
                            currency_code="KZT",
                            effective_at=datetime.now(UTC),
                            description=None,
                            expense_category_id=None,
                            source_type="PAYMENT",
                            source_id=value.aggregate_id,
                            source_event_id=value.id,
                            entry_role="REVENUE",
                            reversal_of_id=None,
                            quality_status=None,
                            created_at=datetime.now(UTC),
                        )
                    )
                    await session.flush()
                    if fail:
                        raise RuntimeError("fault after finance insert")

                handlers = EventHandlerRegistry()
                handlers.register("payment.completed", 1, handler)
                assert await OutboxDispatcher(
                    OutboxRepository(session), handlers, f"worker-{envelope.id}"
                ).run_once() == 1

        failed = await add_event()
        await dispatch(failed, fail=True)
        async with sessions() as session:
            assert await session.scalar(select(func.count(FinanceEntryModel.id))) == 0
            failed_row = await session.get(OutboxEventModel, failed.id)
            assert failed_row is not None
            assert failed_row.processed_at is None
            assert failed_row.attempts == 1

        succeeded = await add_event()
        await dispatch(succeeded, fail=False)
        async with sessions() as session:
            assert await session.scalar(select(func.count(FinanceEntryModel.id))) == 1
            succeeded_row = await session.get(OutboxEventModel, succeeded.id)
            assert succeeded_row is not None
            assert succeeded_row.processed_at is not None
            assert succeeded_row.attempts == 0

        async def system_account() -> UUID:
            async with sessions() as session:
                value = await SqlAlchemyFinanceRepository(session).system_account(
                    organization_id, location_id, "CASH", "KZT"
                )
                await session.commit()
                return value.id

        account_ids = await asyncio.gather(system_account(), system_account())
        assert account_ids[0] == account_ids[1]
        async with sessions() as session:
            assert await session.scalar(
                select(func.count(CashAccountModel.id)).where(
                    CashAccountModel.organization_id == organization_id,
                    CashAccountModel.location_id == location_id,
                    CashAccountModel.system_key == "PAYMENT:CASH",
                )
            ) == 1

        invalid = await add_event()
        async with sessions() as session:
            repository = SqlAlchemyFinanceRepository(session)

            async def invalid_handler(envelope) -> None:
                await repository.add_finance_entry(
                    FinanceEntry(
                        uuid4(),
                        organization_id,
                        None,
                        FinanceEntryType.COGS,
                        Decimal("-1.000000"),
                        "KZT",
                        datetime.now(UTC),
                        None,
                        None,
                        "TEST",
                        envelope.aggregate_id,
                        envelope.id,
                        "INVALID_COGS",
                        None,
                        None,
                        datetime.now(UTC),
                    )
                )

            handlers = EventHandlerRegistry()
            handlers.register("payment.completed", 1, invalid_handler)
            assert await OutboxDispatcher(
                OutboxRepository(session), handlers, "worker-invalid-finance"
            ).run_once() == 1
        async with sessions() as session:
            invalid_row = await session.get(OutboxEventModel, invalid.id)
            assert invalid_row is not None
            assert invalid_row.processed_at is None
            assert invalid_row.attempts == 1
            assert await session.scalar(select(func.count(FinanceEntryModel.id))) == 1
    finally:
        await engine.dispose()
        async with admin_engine.connect() as connection:
            await connection.execute(
                text(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')
            )
        await admin_engine.dispose()


@pytest.mark.anyio
async def test_postgres_finance_projection_idempotency_noops_and_backfill_rerun() -> None:
    source_url = os.getenv("POSTGRES_TEST_URL")
    if not source_url:
        pytest.skip("POSTGRES_TEST_URL is required for the PostgreSQL integration gate")

    database_name = f"beanly_finance_projection_{uuid4().hex}"
    source = make_url(source_url)
    admin_url = source.set(database="postgres").render_as_string(hide_password=False)
    test_url = source.set(database=database_name).render_as_string(hide_password=False)
    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    engine = create_async_engine(test_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with admin_engine.connect() as connection:
            await connection.execute(text(f'CREATE DATABASE "{database_name}"'))
        await asyncio.to_thread(command.upgrade, _config(test_url), "head")

        async def override_session():
            async with sessions() as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"origin": "http://localhost:3000"},
        ) as client:
            password = "correct-horse-battery-staple"
            assert (
                await client.post(
                    "/api/v1/auth/register",
                    json={
                        "email": "finance-projection@example.com",
                        "password": password,
                        "first_name": "Projection",
                        "last_name": "Owner",
                    },
                )
            ).status_code == 201
            login = await client.post(
                "/api/v1/auth/login",
                json={
                    "email": "finance-projection@example.com",
                    "password": password,
                },
            )
            auth = {"authorization": f"Bearer {login.json()['access_token']}"}
            workspace = await client.post(
                "/api/v1/organizations",
                headers=auth,
                json={
                    "name": "Projection",
                    "country_code": "KZ",
                    "currency_code": "KZT",
                    "first_location": {
                        "name": "Dostyk",
                        "timezone": "Asia/Almaty",
                    },
                },
            )
            assert workspace.status_code == 201, workspace.text
            organization_id = UUID(workspace.json()["organization"]["id"])
            location_id = UUID(workspace.json()["location"]["id"])
            headers = {**auth, "X-Organization-ID": str(organization_id)}
            warehouse = await client.post(
                "/api/v1/inventory/warehouses",
                headers=headers,
                json={"location_id": str(location_id), "name": "Main"},
            )
            assert warehouse.status_code == 201, warehouse.text
            warehouse_id = warehouse.json()["id"]

            item_ids = []
            for name in ("Count loss", "Count gain"):
                item = await client.post(
                    "/api/v1/inventory/items",
                    headers=headers,
                    json={"name": name, "base_unit": "g"},
                )
                assert item.status_code == 201, item.text
                item_ids.append(item.json()["id"])
            opening = await client.post(
                "/api/v1/inventory/opening-balances",
                headers={**headers, "Idempotency-Key": "finance-opening"},
                json={
                    "warehouse_id": warehouse_id,
                    "items": [
                        {
                            "inventory_item_id": item_ids[0],
                            "quantity": "1000",
                            "unit_code": "g",
                            "unit_cost_amount": "4.2",
                        },
                        {
                            "inventory_item_id": item_ids[1],
                            "quantity": "100",
                            "unit_code": "g",
                            "unit_cost_amount": "3",
                        },
                    ],
                },
            )
            assert opening.status_code == 201, opening.text

            reason = await client.post(
                "/api/v1/inventory/write-off-reasons",
                headers=headers,
                json={"name": "Spoilage"},
            )
            assert reason.status_code == 201, reason.text
            writeoff = await client.post(
                "/api/v1/inventory/write-offs",
                headers=headers,
                json={
                    "warehouse_id": warehouse_id,
                    "reason_id": reason.json()["id"],
                    "occurred_at": "2026-08-10T08:00:00Z",
                    "lines": [
                        {
                            "inventory_item_id": item_ids[0],
                            "quantity": "100",
                            "unit": "g",
                        }
                    ],
                },
            )
            assert writeoff.status_code == 201, writeoff.text
            writeoff_id = writeoff.json()["id"]
            assert (
                await client.post(
                    f"/api/v1/inventory/write-offs/{writeoff_id}/post",
                    headers=headers,
                )
            ).status_code == 200
            assert (
                await client.post(
                    f"/api/v1/inventory/write-offs/{writeoff_id}/reverse",
                    headers=headers,
                )
            ).status_code == 200

            count = await client.post(
                "/api/v1/inventory/counts",
                headers=headers,
                json={
                    "warehouse_id": warehouse_id,
                    "type": "PARTIAL",
                    "inventory_item_ids": item_ids,
                },
            )
            assert count.status_code == 201, count.text
            count_id = count.json()["id"]
            count_lines = await client.put(
                f"/api/v1/inventory/counts/{count_id}/lines",
                headers=headers,
                json={
                    "lines": [
                        {
                            "inventory_item_id": item_ids[0],
                            "counted_quantity": "900",
                            "unit": "g",
                        },
                        {
                            "inventory_item_id": item_ids[1],
                            "counted_quantity": "110",
                            "unit": "g",
                        },
                    ]
                },
            )
            assert count_lines.status_code == 200, count_lines.text
            posted_count = await client.post(
                f"/api/v1/inventory/counts/{count_id}/post",
                headers=headers,
                json={"confirm_stock_changes": False},
            )
            assert posted_count.status_code == 200, posted_count.text

            register = await client.post(
                "/api/v1/sales/registers",
                headers=headers,
                json={"location_id": str(location_id), "name": "Counter"},
            )
            assert register.status_code == 201, register.text
            shift = await client.post(
                "/api/v1/sales/shifts/open",
                headers=headers,
                json={
                    "register_id": register.json()["id"],
                    "warehouse_id": warehouse_id,
                },
            )
            assert shift.status_code == 201, shift.text
            menu_category = await client.post(
                "/api/v1/menu/categories",
                headers=headers,
                json={"name": "Coffee"},
            )
            assert menu_category.status_code == 201, menu_category.text
            product = await client.post(
                "/api/v1/menu/products",
                headers=headers,
                json={
                    "category_id": menu_category.json()["id"],
                    "name": "No-cost cappuccino",
                    "default_variant": {
                        "name": "Default",
                        "base_price_minor": 670000,
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
            variant_id = activated.json()["variants"][0]["id"]
            no_cost_item = await client.post(
                "/api/v1/inventory/items",
                headers=headers,
                json={"name": "No WAC", "base_unit": "pcs"},
            )
            assert no_cost_item.status_code == 201, no_cost_item.text
            recipe = await client.put(
                f"/api/v1/menu/variants/{variant_id}/recipe",
                headers=headers,
                json={
                    "components": [
                        {
                            "inventory_item_id": no_cost_item.json()["id"],
                            "quantity": "1",
                            "unit": "pcs",
                        }
                    ]
                },
            )
            assert recipe.status_code == 200, recipe.text
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
            order_item = await client.post(
                f"/api/v1/sales/orders/{order.json()['id']}/items",
                headers=headers,
                json={
                    "client_item_id": str(uuid4()),
                    "variant_id": variant_id,
                    "selected_option_ids": [],
                    "quantity": 1,
                },
            )
            assert order_item.status_code == 201, order_item.text
            payment = await client.post(
                f"/api/v1/payments/orders/{order.json()['id']}/complete",
                headers=headers,
                json={
                    "client_payment_id": str(uuid4()),
                    "lines": [
                        {
                            "method": "CASH",
                            "amount_minor": 200000,
                            "cash_received_minor": 200000,
                        },
                        {"method": "CARD", "amount_minor": 470000},
                    ],
                },
            )
            assert payment.status_code == 201, payment.text
            payment_body = payment.json()

        async with sessions() as session:
            repository = SqlAlchemyFinanceRepository(session)
            sources = SqlAlchemyFinanceSourceReader(session)
            registry = EventHandlerRegistry()
            register_finance_handlers(
                registry, FinanceProjectionService(repository, sources)
            )
            assert await OutboxDispatcher(
                OutboxRepository(session), registry, "finance-live", batch_size=100
            ).run_once() > 0

        async with sessions() as session:
            finance_rows = (
                await session.execute(
                    select(
                        FinanceEntryModel.entry_type,
                        FinanceEntryModel.amount,
                        FinanceEntryModel.quality_status,
                        FinanceEntryModel.entry_role,
                        FinanceEntryModel.reversal_of_id,
                    ).order_by(FinanceEntryModel.entry_type, FinanceEntryModel.entry_role)
                )
            ).all()
            assert len(finance_rows) == 6
            assert sum(amount for _, amount, *_ in finance_rows) == Decimal("6310.000000")
            assert (
                "REVENUE",
                Decimal("6700.000000"),
                None,
                "REVENUE",
                None,
            ) in finance_rows
            assert (
                "COGS",
                Decimal("0.000000"),
                "INCOMPLETE",
                "COGS",
                None,
            ) in finance_rows
            assert any(
                entry_type == "INVENTORY_LOSS"
                and amount == Decimal("-420.000000")
                and role == "INVENTORY_LOSS"
                for entry_type, amount, _, role, _ in finance_rows
            )
            assert any(
                entry_type == "INVENTORY_GAIN" and amount == Decimal("30.000000")
                for entry_type, amount, *_ in finance_rows
            )
            assert await session.scalar(select(func.count(CashEntryModel.id))) == 2
            assert (
                await session.execute(
                    select(CashEntryModel.amount_minor).order_by(CashEntryModel.amount_minor)
                )
            ).scalars().all() == [200000, 470000]
            assert await session.scalar(select(func.count(CashAccountModel.id))) == 2

            logical_duplicate = to_envelope(
                PaymentCompleted(
                    UUID(payment_body["id"]),
                    UUID(payment_body["order_id"]),
                    organization_id,
                    location_id,
                    670000,
                ),
                event_id=uuid4(),
            )
            ignored = (
                to_envelope(
                    GoodsReceiptPosted(organization_id, uuid4(), uuid4())
                ),
                to_envelope(
                    InventoryTransferPosted(
                        organization_id, uuid4(), uuid4(), uuid4()
                    )
                ),
                to_envelope(SupplierReturnPosted(organization_id, uuid4(), uuid4())),
            )
            await OutboxRepository(session).add_many((logical_duplicate, *ignored))
            await session.commit()

        async with sessions() as session:
            repository = SqlAlchemyFinanceRepository(session)
            sources = SqlAlchemyFinanceSourceReader(session)
            registry = EventHandlerRegistry()
            register_finance_handlers(
                registry, FinanceProjectionService(repository, sources)
            )
            assert await OutboxDispatcher(
                OutboxRepository(session), registry, "finance-retry", batch_size=10
            ).run_once() == 4
        async with sessions() as session:
            assert await session.scalar(select(func.count(FinanceEntryModel.id))) == 6
            assert await session.scalar(select(func.count(CashEntryModel.id))) == 2
            assert await session.scalar(select(func.count(CashAccountModel.id))) == 2

            await session.execute(text("DELETE FROM cash_entries"))
            await session.execute(text("DELETE FROM finance_entries"))
            await session.commit()

        async with sessions() as session:
            repository = SqlAlchemyFinanceRepository(session)
            sources = SqlAlchemyFinanceSourceReader(session)
            backfill = FinanceBackfillService(
                FinanceProjectionService(repository, sources), sources, repository
            )
            first = await backfill.run()
            second = await backfill.run()
            assert (first.payments, first.writeoffs, first.counts) == (1, 1, 1)
            assert second == first

        async with sessions() as session:
            rows = (
                await session.execute(
                    select(
                        FinanceEntryModel.source_type,
                        FinanceEntryModel.entry_role,
                        FinanceEntryModel.amount,
                        FinanceEntryModel.reversal_of_id,
                    )
                )
            ).all()
            assert len(rows) == 6
            original_writeoff = next(
                row
                for row in rows
                if row.source_type == "INVENTORY_WRITE_OFF"
            )
            reversed_writeoff = next(
                row
                for row in rows
                if row.source_type == "INVENTORY_WRITE_OFF_REVERSAL"
            )
            assert original_writeoff.amount == Decimal("-420.000000")
            assert reversed_writeoff.amount == Decimal("420.000000")
            assert reversed_writeoff.reversal_of_id is not None
            assert await session.scalar(select(func.count(CashEntryModel.id))) == 2
            assert await session.scalar(select(func.count(CashAccountModel.id))) == 2
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
        async with admin_engine.connect() as connection:
            await connection.execute(
                text(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')
            )
        await admin_engine.dispose()
