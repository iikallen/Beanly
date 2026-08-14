import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from beanly.modules.identity.infrastructure.db.models import UserModel
from beanly.modules.inventory.infrastructure.db.models import WarehouseModel
from beanly.modules.kitchen.domain.enums import KitchenTicketStatus, KitchenWorkStatus
from beanly.modules.kitchen.infrastructure.db.models import (
    KitchenActionModel,
    KitchenRoutingRuleModel,
    KitchenStationModel,
    KitchenTicketItemModel,
    KitchenTicketModel,
    KitchenWorkItemModel,
)
from beanly.modules.kitchen.infrastructure.service import KitchenService
from beanly.modules.menu.infrastructure.db.models import (
    MenuCategoryModel,
    ProductModel,
    ProductVariantModel,
)
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.organizations.domain.enums import LocationAccess, MembershipRole
from beanly.modules.organizations.domain.permissions import permissions_for
from beanly.modules.organizations.infrastructure.db.models import LocationModel, OrganizationModel
from beanly.modules.payments.infrastructure.db.models import PaymentModel
from beanly.modules.sales.infrastructure.db.models import (
    PosRegisterModel,
    RegisterShiftModel,
    SalesOrderItemModel,
    SalesOrderModel,
)


class _Organizations:
    async def ensure_location_access(self, context, location_id):
        del context, location_id


def _config(database_url: str) -> Config:
    config = Config(str(Path("alembic.ini")))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.mark.anyio
async def test_stage27_postgres_projection_concurrency_and_actions() -> None:
    source_url = os.getenv("POSTGRES_TEST_URL")
    if not source_url:
        pytest.skip("POSTGRES_TEST_URL is required for the PostgreSQL kitchen gate")
    source = make_url(source_url)
    database_name = f"beanly_stage27_kitchen_{uuid4().hex}"
    admin_url = source.set(database="postgres").render_as_string(hide_password=False)
    database_url = source.set(database=database_name).render_as_string(hide_password=False)
    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with admin_engine.connect() as connection:
            await connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
        await asyncio.to_thread(command.upgrade, _config(database_url), "head")
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        ids = {
            name: uuid4()
            for name in (
                "user",
                "organization",
                "location",
                "warehouse",
                "register",
                "shift",
                "category",
                "product",
                "variant",
                "order",
                "order_item",
                "payment",
            )
        }
        now = datetime.now(UTC)
        async with sessions() as session:
            session.add(
                UserModel(
                    id=ids["user"],
                    email="stage27-pg@example.com",
                    password_hash="x",
                    first_name="Kitchen",
                    last_name="Owner",
                    is_active=True,
                    email_verified=True,
                )
            )
            await session.flush()
            session.add(
                OrganizationModel(
                    id=ids["organization"],
                    name="Stage 27",
                    country_code="KZ",
                    currency_code="KZT",
                    status="active",
                    created_by=ids["user"],
                )
            )
            await session.flush()
            session.add(
                LocationModel(
                    id=ids["location"],
                    organization_id=ids["organization"],
                    name="Dostyk",
                    timezone="Asia/Almaty",
                    is_active=True,
                    is_primary=True,
                    fiscal_enforcement_mode="DISABLED",
                    cash_variance_approval_threshold_minor=0,
                )
            )
            await session.flush()
            session.add(
                WarehouseModel(
                    id=ids["warehouse"],
                    organization_id=ids["organization"],
                    location_id=ids["location"],
                    name="Main",
                    is_active=True,
                )
            )
            session.add(
                PosRegisterModel(
                    id=ids["register"],
                    organization_id=ids["organization"],
                    location_id=ids["location"],
                    name="POS",
                    is_active=True,
                    created_by_user_id=ids["user"],
                )
            )
            await session.flush()
            session.add(
                RegisterShiftModel(
                    id=ids["shift"],
                    organization_id=ids["organization"],
                    location_id=ids["location"],
                    register_id=ids["register"],
                    warehouse_id=ids["warehouse"],
                    status="OPEN",
                    opened_by_user_id=ids["user"],
                    opened_at=now,
                )
            )
            session.add(
                MenuCategoryModel(
                    id=ids["category"],
                    organization_id=ids["organization"],
                    name="Drinks",
                    sort_order=0,
                    is_active=True,
                )
            )
            await session.flush()
            product = ProductModel(
                id=ids["product"],
                organization_id=ids["organization"],
                category_id=ids["category"],
                name="Latte",
                status="ACTIVE",
            )
            session.add(product)
            await session.flush()
            session.add(
                ProductVariantModel(
                    id=ids["variant"],
                    organization_id=ids["organization"],
                    product_id=ids["product"],
                    name="Regular",
                    base_price_minor=1000,
                    is_default=True,
                    status="ACTIVE",
                    sort_order=0,
                )
            )
            await session.flush()
            stations = []
            for code, role, default in (
                ("PREPARATION", "PREP_EXPO", True),
                ("BAR", "PREP", False),
                ("KITCHEN", "PREP", False),
                ("EXPO", "EXPO", False),
            ):
                station = KitchenStationModel(
                    id=uuid4(),
                    organization_id=ids["organization"],
                    location_id=ids["location"],
                    name=code.title(),
                    code=code,
                    role=role,
                    is_default=default,
                    is_active=True,
                    warning_after_seconds=300,
                    late_after_seconds=600,
                    sort_order=len(stations),
                )
                stations.append(station)
                session.add(station)
            await session.flush()
            for station in stations[1:]:
                session.add(
                    KitchenRoutingRuleModel(
                        id=uuid4(),
                        organization_id=ids["organization"],
                        location_id=ids["location"],
                        station_id=station.id,
                        scope="VARIANT",
                        category_id=None,
                        variant_id=ids["variant"],
                        order_type=None,
                        priority=10,
                        is_active=True,
                    )
                )
            await session.flush()
            order = SalesOrderModel(
                id=ids["order"],
                organization_id=ids["organization"],
                location_id=ids["location"],
                shift_id=ids["shift"],
                warehouse_id=ids["warehouse"],
                number=7,
                client_order_id=uuid4(),
                version=1,
                order_type="DINE_IN",
                status="PAID",
                currency_code="KZT",
                guest_count=1,
                table_label="A1",
                note="Serve together",
                subtotal_minor=1000,
                total_minor=1000,
                discount_total_minor=0,
                pricing_revision=1,
                created_by_user_id=ids["user"],
                paid_by_user_id=ids["user"],
                paid_at=now,
            )
            order.items = [
                SalesOrderItemModel(
                    id=ids["order_item"],
                    client_item_id=uuid4(),
                    product_id=ids["product"],
                    product_variant_id=ids["variant"],
                    product_name="Latte",
                    variant_name="Regular",
                    quantity=1,
                    base_price_minor=1000,
                    modifier_price_minor=0,
                    unit_price_minor=1000,
                    line_total_minor=1000,
                    discount_amount_minor=0,
                    net_line_total_minor=1000,
                    note="Warm",
                )
            ]
            session.add(order)
            await session.flush()
            session.add(
                PaymentModel(
                    id=ids["payment"],
                    organization_id=ids["organization"],
                    location_id=ids["location"],
                    order_id=ids["order"],
                    shift_id=ids["shift"],
                    client_payment_id=uuid4(),
                    currency_code="KZT",
                    amount_minor=1000,
                    created_by_user_id=ids["user"],
                    completed_at=now,
                )
            )
            await session.commit()

        async def project():
            async with sessions() as session:
                service = KitchenService(session, _Organizations())
                value = await service.project_payment(
                    ids["organization"], ids["payment"], ids["order"]
                )
                await session.commit()
                return value.id

        assert len(set(await asyncio.gather(project(), project()))) == 1
        async with sessions() as session:
            assert await session.scalar(select(func.count(KitchenTicketModel.id))) == 1
            assert await session.scalar(select(func.count(KitchenTicketItemModel.id))) == 1
            work_ids = tuple(
                await session.scalars(
                    select(KitchenWorkItemModel.id).order_by(KitchenWorkItemModel.id)
                )
            )
            assert len(work_ids) == 2
            ticket_id = await session.scalar(select(KitchenTicketModel.id))
        context = TenantContext(
            user_id=ids["user"],
            organization_id=ids["organization"],
            membership_id=uuid4(),
            role=MembershipRole.OWNER,
            permissions=permissions_for(MembershipRole.OWNER),
            location_access=LocationAccess.ALL,
        )
        shared_action = uuid4()

        async def start(work_id, action_id):
            async with sessions() as session:
                return (
                    await KitchenService(session, _Organizations()).start_work(
                        context, work_id, action_id
                    )
                ).status

        assert await asyncio.gather(
            start(work_ids[0], shared_action), start(work_ids[0], shared_action)
        ) == [KitchenWorkStatus.PREPARING, KitchenWorkStatus.PREPARING]
        await start(work_ids[1], uuid4())

        async def ready(work_id):
            async with sessions() as session:
                return (
                    await KitchenService(session, _Organizations()).ready_work(
                        context, work_id, uuid4()
                    )
                ).status

        assert await asyncio.gather(ready(work_ids[0]), ready(work_ids[1])) == [
            KitchenWorkStatus.READY,
            KitchenWorkStatus.READY,
        ]
        async with sessions() as session:
            service = KitchenService(session, _Organizations())
            ticket = await service.get_ticket(context, ticket_id)
            assert ticket.status == KitchenTicketStatus.READY
            await service.complete_ticket(context, ticket_id, uuid4())
            await service.recall_ticket(context, ticket_id, uuid4())
            await service.complete_ticket(context, ticket_id, uuid4())
        async with sessions() as session:
            assert await session.scalar(select(func.count(KitchenActionModel.id))) == 7
            assert (await session.get(KitchenTicketModel, ticket_id)).status == "COMPLETED"
        await engine.dispose()
    finally:
        async with admin_engine.connect() as connection:
            await connection.exec_driver_sql(
                f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)'
            )
        await admin_engine.dispose()
