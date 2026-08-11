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


def _config(database_url: str) -> Config:
    config = Config(str(Path("alembic.ini")))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _audit_schema(sync_connection) -> dict[str, object]:
    inspector = inspect(sync_connection)
    table = "security_audit_events"
    return {
        "revision": sync_connection.scalar(text("SELECT version_num FROM alembic_version")),
        "tables": set(inspector.get_table_names()),
        "columns": {column["name"]: column for column in inspector.get_columns(table)},
        "foreign_keys": {
            (
                tuple(value["constrained_columns"]),
                value["referred_table"],
                value["options"].get("ondelete"),
            )
            for value in inspector.get_foreign_keys(table)
        },
        "indexes": {
            value["name"]: tuple(value["column_names"])
            for value in inspector.get_indexes(table)
        },
    }


@pytest.mark.anyio
async def test_0019_audit_migration_upgrade_downgrade_and_reupgrade() -> None:
    source_url = os.getenv("POSTGRES_TEST_URL")
    if not source_url:
        pytest.skip("POSTGRES_TEST_URL is required for the PostgreSQL integration gate")

    database_name = f"beanly_stage19_migration_{uuid4().hex}"
    source = make_url(source_url)
    admin_url = source.set(database="postgres").render_as_string(hide_password=False)
    test_url = source.set(database=database_name).render_as_string(hide_password=False)
    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    engine = create_async_engine(test_url)
    try:
        async with admin_engine.connect() as connection:
            await connection.execute(text(f'CREATE DATABASE "{database_name}"'))

        config = _config(test_url)
        await asyncio.to_thread(command.upgrade, config, "0019_production_hardening")
        async with engine.connect() as connection:
            schema = await connection.run_sync(_audit_schema)

        assert schema["revision"] == "0019_production_hardening"
        assert "security_audit_events" in schema["tables"]
        columns = schema["columns"]
        assert set(columns) == {
            "id",
            "organization_id",
            "actor_user_id",
            "action",
            "resource_type",
            "resource_id",
            "request_id",
            "ip_hash",
            "metadata",
            "created_at",
        }
        assert str(columns["metadata"]["type"]) == "JSONB"
        assert str(columns["ip_hash"]["type"]) == "VARCHAR(64)"
        assert columns["created_at"]["type"].timezone
        assert columns["organization_id"]["nullable"]
        assert columns["actor_user_id"]["nullable"]
        assert (("organization_id",), "organizations", "SET NULL") in schema["foreign_keys"]
        assert (("actor_user_id",), "users", "SET NULL") in schema["foreign_keys"]
        assert schema["indexes"] == {
            "ix_security_audit_action_created": ("action", "created_at"),
            "ix_security_audit_org_created": ("organization_id", "created_at"),
        }

        await asyncio.to_thread(command.downgrade, config, "0018_integrations")
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "0018_integrations"
            )
            assert "security_audit_events" not in await connection.run_sync(
                lambda value: inspect(value).get_table_names()
            )

        await asyncio.to_thread(command.upgrade, config, "0019_production_hardening")
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "0019_production_hardening"
            )
    finally:
        await engine.dispose()
        await admin_engine.dispose()
        cleanup_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
        try:
            async with cleanup_engine.connect() as connection:
                await connection.execute(
                    text(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')
                )
        finally:
            await cleanup_engine.dispose()
