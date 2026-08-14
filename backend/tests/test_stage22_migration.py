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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

STAGE22_TABLES = {
    "external_payment_attempts",
    "fiscal_nkt_cache",
    "fiscal_receipts",
    "fiscal_routes",
    "integration_terminal_bindings",
}


def _config(database_url: str) -> Config:
    config = Config(str(Path("alembic.ini")))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _surface(sync_connection) -> dict[str, object]:
    inspector = inspect(sync_connection)
    tables = set(inspector.get_table_names())
    tracked = {
        "locations",
        "fiscal_variant_profiles",
        "payment_lines",
        *STAGE22_TABLES,
    }
    return {
        "revision": sync_connection.scalar(text("SELECT version_num FROM alembic_version")),
        "tables": tables,
        "columns": {
            table: {column["name"] for column in inspector.get_columns(table)}
            for table in tracked & tables
        },
        "indexes": {
            table: inspector.get_indexes(table) for table in STAGE22_TABLES & tables
        },
        "unique_constraints": {
            table: {
                tuple(value["column_names"])
                for value in inspector.get_unique_constraints(table)
            }
            for table in STAGE22_TABLES & tables
        },
    }


async def _snapshot(database_url: str) -> dict[str, object]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            return await connection.run_sync(_surface)
    finally:
        await engine.dispose()


async def _assert_nkt_rejects_non_digits(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            with pytest.raises(IntegrityError):
                await connection.execute(
                    text(
                        """
                        INSERT INTO fiscal_nkt_cache (
                            id, external_product_id, ntin, gtins, name_ru, name_kk,
                            category_code, status, fetched_at, expires_at, payload_hash
                        ) VALUES (
                            :id, 'external', 'ABCDEFGHIJKLM', '[]'::jsonb, 'name', 'name',
                            'category', 'ACTIVE', now(), now(), repeat('0', 64)
                        )
                        """
                    ),
                    {"id": uuid4()},
                )
            await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_stage22_migration_up_down_up_preserves_stage21_surface() -> None:
    source_url = os.getenv("POSTGRES_TEST_URL")
    if not source_url:
        pytest.skip("POSTGRES_TEST_URL is required for the PostgreSQL migration gate")

    source = make_url(source_url)
    database_name = f"beanly_stage22_migration_{uuid4().hex}"
    admin_url = source.set(database="postgres").render_as_string(hide_password=False)
    database_url = source.set(database=database_name).render_as_string(hide_password=False)
    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with admin_engine.connect() as connection:
            await connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')

        config = _config(database_url)
        await asyncio.to_thread(command.upgrade, config, "0021_refunds_fiscal_tax")
        before = await _snapshot(database_url)

        await asyncio.to_thread(command.upgrade, config, "0022_kz_live_integrations")
        upgraded = await _snapshot(database_url)
        assert upgraded["revision"] == "0022_kz_live_integrations"
        assert STAGE22_TABLES <= upgraded["tables"]
        columns = upgraded["columns"]
        assert {"nkt_verified_at", "nkt_external_product_id"} <= columns[
            "fiscal_variant_profiles"
        ]
        assert {
            "external_payment_attempt_id",
            "provider_code",
            "provider_transaction_id",
        } <= columns["payment_lines"]
        assert "fiscal_enforcement_mode" in columns["locations"]
        assert {
            "provider_correlation_id",
            "provider_request_id",
            "receipt_number",
            "receipt_url",
            "source_id",
            "source_type",
            "status",
        } <= columns["fiscal_receipts"]
        assert {
            "client_attempt_id",
            "payment_id",
            "request_hash",
            "status",
        } <= columns["external_payment_attempts"]
        assert ("organization_id", "client_attempt_id") in upgraded[
            "unique_constraints"
        ]["external_payment_attempts"]
        assert ("organization_id", "source_type", "source_id") in upgraded[
            "unique_constraints"
        ]["fiscal_receipts"]
        assert ("connection_id", "provider_correlation_id") in upgraded[
            "unique_constraints"
        ]["fiscal_receipts"]
        assert ("ntin",) in upgraded["unique_constraints"]["fiscal_nkt_cache"]
        assert ("register_id", "provider_code") in upgraded["unique_constraints"][
            "integration_terminal_bindings"
        ]
        assert any(
            index.get("unique")
            and index.get("column_names") == ["register_id"]
            and "is_active" in str(index.get("dialect_options", {}))
            for index in upgraded["indexes"]["fiscal_routes"]
        ), "one active fiscal route per register must be a PostgreSQL partial unique index"
        await _assert_nkt_rejects_non_digits(database_url)

        await asyncio.to_thread(command.downgrade, config, "0021_refunds_fiscal_tax")
        downgraded = await _snapshot(database_url)
        assert downgraded["revision"] == "0021_refunds_fiscal_tax"
        assert not (STAGE22_TABLES & downgraded["tables"])
        assert downgraded["tables"] == before["tables"]
        assert downgraded["columns"] == before["columns"]

        await asyncio.to_thread(command.upgrade, config, "head")
        await asyncio.to_thread(command.check, config)
        assert (await _snapshot(database_url))["revision"] == (
            ScriptDirectory.from_config(config).get_current_head()
        )
    finally:
        async with admin_engine.connect() as connection:
            await connection.exec_driver_sql(
                f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)'
            )
        await admin_engine.dispose()
