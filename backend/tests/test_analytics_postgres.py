import asyncio
import os
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from beanly.core.events.handlers.registry import EventHandlerRegistry
from beanly.core.events.outbox.dispatcher import OutboxDispatcher
from beanly.core.events.outbox.models import OutboxEventModel
from beanly.core.events.outbox.repositories import OutboxRepository
from beanly.core.events.registry import to_envelope
from beanly.modules.analytics.application.dto import SalesDailyDelta
from beanly.modules.analytics.infrastructure.db.models import AnalyticsSalesDailyModel
from beanly.modules.analytics.infrastructure.db.repositories import (
    SqlAlchemyAnalyticsRepository,
)
from beanly.modules.finance.infrastructure.db.models import FinanceEntryModel
from beanly.modules.payments.domain.events import PaymentCompleted

ANALYTICS_TABLES = {
    "analytics_projection_receipts",
    "analytics_sales_daily",
    "analytics_product_sales_daily",
    "analytics_hourly_sales",
    "analytics_location_metrics_daily",
    "analytics_inventory_consumption_daily",
}


def _config(database_url: str) -> Config:
    config = Config(str(Path("alembic.ini")))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _analytics_schema(sync_connection) -> dict:
    inspector = inspect(sync_connection)
    return {
        "revision": sync_connection.scalar(text("SELECT version_num FROM alembic_version")),
        "tables": set(inspector.get_table_names()),
        "columns": {
            table: {column["name"]: column for column in inspector.get_columns(table)}
            for table in ANALYTICS_TABLES
            if inspector.has_table(table)
        },
        "checks": {
            table: {
                constraint["name"] for constraint in inspector.get_check_constraints(table)
            }
            for table in ANALYTICS_TABLES
            if inspector.has_table(table)
        },
        "primary_keys": {
            table: tuple(inspector.get_pk_constraint(table)["constrained_columns"])
            for table in ANALYTICS_TABLES
            if inspector.has_table(table)
        },
        "indexes": {
            table: {
                index["name"]: tuple(index["column_names"])
                for index in inspector.get_indexes(table)
            }
            for table in ANALYTICS_TABLES
            if inspector.has_table(table)
        },
    }


@pytest.mark.anyio
async def test_0017_analytics_upgrade_contract_downgrade_and_reupgrade() -> None:
    source_url = os.getenv("POSTGRES_TEST_URL")
    if not source_url:
        pytest.skip("POSTGRES_TEST_URL is required for the PostgreSQL integration gate")

    database_name = f"beanly_analytics_migration_{uuid4().hex}"
    source = make_url(source_url)
    admin_url = source.set(database="postgres").render_as_string(hide_password=False)
    test_url = source.set(database=database_name).render_as_string(hide_password=False)
    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    engine = create_async_engine(test_url)
    try:
        async with admin_engine.connect() as connection:
            await connection.execute(text(f'CREATE DATABASE "{database_name}"'))

        config = _config(test_url)
        await asyncio.to_thread(command.upgrade, config, "0017_analytics_read_models")
        async with engine.connect() as connection:
            schema = await connection.run_sync(_analytics_schema)

        assert schema["revision"] == "0017_analytics_read_models"
        assert ANALYTICS_TABLES <= schema["tables"]
        assert schema["primary_keys"]["analytics_projection_receipts"] == (
            "projection_name",
            "source_type",
            "source_id",
        )
        assert schema["primary_keys"]["analytics_sales_daily"] == (
            "organization_id",
            "location_id",
            "local_date",
        )
        assert schema["primary_keys"]["analytics_product_sales_daily"] == (
            "organization_id",
            "location_id",
            "local_date",
            "product_variant_id",
        )
        assert schema["primary_keys"]["analytics_hourly_sales"] == (
            "organization_id",
            "location_id",
            "local_date",
            "local_hour",
        )
        assert schema["primary_keys"]["analytics_location_metrics_daily"] == (
            "organization_id",
            "location_id",
            "local_date",
        )
        assert schema["primary_keys"]["analytics_inventory_consumption_daily"] == (
            "organization_id",
            "location_id",
            "warehouse_id",
            "local_date",
            "inventory_item_id",
        )
        assert "ck_an_hour_local_hour" in schema["checks"]["analytics_hourly_sales"]
        assert "ck_an_sales_currency" in schema["checks"]["analytics_sales_daily"]
        assert str(
            schema["columns"]["analytics_sales_daily"]["revenue_amount"]["type"]
        ) == "NUMERIC(20, 6)"
        assert str(
            schema["columns"]["analytics_sales_daily"]["paid_orders"]["type"]
        ) == "BIGINT"
        assert schema["columns"]["analytics_projection_receipts"][
            "source_event_id"
        ]["nullable"]
        assert schema["indexes"]["analytics_sales_daily"][
            "ix_an_sales_org_date"
        ] == ("organization_id", "local_date")
        assert schema["indexes"]["analytics_product_sales_daily"][
            "ix_an_product_org_location_date"
        ] == ("organization_id", "location_id", "local_date")
        assert schema["indexes"]["analytics_inventory_consumption_daily"][
            "ix_an_consumption_org_location_date"
        ] == ("organization_id", "location_id", "local_date")

        await asyncio.to_thread(command.downgrade, config, "0016_dashboard_query_indexes")
        async with engine.connect() as connection:
            downgraded = await connection.run_sync(_analytics_schema)
        assert downgraded["revision"] == "0016_dashboard_query_indexes"
        assert not ANALYTICS_TABLES & downgraded["tables"]

        await asyncio.to_thread(command.upgrade, config, "0017_analytics_read_models")
        async with engine.connect() as connection:
            reupgraded = await connection.run_sync(_analytics_schema)
        assert reupgraded["revision"] == "0017_analytics_read_models"
        assert ANALYTICS_TABLES <= reupgraded["tables"]

        # The schema assertions above intentionally target the historical 0017
        # boundary. Exercise the current repository only after upgrading to the
        # current head so its mapped columns match the database.
        await asyncio.to_thread(command.upgrade, config, "head")

        user_id = uuid4()
        organization_id = uuid4()
        location_id = uuid4()
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO users (id,email,password_hash,first_name,last_name) "
                    "VALUES (:id,:email,'unused','Analytics','Owner')"
                ),
                {"id": user_id, "email": f"analytics-{user_id}@example.com"},
            )
            await connection.execute(
                text(
                    "INSERT INTO organizations "
                    "(id,name,country_code,currency_code,created_by) "
                    "VALUES (:id,'Analytics','KZ','KZT',:user_id)"
                ),
                {"id": organization_id, "user_id": user_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO locations "
                    "(id,organization_id,name,timezone,is_active,is_primary) "
                    "VALUES (:id,:organization_id,'Dostyk','Asia/Almaty',true,true)"
                ),
                {"id": location_id, "organization_id": organization_id},
            )

        sessions = async_sessionmaker(engine, expire_on_commit=False)
        local_date = date(2026, 8, 11)

        async def project(source_id, amount: Decimal) -> bool:
            async with sessions() as session:
                repository = SqlAlchemyAnalyticsRepository(session)
                accepted = await repository.add_receipt(
                    "SALE_ANALYTICS",
                    "PAYMENT",
                    source_id,
                    organization_id,
                    uuid4(),
                    datetime(2026, 8, 10, 20, 30, tzinfo=UTC),
                )
                if accepted:
                    await repository.upsert_sales(
                        SalesDailyDelta(
                            organization_id=organization_id,
                            location_id=location_id,
                            local_date=local_date,
                            timezone="Asia/Almaty",
                            currency_code="KZT",
                            revenue_amount=amount,
                            paid_orders=1,
                            items_sold=1,
                            cogs_amount=Decimal("1"),
                            incomplete_cogs_orders=0,
                            dine_in_orders=1,
                            takeaway_orders=0,
                            delivery_orders=0,
                        )
                    )
                await repository.commit()
                return accepted

        duplicate_source = uuid4()
        duplicate_results = await asyncio.gather(
            project(duplicate_source, Decimal("10")),
            project(duplicate_source, Decimal("10")),
        )
        assert sorted(duplicate_results) == [False, True]

        distinct_results = await asyncio.gather(
            project(uuid4(), Decimal("20")),
            project(uuid4(), Decimal("30")),
        )
        assert distinct_results == [True, True]
        async with sessions() as session:
            row = await session.get(
                AnalyticsSalesDailyModel,
                {
                    "organization_id": organization_id,
                    "location_id": location_id,
                    "local_date": local_date,
                },
            )
            assert row is not None
            assert row.revenue_amount == Decimal("60.000000")
            assert row.paid_orders == 3
            receipt_count = await session.scalar(
                text(
                    "SELECT count(*) FROM analytics_projection_receipts "
                    "WHERE organization_id = :organization_id"
                ),
                {"organization_id": organization_id},
            )
            assert receipt_count == 3

        envelope = to_envelope(
            PaymentCompleted(
                payment_id=uuid4(),
                order_id=uuid4(),
                organization_id=organization_id,
                location_id=location_id,
                amount_minor=100_00,
            )
        )
        async with sessions() as session:
            await OutboxRepository(session).add_many((envelope,))
            await session.commit()

        calls: list[str] = []
        async with sessions() as session:
            async def finance_handler(value) -> None:
                calls.append("finance")
                session.add(
                    FinanceEntryModel(
                        id=uuid4(),
                        organization_id=organization_id,
                        location_id=location_id,
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

            async def failing_analytics_handler(value) -> None:
                calls.append("analytics")
                repository = SqlAlchemyAnalyticsRepository(session)
                accepted = await repository.add_receipt(
                    "SALE_ANALYTICS",
                    "PAYMENT",
                    value.aggregate_id,
                    organization_id,
                    value.id,
                    value.occurred_at,
                )
                assert accepted
                await repository.upsert_sales(
                    SalesDailyDelta(
                        organization_id=organization_id,
                        location_id=location_id,
                        local_date=date(2026, 8, 12),
                        timezone="Asia/Almaty",
                        currency_code="KZT",
                        revenue_amount=Decimal("100"),
                        paid_orders=1,
                        items_sold=1,
                        cogs_amount=Decimal(0),
                        incomplete_cogs_orders=0,
                        dine_in_orders=1,
                        takeaway_orders=0,
                        delivery_orders=0,
                    )
                )
                await session.flush()
                raise RuntimeError("analytics projection failed")

            handlers = EventHandlerRegistry()
            handlers.register("payment.completed", 1, finance_handler)
            handlers.register("payment.completed", 1, failing_analytics_handler)
            assert await OutboxDispatcher(
                OutboxRepository(session), handlers, "analytics-rollback-worker"
            ).run_once() == 1

        assert calls == ["finance", "analytics"]
        async with sessions() as session:
            failed = await session.get(OutboxEventModel, envelope.id)
            assert failed is not None
            assert failed.processed_at is None
            assert failed.attempts == 1
            assert await session.scalar(
                text(
                    "SELECT count(*) FROM finance_entries "
                    "WHERE source_event_id = :event_id"
                ),
                {"event_id": envelope.id},
            ) == 0
            assert await session.scalar(
                text(
                    "SELECT count(*) FROM analytics_projection_receipts "
                    "WHERE source_event_id = :event_id"
                ),
                {"event_id": envelope.id},
            ) == 0
            assert await session.scalar(
                text(
                    "SELECT count(*) FROM analytics_sales_daily "
                    "WHERE organization_id = :organization_id "
                    "AND local_date = '2026-08-12'"
                ),
                {"organization_id": organization_id},
            ) == 0
    finally:
        await engine.dispose()
        async with admin_engine.connect() as connection:
            await connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :database_name AND pid <> pg_backend_pid()"
                ),
                {"database_name": database_name},
            )
            await connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}"'))
        await admin_engine.dispose()
