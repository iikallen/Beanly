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

STAGE26_TABLES = {
    "cash_drawer_sessions",
    "cash_drawer_movements",
    "cash_drawer_close_snapshots",
    "cash_drawer_fiscal_states",
}


def _config(database_url: str) -> Config:
    config = Config(str(Path("alembic.ini")))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _surface(sync_connection) -> dict[str, object]:
    inspector = inspect(sync_connection)
    tables = set(inspector.get_table_names())
    tracked = STAGE26_TABLES | {"locations", "register_shifts"}
    return {
        "revision": sync_connection.scalar(text("SELECT version_num FROM alembic_version")),
        "tables": tables,
        "columns": {
            table: {column["name"] for column in inspector.get_columns(table)}
            for table in tracked & tables
        },
        "checks": {
            table: {value["sqltext"] for value in inspector.get_check_constraints(table)}
            for table in tracked & tables
        },
        "uniques": {
            table: {
                tuple(value["column_names"]) for value in inspector.get_unique_constraints(table)
            }
            for table in tracked & tables
        },
        "immutable_triggers": set(
            sync_connection.scalars(
                text(
                    "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal "
                    "AND tgrelid IN ('cash_drawer_movements'::regclass, "
                    "'cash_drawer_close_snapshots'::regclass)"
                )
            )
        )
        if STAGE26_TABLES <= tables
        else set(),
    }


async def _snapshot(database_url: str) -> dict[str, object]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            return await connection.run_sync(_surface)
    finally:
        await engine.dispose()


async def _seed_open_shift(database_url: str) -> str:
    ids = {
        name: str(uuid4())
        for name in (
            "user",
            "organization",
            "location",
            "warehouse",
            "register",
            "shift",
        )
    }
    statements = (
        "INSERT INTO users (id,email,password_hash,first_name,last_name,is_active,email_verified,created_at,updated_at) "  # noqa: E501
        "VALUES (:user,'stage26-migration@example.com','x','Migration','Owner',true,true,now(),now())",  # noqa: E501
        "INSERT INTO organizations (id,name,country_code,currency_code,status,created_by,created_at,updated_at) "  # noqa: E501
        "VALUES (:organization,'Stage 26 migration','KZ','KZT','active',:user,now(),now())",
        "INSERT INTO locations (id,organization_id,name,timezone,is_active,is_primary,fiscal_enforcement_mode,created_at,updated_at) "  # noqa: E501
        "VALUES (:location,:organization,'Dostyk','Asia/Almaty',true,true,'DISABLED',now(),now())",
        "INSERT INTO warehouses (id,organization_id,location_id,name,is_active,created_at,updated_at) "  # noqa: E501
        "VALUES (:warehouse,:organization,:location,'Main',true,now(),now())",
        "INSERT INTO pos_registers (id,organization_id,location_id,name,is_active,created_by_user_id,created_at,updated_at) "  # noqa: E501
        "VALUES (:register,:organization,:location,'Front',true,:user,now(),now())",
        "INSERT INTO register_shifts (id,organization_id,location_id,register_id,warehouse_id,status,opened_by_user_id,opened_at,created_at,updated_at) "  # noqa: E501
        "VALUES (:shift,:organization,:location,:register,:warehouse,'OPEN',:user,now(),now(),now())",  # noqa: E501
    )
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            for statement in statements:
                await connection.execute(text(statement), ids)
        return ids["shift"]
    finally:
        await engine.dispose()


async def _backfilled_drawer(database_url: str, shift_id: str) -> dict[str, object]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        text(
                            "SELECT d.id,d.status,d.starting_cash_minor,d.currency_code,"
                            "count(m.id) FILTER (WHERE m.kind='OPENING_FLOAT') AS opening_count "
                            "FROM cash_drawer_sessions d LEFT JOIN cash_drawer_movements m "
                            "ON m.drawer_session_id=d.id WHERE d.shift_id=:shift_id "
                            "GROUP BY d.id"
                        ),
                        {"shift_id": shift_id},
                    )
                )
                .mappings()
                .one()
            )
            return dict(row)
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_stage26_migration_stage25_down_reup_head_and_check() -> None:
    source_url = os.getenv("POSTGRES_TEST_URL")
    if not source_url:
        pytest.skip("POSTGRES_TEST_URL is required for the PostgreSQL migration gate")

    source = make_url(source_url)
    database_name = f"beanly_stage26_migration_{uuid4().hex}"
    admin_url = source.set(database="postgres").render_as_string(hide_password=False)
    database_url = source.set(database=database_name).render_as_string(hide_password=False)
    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with admin_engine.connect() as connection:
            await connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')

        config = _config(database_url)
        await asyncio.to_thread(command.upgrade, config, "0025_customers_crm_loyalty")
        seeded_shift_id = await _seed_open_shift(database_url)
        before = await _snapshot(database_url)

        await asyncio.to_thread(command.upgrade, config, "0026_cash_management")
        upgraded = await _snapshot(database_url)
        assert upgraded["revision"] == "0026_cash_management"
        assert set(upgraded["tables"]) - set(before["tables"]) == STAGE26_TABLES
        assert {
            "id",
            "organization_id",
            "location_id",
            "register_id",
            "shift_id",
            "currency_code",
            "status",
            "starting_cash_minor",
            "expected_cash_minor_snapshot",
            "actual_cash_minor",
            "variance_minor",
            "client_open_id",
            "client_close_id",
            "version",
        } <= upgraded["columns"]["cash_drawer_sessions"]
        assert {
            "organization_id",
            "drawer_session_id",
            "kind",
            "amount_minor",
            "source_type",
            "source_id",
            "source_line_id",
            "client_movement_id",
            "reason",
        } <= upgraded["columns"]["cash_drawer_movements"]
        assert "cash_variance_approval_threshold_minor" in upgraded["columns"]["locations"]
        assert {
            "drawer_session_id",
            "fiscal_job_id",
            "status",
            "updated_at",
        } <= upgraded["columns"]["cash_drawer_fiscal_states"]
        assert ("shift_id",) in upgraded["uniques"]["cash_drawer_sessions"]
        assert {
            (
                "organization_id",
                "source_type",
                "source_id",
                "source_line_id",
            ),
            ("organization_id", "client_movement_id"),
        } <= upgraded["uniques"]["cash_drawer_movements"]
        assert len(upgraded["immutable_triggers"]) == 2
        assert any("CLOSING" in sql for sql in upgraded["checks"]["register_shifts"])
        backfilled = await _backfilled_drawer(database_url, seeded_shift_id)
        assert (
            backfilled["status"],
            backfilled["starting_cash_minor"],
            backfilled["currency_code"],
            backfilled["opening_count"],
        ) == ("OPEN", 0, "KZT", 1)

        engine = create_async_engine(database_url)
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text("UPDATE register_shifts SET status='CLOSING' WHERE id=:shift_id"),
                    {"shift_id": seeded_shift_id},
                )
        finally:
            await engine.dispose()

        await asyncio.to_thread(command.downgrade, config, "0025_customers_crm_loyalty")
        assert await _snapshot(database_url) == before
        await asyncio.to_thread(command.upgrade, config, "0026_cash_management")
        assert await _snapshot(database_url) == upgraded
        assert ScriptDirectory.from_config(config).get_current_head() == "0026_cash_management"
        await asyncio.to_thread(command.upgrade, config, "head")
        await asyncio.to_thread(command.check, config)
    finally:
        async with admin_engine.connect() as connection:
            await connection.exec_driver_sql(
                f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)'
            )
        await admin_engine.dispose()
