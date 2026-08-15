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

STAGE27_TABLES = {
    "kitchen_stations",
    "kitchen_routing_rules",
    "kitchen_tickets",
    "kitchen_ticket_items",
    "kitchen_ticket_item_modifiers",
    "kitchen_work_items",
    "kitchen_actions",
}


def _config(database_url: str) -> Config:
    config = Config(str(Path("alembic.ini")))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _surface(sync_connection) -> dict[str, object]:
    inspector = inspect(sync_connection)
    tables = set(inspector.get_table_names())
    return {
        "revision": sync_connection.scalar(text("SELECT version_num FROM alembic_version")),
        "tables": tables,
        "columns": {
            table: {column["name"] for column in inspector.get_columns(table)}
            for table in STAGE27_TABLES & tables
        },
        "uniques": {
            table: {
                tuple(value["column_names"])
                for value in inspector.get_unique_constraints(table)
            }
            for table in STAGE27_TABLES & tables
        },
        "checks": {
            table: {
                value["name"] for value in inspector.get_check_constraints(table)
            }
            for table in STAGE27_TABLES & tables
        },
    }


async def _snapshot(database_url: str) -> dict[str, object]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            return await connection.run_sync(_surface)
    finally:
        await engine.dispose()


async def _seed_location(database_url: str) -> tuple[str, str]:
    user_id, organization_id, location_id = (str(uuid4()) for _ in range(3))
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO users "
                    "(id,email,password_hash,first_name,last_name,is_active,email_verified,"
                    "created_at,updated_at) VALUES "
                    "(:user,'stage27-migration@example.com','x','Kitchen','Owner',"
                    "true,true,now(),now())"
                ),
                {"user": user_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO organizations "
                    "(id,name,country_code,currency_code,status,created_by,created_at,updated_at) "
                    "VALUES (:organization,'Stage 27','KZ','KZT','active',:user,now(),now())"
                ),
                {"organization": organization_id, "user": user_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO locations "
                    "(id,organization_id,name,timezone,is_active,is_primary,"
                    "fiscal_enforcement_mode,cash_variance_approval_threshold_minor,"
                    "created_at,updated_at) VALUES "
                    "(:location,:organization,'Kitchen','Asia/Almaty',true,true,"
                    "'DISABLED',0,now(),now())"
                ),
                {"location": location_id, "organization": organization_id},
            )
        return organization_id, location_id
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_stage27_migration_stage26_down_reup_default_and_check() -> None:
    source_url = os.getenv("POSTGRES_TEST_URL")
    if not source_url:
        pytest.skip("POSTGRES_TEST_URL is required for the PostgreSQL migration gate")
    source = make_url(source_url)
    database_name = f"beanly_stage27_migration_{uuid4().hex}"
    admin_url = source.set(database="postgres").render_as_string(hide_password=False)
    database_url = source.set(database=database_name).render_as_string(hide_password=False)
    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with admin_engine.connect() as connection:
            await connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
        config = _config(database_url)
        await asyncio.to_thread(command.upgrade, config, "0026_cash_management")
        organization_id, location_id = await _seed_location(database_url)
        before = await _snapshot(database_url)
        await asyncio.to_thread(command.upgrade, config, "0027_kitchen_fulfillment")
        upgraded = await _snapshot(database_url)
        assert upgraded["revision"] == "0027_kitchen_fulfillment"
        assert set(upgraded["tables"]) - set(before["tables"]) == STAGE27_TABLES
        assert {
            "organization_id",
            "location_id",
            "order_id",
            "payment_id",
            "status",
            "ordered_at",
            "fired_at",
            "version",
        } <= upgraded["columns"]["kitchen_tickets"]
        assert ("organization_id", "order_id") in upgraded["uniques"]["kitchen_tickets"]
        assert ("organization_id", "client_action_id") in upgraded["uniques"][
            "kitchen_actions"
        ]
        assert "ck_kitchen_routing_target" in upgraded["checks"]["kitchen_routing_rules"]
        engine = create_async_engine(database_url)
        try:
            async with engine.connect() as connection:
                default = (
                    await connection.execute(
                        text(
                            "SELECT organization_id,location_id,name,code,role,is_default "
                            "FROM kitchen_stations WHERE location_id=:location"
                        ),
                        {"location": location_id},
                    )
                ).mappings().one()
                assert {
                    **dict(default),
                    "organization_id": str(default["organization_id"]),
                    "location_id": str(default["location_id"]),
                } == {
                    "organization_id": organization_id,
                    "location_id": location_id,
                    "name": "Preparation",
                    "code": "PREPARATION",
                    "role": "PREP_EXPO",
                    "is_default": True,
                }
        finally:
            await engine.dispose()
        await asyncio.to_thread(command.downgrade, config, "0026_cash_management")
        assert await _snapshot(database_url) == before
        await asyncio.to_thread(command.upgrade, config, "0027_kitchen_fulfillment")
        assert await _snapshot(database_url) == upgraded
        await asyncio.to_thread(command.upgrade, config, "head")
        await asyncio.to_thread(command.check, config)
    finally:
        async with admin_engine.connect() as connection:
            await connection.exec_driver_sql(
                f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)'
            )
        await admin_engine.dispose()
