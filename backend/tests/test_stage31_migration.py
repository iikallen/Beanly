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


def _config(database_url: str) -> Config:
    config = Config(str(Path("alembic.ini")))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


async def _surface(database_url: str) -> dict[str, object]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            def inspect_surface(sync):
                inspector = inspect(sync)
                tables = set(inspector.get_table_names())
                tracked = {
                    "reservation_locations",
                    "reservation_schedules",
                    "dining_sections",
                    "dining_tables",
                    "reservations",
                    "waitlist_entries",
                    "dining_visits",
                } & tables
                return {
                    "revision": sync.scalar(
                        text("SELECT version_num FROM alembic_version")
                    ),
                    "tables": tables,
                    "checks": {
                        table: {
                            item["name"]
                            for item in inspector.get_check_constraints(table)
                        }
                        for table in tracked
                    },
                    "uniques": {
                        table: {
                            item["name"]
                            for item in inspector.get_unique_constraints(table)
                        }
                        for table in tracked
                    },
                    "indexes": {
                        table: {
                            item["name"] for item in inspector.get_indexes(table)
                        }
                        for table in tracked
                    },
                    "foreign_keys": {
                        table: {
                            item["name"] for item in inspector.get_foreign_keys(table)
                        }
                        for table in tracked
                    },
                }

            return await connection.run_sync(inspect_surface)
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_stage31_migration_is_direct_single_head_and_reversible() -> None:
    source_url = os.getenv("POSTGRES_TEST_URL")
    if not source_url:
        pytest.skip("POSTGRES_TEST_URL is required for the Stage 31 migration gate")
    source = make_url(source_url)
    database_name = f"beanly_stage31_migration_{uuid4().hex}"
    admin_url = source.set(database="postgres").render_as_string(hide_password=False)
    database_url = source.set(database=database_name).render_as_string(hide_password=False)
    admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as connection:
            await connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
        config = _config(database_url)
        scripts = ScriptDirectory.from_config(config)
        assert scripts.get_heads() == ["0031_reservations_waitlist"]
        assert scripts.get_revision("0031_reservations_waitlist").down_revision == (
            "0030_online_fulfillment"
        )
        assert all(
            not revision.revision.startswith("0028")
            for revision in scripts.walk_revisions()
        )

        await asyncio.to_thread(command.upgrade, config, "0030_online_fulfillment")
        before = await _surface(database_url)
        await asyncio.to_thread(command.upgrade, config, "head")
        upgraded = await _surface(database_url)
        assert upgraded["revision"] == "0031_reservations_waitlist"
        assert {
            "reservation_locations",
            "reservation_schedules",
            "dining_sections",
            "dining_tables",
            "reservations",
            "waitlist_entries",
            "dining_visits",
        } <= upgraded["tables"]
        assert "ck_dining_table_capacity_positive" in upgraded["checks"][
            "dining_tables"
        ]
        assert "ex_reservation_table_period_active" in {
            row
            for row in await _constraint_names(database_url, "reservations")
        }
        assert {
            "uq_dining_visit_reservation",
            "uq_dining_visit_waitlist",
            "uq_dining_visit_sales_order",
        } <= upgraded["uniques"]["dining_visits"]
        assert "uq_dining_visit_active_table" in upgraded["indexes"][
            "dining_visits"
        ]
        assert {
            "fk_dining_table_section_scope",
        } <= upgraded["foreign_keys"]["dining_tables"]
        assert "fk_reservation_table_scope" in upgraded["foreign_keys"][
            "reservations"
        ]
        assert "fk_dining_visit_table_scope" in upgraded["foreign_keys"][
            "dining_visits"
        ]
        await asyncio.to_thread(command.check, config)

        await asyncio.to_thread(command.downgrade, config, "0030_online_fulfillment")
        assert await _surface(database_url) == before
        await asyncio.to_thread(command.upgrade, config, "head")
        assert await _surface(database_url) == upgraded
        await asyncio.to_thread(command.check, config)
    finally:
        async with admin.connect() as connection:
            await connection.exec_driver_sql(
                f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)'
            )
        await admin.dispose()


async def _constraint_names(database_url: str, table_name: str) -> set[str]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            rows = await connection.scalars(
                text(
                    "SELECT conname FROM pg_constraint "
                    "WHERE conrelid = to_regclass(:table_name)"
                ),
                {"table_name": table_name},
            )
            return set(rows)
    finally:
        await engine.dispose()
