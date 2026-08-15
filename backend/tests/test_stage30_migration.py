import asyncio
import os
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

STAGE30_TABLES = {
    "online_delivery_zones",
    "online_order_fulfillments",
    "online_fulfillment_reservations",
}


def _config(database_url: str) -> Config:
    config = Config(str(Path("alembic.ini")))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _surface(connection):
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    tracked = {
        "online_ordering_locations",
        "sales_orders",
        "online_orders",
        "refunds",
        "kitchen_tickets",
        *STAGE30_TABLES,
    }
    present = tracked & tables
    return {
        "revision": connection.scalar(text("SELECT version_num FROM alembic_version")),
        "tables": tables,
        "columns": {
            table: {
                column["name"]: (str(column["type"]), column["nullable"])
                for column in inspector.get_columns(table)
            }
            for table in present
        },
        "checks": {
            table: {value["name"] for value in inspector.get_check_constraints(table)}
            for table in present
        },
        "uniques": {
            table: {
                (value["name"], tuple(value["column_names"]))
                for value in inspector.get_unique_constraints(table)
            }
            for table in present
        },
        "indexes": {
            table: {value["name"] for value in inspector.get_indexes(table)}
            for table in present
        },
    }


async def _snapshot(database_url: str):
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            return await connection.run_sync(_surface)
    finally:
        await engine.dispose()


async def _seed_stage29_order(database_url: str) -> dict[str, str]:
    ids = {
        name: str(uuid4())
        for name in (
            "user",
            "organization",
            "location",
            "warehouse",
            "register",
            "shift",
            "sales",
            "online",
            "client",
        )
    }
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            statements = (
                (
                    "INSERT INTO users (id,email,password_hash,first_name,last_name,"
                    "is_active,email_verified,created_at,updated_at) VALUES "
                    "(:user,'stage30-migration@example.com','x','Stage','Owner',"
                    "true,true,now(),now())"
                ),
                (
                    "INSERT INTO organizations (id,name,country_code,currency_code,status,"
                    "created_by,created_at,updated_at) VALUES "
                    "(:organization,'Stage 30','KZ','KZT','active',:user,now(),now())"
                ),
                (
                    "INSERT INTO locations (id,organization_id,name,timezone,is_active,"
                    "is_primary,created_at,updated_at) VALUES "
                    "(:location,:organization,'Dostyk','Asia/Almaty',true,true,now(),now())"
                ),
                (
                    "INSERT INTO warehouses (id,organization_id,location_id,name,is_active,"
                    "created_at,updated_at) VALUES "
                    "(:warehouse,:organization,:location,'Main',true,now(),now())"
                ),
                (
                    "INSERT INTO pos_registers (id,organization_id,location_id,name,is_active,"
                    "created_by_user_id,created_at,updated_at) VALUES "
                    "(:register,:organization,:location,'Main',true,:user,now(),now())"
                ),
                (
                    "INSERT INTO register_shifts (id,organization_id,location_id,register_id,"
                    "warehouse_id,status,opened_by_user_id,opened_at,created_at,updated_at) "
                    "VALUES (:shift,:organization,:location,:register,:warehouse,'OPEN',"
                    ":user,now(),now(),now())"
                ),
                (
                    "INSERT INTO sales_orders (id,organization_id,location_id,shift_id,"
                    "warehouse_id,number,client_order_id,order_type,order_source,status,"
                    "currency_code,subtotal_minor,discount_total_minor,total_minor,"
                    "pricing_revision,created_at,updated_at) VALUES "
                    "(:sales,:organization,:location,:shift,:warehouse,1,:client,'TAKEAWAY',"
                    "'ONLINE','OPEN','KZT',90000,9000,81000,1,now(),now())"
                ),
                (
                    "INSERT INTO online_orders (id,organization_id,location_id,sales_order_id,"
                    "client_order_id,payload_hash,source,status,subtotal_minor,discount_minor,"
                    "total_minor,quote_revision,status_token_hash,created_at,updated_at) VALUES "
                    "(:online,:organization,:location,:sales,:client,repeat('a',64),'ONLINE',"
                    "'PENDING',90000,9000,81000,concat(extract(epoch from now())::bigint,':',"
                    "repeat('b',64)),repeat('c',64),now(),now())"
                ),
            )
            for statement in statements:
                await connection.execute(text(statement), ids)
    finally:
        await engine.dispose()
    return ids


async def _legacy_order(database_url: str, ids: dict[str, str]):
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            return (
                await connection.execute(
                    text(
                        "SELECT so.id,so.subtotal_minor,so.discount_total_minor,so.total_minor,"
                        "oo.id,oo.status,oo.subtotal_minor,oo.discount_minor,oo.total_minor "
                        "FROM sales_orders so JOIN online_orders oo ON oo.sales_order_id=so.id "
                        "WHERE so.id=:sales"
                    ),
                    ids,
                )
            ).one()
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_stage30_migration_is_single_head_direct_and_reversible() -> None:
    source_url = os.getenv("POSTGRES_TEST_URL")
    if not source_url:
        pytest.skip("POSTGRES_TEST_URL is required for Stage 30 migration gate")
    source = make_url(source_url)
    database_name = f"beanly_stage30_migration_{uuid4().hex}"
    admin_url = source.set(database="postgres").render_as_string(hide_password=False)
    database_url = source.set(database=database_name).render_as_string(hide_password=False)
    admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as connection:
            await connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
        config = _config(database_url)
        scripts = ScriptDirectory.from_config(config)
        assert scripts.get_heads() == [scripts.get_current_head()]
        assert scripts.get_revision("0030_online_fulfillment").down_revision == (
            "0029_online_ordering"
        )
        assert all(
            not revision.revision.startswith("0028")
            for revision in scripts.walk_revisions()
        )

        await asyncio.to_thread(command.upgrade, config, "0029_online_ordering")
        ids = await _seed_stage29_order(database_url)
        before = await _snapshot(database_url)
        legacy_before = await _legacy_order(database_url, ids)
        await asyncio.to_thread(command.upgrade, config, "0030_online_fulfillment")
        upgraded = await _snapshot(database_url)
        assert upgraded["revision"] == "0030_online_fulfillment"
        assert upgraded["tables"] - before["tables"] == STAGE30_TABLES

        assert {
            "delivery_enabled",
            "preparation_minutes",
            "slot_interval_minutes",
            "slot_capacity",
            "max_advance_minutes",
            "cancellation_cutoff_minutes",
            "delivery_minimum_order_minor",
            "default_fulfillment_type",
        } <= upgraded["columns"]["online_ordering_locations"].keys()
        assert "fulfillment_fee_minor" in upgraded["columns"]["sales_orders"]
        assert "fulfillment_fee_minor" in upgraded["columns"]["online_orders"]
        assert "fulfillment_fee_minor" in upgraded["columns"]["refunds"]
        assert {
            "fulfillment_type",
            "promised_at",
            "guest_instructions",
            "order_source",
        } <= upgraded["columns"]["kitchen_tickets"].keys()
        assert "ck_online_location_fulfillment" in upgraded["checks"][
            "online_ordering_locations"
        ]
        assert "ck_online_delivery_zone_money" in upgraded["checks"][
            "online_delivery_zones"
        ]
        assert "ck_online_fulfillment_delivery_shape" in upgraded["checks"][
            "online_order_fulfillments"
        ]
        assert "ck_online_reservation_status" in upgraded["checks"][
            "online_fulfillment_reservations"
        ]
        assert (
            "uq_online_order_fulfillment_order",
            ("online_order_id",),
        ) in upgraded["uniques"]["online_order_fulfillments"]
        assert (
            "uq_online_reservation_order",
            ("online_order_id",),
        ) in upgraded["uniques"]["online_fulfillment_reservations"]
        assert "ix_online_reservation_capacity" in upgraded["indexes"][
            "online_fulfillment_reservations"
        ]
        engine = create_async_engine(database_url)
        try:
            async with engine.connect() as connection:
                fulfillment = (
                    await connection.execute(
                        text(
                            "SELECT f.id,f.online_order_id,f.fulfillment_type,"
                            "f.fulfillment_timing,f.requested_at,f.promised_at,"
                            "f.delivery_zone_id,f.delivery_address,f.fulfillment_fee_minor,"
                            "oo.created_at FROM online_order_fulfillments f "
                            "JOIN online_orders oo ON oo.id=f.online_order_id "
                            "WHERE f.online_order_id=:online"
                        ),
                        ids,
                    )
                ).one()
                assert fulfillment.id == fulfillment.online_order_id == UUID(ids["online"])
                assert fulfillment.fulfillment_type == "PICKUP"
                assert fulfillment.fulfillment_timing == "ASAP"
                assert fulfillment.requested_at is None
                assert fulfillment.promised_at == fulfillment.created_at.replace(
                    second=0, microsecond=0
                )
                assert fulfillment.delivery_zone_id is None
                assert fulfillment.delivery_address is None
                assert fulfillment.fulfillment_fee_minor == 0
                assert (
                    await connection.scalar(
                        text(
                            "SELECT count(*) FROM online_order_fulfillments "
                            "WHERE online_order_id=:online"
                        ),
                        ids,
                    )
                    == 1
                )
        finally:
            await engine.dispose()

        await asyncio.to_thread(command.downgrade, config, "0029_online_ordering")
        assert await _snapshot(database_url) == before
        assert await _legacy_order(database_url, ids) == legacy_before
        await asyncio.to_thread(command.upgrade, config, "0030_online_fulfillment")
        assert await _snapshot(database_url) == upgraded
        await asyncio.to_thread(command.upgrade, config, "head")
        await asyncio.to_thread(command.check, config)
    finally:
        async with admin.connect() as connection:
            await connection.exec_driver_sql(
                f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)'
            )
        await admin.dispose()
