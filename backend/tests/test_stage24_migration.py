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

STAGE24_TABLES = {
    "promotions",
    "promotion_locations",
    "promotion_schedules",
    "promotion_targets",
    "promotion_codes",
    "sales_order_discounts",
    "sales_order_discount_allocations",
    "refund_discount_allocations",
    "analytics_promotions_daily",
}
EXTENDED_COLUMNS = {
    "sales_orders": {"discount_total_minor", "pricing_revision", "priced_at"},
    "sales_order_items": {"discount_amount_minor", "net_line_total_minor"},
    "refund_lines": {
        "gross_refund_minor",
        "discount_refund_minor",
        "net_refund_minor",
    },
    "fiscal_sale_snapshots": {"discount_total_minor"},
    "fiscal_sale_snapshot_lines": {"gross_total_minor", "discount_minor"},
    "external_payment_attempts": {"order_pricing_revision"},
    "analytics_sales_daily": {"gross_revenue_amount", "discount_amount"},
    "analytics_product_sales_daily": {"gross_revenue_amount", "discount_amount"},
}


def _config(database_url: str) -> Config:
    config = Config(str(Path("alembic.ini")))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _surface(sync_connection) -> dict[str, object]:
    inspector = inspect(sync_connection)
    tables = set(inspector.get_table_names())
    tracked = STAGE24_TABLES | set(EXTENDED_COLUMNS)
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
        "unique_constraints": {
            table: {
                tuple(value["column_names"])
                for value in inspector.get_unique_constraints(table)
            }
            for table in tracked & tables
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
async def test_stage24_migration_up_down_reup_is_exact_and_reversible() -> None:
    source_url = os.getenv("POSTGRES_TEST_URL")
    if not source_url:
        pytest.skip("POSTGRES_TEST_URL is required for the PostgreSQL migration gate")

    source = make_url(source_url)
    database_name = f"beanly_stage24_migration_{uuid4().hex}"
    admin_url = source.set(database="postgres").render_as_string(hide_password=False)
    database_url = source.set(database=database_name).render_as_string(hide_password=False)
    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with admin_engine.connect() as connection:
            await connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')

        config = _config(database_url)
        await asyncio.to_thread(command.upgrade, config, "0023_onboarding_imports")
        before = await _snapshot(database_url)

        await asyncio.to_thread(command.upgrade, config, "0024_promotions_pricing")
        upgraded = await _snapshot(database_url)
        assert upgraded["revision"] == "0024_promotions_pricing"
        assert set(upgraded["tables"]) - set(before["tables"]) == STAGE24_TABLES
        for table, columns in EXTENDED_COLUMNS.items():
            assert columns <= upgraded["columns"][table]
        assert {
            "orders_count",
            "applications_count",
            "items_count",
            "gross_eligible_amount",
            "discount_amount",
            "net_revenue_amount",
            "refund_amount",
        } <= upgraded["columns"]["analytics_promotions_daily"]

        assert {
            "ck_promotions_status",
            "ck_promotions_application",
            "ck_promotions_kind",
            "ck_promotions_scope",
            "ck_promotions_stacking",
            "ck_promotions_percent",
        } <= upgraded["checks"]["promotions"]
        assert {
            "ck_sales_order_discount_nonnegative",
            "ck_sales_order_discount_bounded",
            "ck_sales_order_pricing_revision",
        } <= upgraded["checks"]["sales_orders"]
        assert {
            "ck_order_item_discount_bounded",
            "ck_order_item_net_reconciles",
        } <= upgraded["checks"]["sales_order_items"]
        assert ("organization_id", "code_normalized") in upgraded["unique_constraints"][
            "promotion_codes"
        ]
        assert ("order_id", "client_discount_id") in upgraded["unique_constraints"][
            "sales_order_discounts"
        ]

        await asyncio.to_thread(command.downgrade, config, "0023_onboarding_imports")
        downgraded = await _snapshot(database_url)
        assert downgraded["revision"] == "0023_onboarding_imports"
        assert downgraded["tables"] == before["tables"]
        for table, columns in EXTENDED_COLUMNS.items():
            assert not columns & downgraded["columns"][table]

        await asyncio.to_thread(command.upgrade, config, "head")
        await asyncio.to_thread(command.check, config)
        assert (await _snapshot(database_url))["revision"] == "0024_promotions_pricing"
    finally:
        async with admin_engine.connect() as connection:
            await connection.exec_driver_sql(
                f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)'
            )
        await admin_engine.dispose()
