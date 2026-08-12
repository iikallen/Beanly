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

STAGE23_TABLES = {
    "onboarding_states",
    "onboarding_import_runs",
    "onboarding_import_entities",
}


def _config(database_url: str) -> Config:
    config = Config(str(Path("alembic.ini")))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _surface(sync_connection) -> dict[str, object]:
    inspector = inspect(sync_connection)
    tables = set(inspector.get_table_names())
    tracked = STAGE23_TABLES & tables
    return {
        "revision": sync_connection.scalar(text("SELECT version_num FROM alembic_version")),
        "tables": tables,
        "columns": {
            table: {
                column["name"]: (str(column["type"]), column["nullable"])
                for column in inspector.get_columns(table)
            }
            for table in tracked
        },
        "checks": {
            table: {value["name"] for value in inspector.get_check_constraints(table)}
            for table in tracked
        },
        "foreign_keys": {
            table: {
                (
                    tuple(value["constrained_columns"]),
                    value["referred_table"],
                    value.get("options", {}).get("ondelete"),
                )
                for value in inspector.get_foreign_keys(table)
            }
            for table in tracked
        },
        "indexes": {
            table: {
                (value["name"], tuple(value["column_names"]), value["unique"])
                for value in inspector.get_indexes(table)
            }
            for table in tracked
        },
        "unique_constraints": {
            table: {
                tuple(value["column_names"])
                for value in inspector.get_unique_constraints(table)
            }
            for table in tracked
        },
    }


async def _snapshot(database_url: str) -> dict[str, object]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            return await connection.run_sync(_surface)
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_stage23_migration_up_down_reup_preserves_stage22_surface() -> None:
    source_url = os.getenv("POSTGRES_TEST_URL")
    if not source_url:
        pytest.skip("POSTGRES_TEST_URL is required for the PostgreSQL migration gate")

    source = make_url(source_url)
    database_name = f"beanly_stage23_migration_{uuid4().hex}"
    admin_url = source.set(database="postgres").render_as_string(hide_password=False)
    database_url = source.set(database=database_name).render_as_string(hide_password=False)
    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with admin_engine.connect() as connection:
            await connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')

        config = _config(database_url)
        await asyncio.to_thread(command.upgrade, config, "0022_kz_live_integrations")
        before = await _snapshot(database_url)

        await asyncio.to_thread(command.upgrade, config, "0023_onboarding_imports")
        upgraded = await _snapshot(database_url)
        assert upgraded["revision"] == "0023_onboarding_imports"
        assert STAGE23_TABLES <= upgraded["tables"]
        assert set(upgraded["tables"]) - set(before["tables"]) == STAGE23_TABLES

        assert set(upgraded["columns"]["onboarding_states"]) == {
            "id",
            "organization_id",
            "status",
            "current_step",
            "started_at",
            "completed_at",
            "dismissed_at",
            "created_by",
            "updated_at",
        }
        assert set(upgraded["columns"]["onboarding_import_runs"]) == {
            "id",
            "organization_id",
            "location_id",
            "client_import_id",
            "source_type",
            "source_name",
            "source_version",
            "file_name",
            "file_hash",
            "status",
            "entity_count",
            "error_count",
            "warning_count",
            "payload_hash",
            "mapping",
            "created_by",
            "created_at",
            "applied_at",
            "failed_at",
        }
        assert set(upgraded["columns"]["onboarding_import_entities"]) == {
            "id",
            "import_run_id",
            "entity_type",
            "source_key",
            "payload",
            "resolution",
            "target_id",
            "error_codes",
            "warning_codes",
            "sort_order",
        }
        assert upgraded["columns"]["onboarding_import_runs"]["source_version"] == (
            "INTEGER",
            True,
        )

        assert ("organization_id",) in upgraded["unique_constraints"][
            "onboarding_states"
        ]
        assert ("organization_id", "client_import_id") in upgraded[
            "unique_constraints"
        ]["onboarding_import_runs"]
        assert ("import_run_id", "source_key") in upgraded["unique_constraints"][
            "onboarding_import_entities"
        ]
        assert {
            "ck_onboarding_import_source",
            "ck_onboarding_import_status",
            "ck_onboarding_import_entity_count",
            "ck_onboarding_import_error_count",
            "ck_onboarding_import_warning_count",
        } <= upgraded["checks"]["onboarding_import_runs"]
        assert {
            "ck_onboarding_entity_type",
            "ck_onboarding_entity_resolution",
            "ck_onboarding_entity_sort_order",
        } <= upgraded["checks"]["onboarding_import_entities"]
        assert (
            ("organization_id",),
            "organizations",
            "CASCADE",
        ) in upgraded["foreign_keys"]["onboarding_import_runs"]
        assert (
            ("location_id",),
            "locations",
            "RESTRICT",
        ) in upgraded["foreign_keys"]["onboarding_import_runs"]
        assert (
            ("import_run_id",),
            "onboarding_import_runs",
            "CASCADE",
        ) in upgraded["foreign_keys"]["onboarding_import_entities"]
        assert {
            (
                "ix_onboarding_import_org_created",
                ("organization_id", "created_at"),
                False,
            ),
            (
                "ix_onboarding_import_org_status",
                ("organization_id", "status"),
                False,
            ),
        } <= upgraded["indexes"]["onboarding_import_runs"]
        assert (
            "ix_onboarding_entity_run_order",
            ("import_run_id", "sort_order"),
            False,
        ) in upgraded["indexes"]["onboarding_import_entities"]

        await asyncio.to_thread(command.downgrade, config, "0022_kz_live_integrations")
        downgraded = await _snapshot(database_url)
        assert downgraded["revision"] == "0022_kz_live_integrations"
        assert not (STAGE23_TABLES & downgraded["tables"])
        assert downgraded["tables"] == before["tables"]

        await asyncio.to_thread(command.upgrade, config, "head")
        await asyncio.to_thread(command.check, config)
        assert (await _snapshot(database_url))["revision"] == "0023_onboarding_imports"
    finally:
        async with admin_engine.connect() as connection:
            await connection.exec_driver_sql(
                f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)'
            )
        await admin_engine.dispose()
