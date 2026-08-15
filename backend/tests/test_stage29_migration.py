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

STAGE29_TABLES = {
    "promotion_channels",
    "online_ordering_locations",
    "online_ordering_schedules",
    "online_ordering_stations",
    "online_orders",
    "online_order_actions",
}


def _config(database_url: str) -> Config:
    config = Config(str(Path("alembic.ini")))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _surface(connection):
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    return {
        "revision": connection.scalar(text("SELECT version_num FROM alembic_version")),
        "tables": tables,
        "sales_columns": {
            column["name"]: column["nullable"]
            for column in inspector.get_columns("sales_orders")
        },
        "online_uniques": {
            tuple(value["column_names"])
            for value in inspector.get_unique_constraints("online_orders")
        }
        if "online_orders" in tables
        else set(),
        "indexes": {
            value["name"]
            for value in inspector.get_indexes("online_order_actions")
        }
        if "online_order_actions" in tables
        else set(),
    }


async def _snapshot(database_url: str):
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            return await connection.run_sync(_surface)
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_stage29_migration_is_direct_from_stage27_and_reversible() -> None:
    source_url = os.getenv("POSTGRES_TEST_URL")
    if not source_url:
        pytest.skip("POSTGRES_TEST_URL is required for Stage 29 migration gate")
    source = make_url(source_url)
    database_name = f"beanly_stage29_migration_{uuid4().hex}"
    admin_url = source.set(database="postgres").render_as_string(hide_password=False)
    database_url = source.set(database=database_name).render_as_string(hide_password=False)
    admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as connection:
            await connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
        config = _config(database_url)
        await asyncio.to_thread(command.upgrade, config, "0027_kitchen_fulfillment")
        ids = {name: str(uuid4()) for name in ("user", "organization", "promotion")}
        engine = create_async_engine(database_url)
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO users (id,email,password_hash,first_name,last_name,"
                    "is_active,email_verified,created_at,updated_at) VALUES "
                    "(:user,'stage29-migration@example.com','x','Stage','Owner',true,true,now(),now())"
                ),
                ids,
            )
            await connection.execute(
                text(
                    "INSERT INTO organizations (id,name,country_code,currency_code,status,"
                    "created_by,created_at,updated_at) VALUES "
                    "(:organization,'Stage 29','KZ','KZT','active',:user,now(),now())"
                ),
                ids,
            )
            await connection.execute(
                text(
                    "INSERT INTO promotions (id,organization_id,name,pos_name,status,"
                    "application_mode,discount_kind,scope,percent_rate,priority,stacking_policy,"
                    "include_modifier_price,all_locations,requires_override_permission,created_by,"
                    "created_at,updated_at) VALUES (:promotion,:organization,'Legacy','Legacy',"
                    "'ACTIVE','AUTOMATIC','PERCENT','ORDER',10,0,'EXCLUSIVE',false,true,false,"
                    ":user,now(),now())"
                ),
                ids,
            )
        await engine.dispose()
        before = await _snapshot(database_url)
        await asyncio.to_thread(command.upgrade, config, "0029_online_ordering")
        upgraded = await _snapshot(database_url)
        assert upgraded["revision"] == "0029_online_ordering"
        assert set(upgraded["tables"]) - set(before["tables"]) == STAGE29_TABLES
        assert upgraded["sales_columns"]["order_source"] is False
        assert upgraded["sales_columns"]["created_by_user_id"] is True
        assert {("organization_id", "client_order_id"), ("sales_order_id",)} <= upgraded[
            "online_uniques"
        ]
        assert {"uq_online_order_action_client", "uq_online_order_action_event"} <= upgraded[
            "indexes"
        ]
        engine = create_async_engine(database_url)
        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    text(
                        "SELECT channel FROM promotion_channels "
                        "WHERE promotion_id=:promotion"
                    ),
                    ids,
                )
                == "POS"
            )
        await engine.dispose()
        await asyncio.to_thread(command.downgrade, config, "0027_kitchen_fulfillment")
        assert await _snapshot(database_url) == before
        await asyncio.to_thread(command.upgrade, config, "0029_online_ordering")
        assert await _snapshot(database_url) == upgraded
        await asyncio.to_thread(command.upgrade, config, "head")
        await asyncio.to_thread(command.check, config)
    finally:
        async with admin.connect() as connection:
            await connection.exec_driver_sql(
                f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)'
            )
        await admin.dispose()
