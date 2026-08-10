import asyncio
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

INDEXES = {
    "ix_sales_orders_dashboard_paid": (
        "sales_orders",
        ("organization_id", "location_id", "paid_at"),
    ),
    "ix_payments_dashboard_completed": (
        "payments",
        ("organization_id", "location_id", "completed_at"),
    ),
    "ix_finance_entries_dashboard_scope": (
        "finance_entries",
        ("organization_id", "location_id", "effective_at"),
    ),
}


def _config(database_url: str) -> Config:
    config = Config(str(Path("alembic.ini")))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _schema(connection) -> tuple[set[str], dict[str, tuple[str, ...]]]:
    inspector = inspect(connection)
    indexes = {
        value["name"]: tuple(value["column_names"])
        for table in {table for table, _ in INDEXES.values()}
        for value in inspector.get_indexes(table)
        if value["name"] in INDEXES
    }
    return set(inspector.get_table_names()), indexes


@pytest.mark.anyio
async def test_0016_dashboard_indexes_upgrade_downgrade_and_query_plans() -> None:
    source_url = os.getenv("POSTGRES_TEST_URL")
    if not source_url:
        pytest.skip("POSTGRES_TEST_URL is required for the PostgreSQL integration gate")

    database_name = f"beanly_dashboard_{uuid4().hex}"
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
            tables_0015, indexes_0015 = await connection.run_sync(_schema)
            definitions_0015 = await _index_definitions(connection)
            revision_0015 = await connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )
        assert revision_0015 == "0015_finance"
        assert not indexes_0015
        assert not definitions_0015

        await asyncio.to_thread(
            command.upgrade, config, "0016_dashboard_query_indexes"
        )
        async with engine.connect() as connection:
            tables_0016, indexes_0016 = await connection.run_sync(_schema)
            revision_0016 = await connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )
            definitions = await _index_definitions(connection)
        assert revision_0016 == "0016_dashboard_query_indexes"
        assert tables_0016 == tables_0015
        assert set(indexes_0016) <= set(INDEXES)
        assert set(definitions) == set(INDEXES)
        for name, (table, columns) in INDEXES.items():
            assert f"ON public.{table} USING btree ({', '.join(columns)})" in (
                definitions[name]
            )
        assert "WHERE ((status)::text = 'PAID'::text)" in definitions[
            "ix_sales_orders_dashboard_paid"
        ]
        assert "ix_stock_balances_negative" not in definitions

        await asyncio.to_thread(command.downgrade, config, "0015_finance")
        async with engine.connect() as connection:
            tables_down, indexes_down = await connection.run_sync(_schema)
            definitions_down = await _index_definitions(connection)
            revision_down = await connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )
        assert revision_down == "0015_finance"
        assert tables_down == tables_0015
        assert not indexes_down
        assert not definitions_down

        await asyncio.to_thread(
            command.upgrade, config, "0016_dashboard_query_indexes"
        )
        async with engine.begin() as connection:
            await _seed_dashboard_fixture(connection)
            await connection.execute(text("ANALYZE"))
        async with engine.connect() as connection:
            plans = {
                "ix_sales_orders_dashboard_paid": await _plan(
                    connection,
                    "SELECT count(*) FROM sales_orders "
                    "WHERE organization_id = :organization_id "
                    "AND location_id = :location_id AND status = 'PAID' "
                    "AND paid_at >= '2026-08-01T00:00:00Z' "
                    "AND paid_at < '2026-09-01T00:00:00Z'",
                ),
                "ix_payments_dashboard_completed": await _plan(
                    connection,
                    "SELECT sum(amount_minor), count(*) FROM payments "
                    "WHERE organization_id = :organization_id "
                    "AND location_id = :location_id "
                    "AND completed_at >= '2026-08-01T00:00:00Z' "
                    "AND completed_at < '2026-09-01T00:00:00Z'",
                ),
                "ix_finance_entries_dashboard_scope": await _plan(
                    connection,
                    "SELECT entry_type, sum(amount) FROM finance_entries "
                    "WHERE organization_id = :organization_id "
                    "AND location_id = :location_id "
                    "AND effective_at >= '2026-08-01T00:00:00Z' "
                    "AND effective_at < '2026-09-01T00:00:00Z' GROUP BY entry_type",
                ),
            }
        assert all(plans.values()), plans
    finally:
        await engine.dispose()
        try:
            async with admin_engine.connect() as connection:
                await connection.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname = :database_name AND pid <> pg_backend_pid()"
                    ),
                    {"database_name": database_name},
                )
                await connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}"'))
        finally:
            await admin_engine.dispose()


async def _plan(connection, query: str) -> set[str]:
    result = await connection.scalar(
        text(f"EXPLAIN (ANALYZE, COSTS OFF, FORMAT JSON) {query}"),
        {
            "organization_id": "10000000-0000-0000-0000-000000000001",
            "location_id": "20000000-0000-0000-0000-000000000001",
        },
    )
    names: set[str] = set()

    def collect(value) -> None:
        if isinstance(value, dict):
            if index_name := value.get("Index Name"):
                names.add(index_name)
            for nested in value.values():
                collect(nested)
        elif isinstance(value, list):
            for nested in value:
                collect(nested)

    collect(result)
    return names


async def _index_definitions(connection) -> dict[str, str]:
    return dict(
        (
            await connection.execute(
                text(
                    "SELECT indexname, indexdef FROM pg_indexes "
                    "WHERE schemaname = current_schema() AND indexname IN ("
                    "'ix_sales_orders_dashboard_paid',"
                    "'ix_payments_dashboard_completed',"
                    "'ix_finance_entries_dashboard_scope',"
                    "'ix_stock_balances_negative')"
                )
            )
        ).all()
    )


async def _seed_dashboard_fixture(connection) -> None:
    raw_connection = await connection.get_raw_connection()
    await raw_connection.driver_connection.execute(
            "INSERT INTO users (id,email,password_hash,first_name,last_name) VALUES "
            "('00000000-0000-0000-0000-000000000001',"
            "'dashboard-plan@example.com','unused','Plan','Owner');"
            "INSERT INTO organizations (id,name,country_code,currency_code,created_by) "
            "VALUES ('10000000-0000-0000-0000-000000000001','Plan','KZ','KZT',"
            "'00000000-0000-0000-0000-000000000001');"
            "INSERT INTO locations (id,organization_id,name,timezone,is_primary) VALUES "
            "('20000000-0000-0000-0000-000000000001',"
            "'10000000-0000-0000-0000-000000000001','Target','Asia/Almaty',true),"
            "('20000000-0000-0000-0000-000000000002',"
            "'10000000-0000-0000-0000-000000000001','Noise','Asia/Almaty',false);"
            "INSERT INTO warehouses (id,organization_id,location_id,name) VALUES "
            "('30000000-0000-0000-0000-000000000001',"
            "'10000000-0000-0000-0000-000000000001',"
            "'20000000-0000-0000-0000-000000000001','Target'),"
            "('30000000-0000-0000-0000-000000000002',"
            "'10000000-0000-0000-0000-000000000001',"
            "'20000000-0000-0000-0000-000000000002','Noise');"
            "INSERT INTO pos_registers "
            "(id,organization_id,location_id,name,created_by_user_id) VALUES "
            "('40000000-0000-0000-0000-000000000001',"
            "'10000000-0000-0000-0000-000000000001',"
            "'20000000-0000-0000-0000-000000000001','Target',"
            "'00000000-0000-0000-0000-000000000001'),"
            "('40000000-0000-0000-0000-000000000002',"
            "'10000000-0000-0000-0000-000000000001',"
            "'20000000-0000-0000-0000-000000000002','Noise',"
            "'00000000-0000-0000-0000-000000000001');"
            "INSERT INTO register_shifts "
            "(id,organization_id,location_id,register_id,warehouse_id,status,"
            "opened_by_user_id,closed_by_user_id,opened_at,closed_at) VALUES "
            "('50000000-0000-0000-0000-000000000001',"
            "'10000000-0000-0000-0000-000000000001',"
            "'20000000-0000-0000-0000-000000000001',"
            "'40000000-0000-0000-0000-000000000001',"
            "'30000000-0000-0000-0000-000000000001','CLOSED',"
            "'00000000-0000-0000-0000-000000000001',"
            "'00000000-0000-0000-0000-000000000001',now(),now()),"
            "('50000000-0000-0000-0000-000000000002',"
            "'10000000-0000-0000-0000-000000000001',"
            "'20000000-0000-0000-0000-000000000002',"
            "'40000000-0000-0000-0000-000000000002',"
            "'30000000-0000-0000-0000-000000000002','CLOSED',"
            "'00000000-0000-0000-0000-000000000001',"
            "'00000000-0000-0000-0000-000000000001',now(),now())"
    )
    await connection.execute(
        text(
            "INSERT INTO sales_orders "
            "(id,organization_id,location_id,shift_id,warehouse_id,number,client_order_id,"
            "order_type,status,currency_code,subtotal_minor,total_minor,created_by_user_id,"
            "paid_by_user_id,paid_at) SELECT md5('order-' || g)::uuid,"
            "'10000000-0000-0000-0000-000000000001',"
            "CASE WHEN g <= 2000 THEN '20000000-0000-0000-0000-000000000001'::uuid "
            "ELSE '20000000-0000-0000-0000-000000000002'::uuid END,"
            "CASE WHEN g <= 2000 THEN '50000000-0000-0000-0000-000000000001'::uuid "
            "ELSE '50000000-0000-0000-0000-000000000002'::uuid END,"
            "CASE WHEN g <= 2000 THEN '30000000-0000-0000-0000-000000000001'::uuid "
            "ELSE '30000000-0000-0000-0000-000000000002'::uuid END,"
            "g,md5('client-order-' || g)::uuid,'TAKEAWAY','PAID','KZT',100,100,"
            "'00000000-0000-0000-0000-000000000001',"
            "'00000000-0000-0000-0000-000000000001',"
            "CASE WHEN g <= 100 OR g BETWEEN 2001 AND 3900 "
            "THEN '2026-08-01T00:00:00Z'::timestamptz + g * interval '1 minute' "
            "ELSE '2026-07-01T00:00:00Z'::timestamptz + g * interval '1 minute' END "
            "FROM generate_series(1,20000) g"
        )
    )
    await connection.execute(
        text(
            "INSERT INTO payments "
            "(id,organization_id,location_id,order_id,shift_id,client_payment_id,"
            "currency_code,amount_minor,created_by_user_id,completed_at) SELECT "
            "md5('payment-' || g)::uuid,'10000000-0000-0000-0000-000000000001',"
            "CASE WHEN g <= 2000 THEN '20000000-0000-0000-0000-000000000001'::uuid "
            "ELSE '20000000-0000-0000-0000-000000000002'::uuid END,"
            "md5('order-' || g)::uuid,"
            "CASE WHEN g <= 2000 THEN '50000000-0000-0000-0000-000000000001'::uuid "
            "ELSE '50000000-0000-0000-0000-000000000002'::uuid END,"
            "md5('client-payment-' || g)::uuid,'KZT',100,"
            "'00000000-0000-0000-0000-000000000001',"
            "CASE WHEN g <= 100 OR g BETWEEN 2001 AND 3900 "
            "THEN '2026-08-01T00:00:00Z'::timestamptz + g * interval '1 minute' "
            "ELSE '2026-07-01T00:00:00Z'::timestamptz + g * interval '1 minute' END "
            "FROM generate_series(1,20000) g"
        )
    )
    await connection.execute(
        text(
            "INSERT INTO finance_entries "
            "(id,organization_id,location_id,entry_type,amount,currency_code,effective_at,"
            "source_type,source_id,entry_role,created_at) SELECT "
            "md5('finance-' || g)::uuid,'10000000-0000-0000-0000-000000000001',"
            "CASE WHEN g <= 2000 THEN '20000000-0000-0000-0000-000000000001'::uuid "
            "ELSE '20000000-0000-0000-0000-000000000002'::uuid END,"
            "'REVENUE',1,'KZT',"
            "CASE WHEN g <= 100 OR g BETWEEN 2001 AND 3900 "
            "THEN '2026-08-01T00:00:00Z'::timestamptz + g * interval '1 minute' "
            "ELSE '2026-07-01T00:00:00Z'::timestamptz + g * interval '1 minute' END,"
            "'DASHBOARD_TEST',md5('finance-source-' || g)::uuid,'REVENUE',now() "
            "FROM generate_series(1,20000) g"
        )
    )
