import asyncio
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

STAGE25_TABLES = {
    "customers",
    "loyalty_programs",
    "loyalty_tiers",
    "loyalty_accounts",
    "loyalty_ledger_entries",
    "loyalty_redemptions",
    "promotion_audiences",
    "promotion_audience_customers",
}


def _config(database_url: str) -> Config:
    config = Config(str(Path("alembic.ini")))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _surface(sync_connection) -> dict[str, object]:
    inspector = inspect(sync_connection)
    tables = set(inspector.get_table_names())
    tracked = STAGE25_TABLES | {"sales_orders", "sales_order_discounts"}
    return {
        "revision": sync_connection.scalar(text("SELECT version_num FROM alembic_version")),
        "tables": tables,
        "columns": {
            table: {column["name"] for column in inspector.get_columns(table)}
            for table in tracked & tables
        },
        "checks": {
            table: {value["name"] for value in inspector.get_check_constraints(table)}
            for table in tracked & tables
        },
        "uniques": {
            table: {
                tuple(value["column_names"])
                for value in inspector.get_unique_constraints(table)
            }
            for table in tracked & tables
        },
        "immutable_trigger": bool(
            sync_connection.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_trigger "
                    "WHERE tgname = 'trg_loyalty_ledger_immutable' AND NOT tgisinternal)"
                )
            )
        ),
    }


async def _snapshot(database_url: str) -> dict[str, object]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            return await connection.run_sync(_surface)
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_stage25_migration_up_down_reup_and_check() -> None:
    source_url = os.getenv("POSTGRES_TEST_URL")
    if not source_url:
        pytest.skip("POSTGRES_TEST_URL is required for the PostgreSQL migration gate")

    source = make_url(source_url)
    database_name = f"beanly_stage25_migration_{uuid4().hex}"
    admin_url = source.set(database="postgres").render_as_string(hide_password=False)
    database_url = source.set(database=database_name).render_as_string(hide_password=False)
    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with admin_engine.connect() as connection:
            await connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')

        config = _config(database_url)
        await asyncio.to_thread(command.upgrade, config, "0024_promotions_pricing")
        before = await _snapshot(database_url)

        await asyncio.to_thread(command.upgrade, config, "0025_customers_crm_loyalty")
        upgraded = await _snapshot(database_url)
        assert upgraded["revision"] == "0025_customers_crm_loyalty"
        assert set(upgraded["tables"]) - set(before["tables"]) == STAGE25_TABLES
        assert {
            "customer_id",
            "customer_name_snapshot",
            "customer_phone_snapshot",
        } <= upgraded["columns"]["sales_orders"]
        assert "audience_kind" in upgraded["columns"]["sales_order_discounts"]
        assert "related_source_id" in upgraded["columns"]["loyalty_ledger_entries"]
        assert ("organization_id", "phone_normalized") in upgraded["uniques"]["customers"]
        assert (
            "organization_id",
            "customer_id",
            "kind",
            "source_type",
            "source_id",
        ) in upgraded["uniques"]["loyalty_ledger_entries"]
        assert "ck_loyalty_account_balance" not in upgraded["checks"]["loyalty_accounts"]
        assert "ck_loyalty_account_lifetime" in upgraded["checks"]["loyalty_accounts"]
        assert upgraded["immutable_trigger"] is True

        await asyncio.to_thread(command.downgrade, config, "0024_promotions_pricing")
        assert await _snapshot(database_url) == before
        await asyncio.to_thread(command.upgrade, config, "0025_customers_crm_loyalty")
        assert await _snapshot(database_url) == upgraded
        assert ScriptDirectory.from_config(config).get_current_head() == (
            "0025_customers_crm_loyalty"
        )
        await asyncio.to_thread(command.upgrade, config, "head")
        await asyncio.to_thread(command.check, config)
    finally:
        async with admin_engine.connect() as connection:
            await connection.exec_driver_sql(
                f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)'
            )
        await admin_engine.dispose()
