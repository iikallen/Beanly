from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_offline_pos import _workspace

from beanly.core.database.base import Base
from beanly.core.events.outbox.models import OutboxEventModel
from beanly.modules.kitchen.api.schemas import TicketResponse
from beanly.modules.kitchen.domain.enums import KitchenTicketStatus, KitchenWorkStatus
from beanly.modules.kitchen.domain.exceptions import KitchenActionIdempotencyConflict
from beanly.modules.kitchen.infrastructure.db.models import (
    KitchenActionModel,
    KitchenRoutingRuleModel,
    KitchenStationModel,
    KitchenTicketItemModel,
    KitchenTicketModel,
    KitchenWorkItemModel,
)
from beanly.modules.kitchen.infrastructure.service import KitchenService
from beanly.modules.menu.infrastructure.db.models import ProductModel, ProductVariantModel
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.organizations.domain.enums import LocationAccess, MembershipRole
from beanly.modules.organizations.domain.permissions import Permission, permissions_for
from beanly.modules.organizations.infrastructure.db.models import OrganizationMembershipModel
from beanly.modules.payments.infrastructure.db.models import PaymentModel
from beanly.modules.sales.infrastructure.db.models import (
    SalesOrderItemModel,
    SalesOrderItemModifierModel,
    SalesOrderModel,
)


class _Organizations:
    async def ensure_location_access(self, context, location_id):
        del context, location_id


def _context(organization_id, user_id, membership_id):
    return TenantContext(
        user_id=user_id,
        organization_id=organization_id,
        membership_id=membership_id,
        role=MembershipRole.OWNER,
        permissions=permissions_for(MembershipRole.OWNER),
        location_access=LocationAccess.ALL,
    )


@pytest.mark.anyio
async def test_payment_projection_routing_snapshots_actions_and_recall(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'kitchen.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    organization_id = uuid4()
    location_id = uuid4()
    user_id = uuid4()
    membership_id = uuid4()
    shift_id = uuid4()
    warehouse_id = uuid4()
    order_id = uuid4()
    payment_id = uuid4()
    category_drink = uuid4()
    category_food = uuid4()
    product_drink = uuid4()
    product_food = uuid4()
    variant_drink = uuid4()
    variant_food = uuid4()
    ordered_at = datetime.now(UTC) - timedelta(hours=2)
    async with sessions() as session:
        bar = KitchenStationModel(
            id=uuid4(),
            organization_id=organization_id,
            location_id=location_id,
            name="Bar",
            code="BAR",
            role="PREP",
            is_default=False,
            is_active=True,
            warning_after_seconds=300,
            late_after_seconds=600,
            sort_order=1,
        )
        kitchen = KitchenStationModel(
            id=uuid4(),
            organization_id=organization_id,
            location_id=location_id,
            name="Kitchen",
            code="KITCHEN",
            role="PREP",
            is_default=False,
            is_active=True,
            warning_after_seconds=300,
            late_after_seconds=600,
            sort_order=2,
        )
        expo = KitchenStationModel(
            id=uuid4(),
            organization_id=organization_id,
            location_id=location_id,
            name="Expo",
            code="EXPO",
            role="EXPO",
            is_default=False,
            is_active=True,
            warning_after_seconds=300,
            late_after_seconds=600,
            sort_order=3,
        )
        drink_product = ProductModel(
            id=product_drink,
            organization_id=organization_id,
            category_id=category_drink,
            name="Flat White",
            status="ACTIVE",
        )
        food_product = ProductModel(
            id=product_food,
            organization_id=organization_id,
            category_id=category_food,
            name="Croissant",
            status="ACTIVE",
        )
        session.add_all(
            [
                bar,
                kitchen,
                expo,
                drink_product,
                food_product,
                ProductVariantModel(
                    id=variant_drink,
                    organization_id=organization_id,
                    product_id=product_drink,
                    name="Large",
                    base_price_minor=2500,
                    is_default=True,
                    status="ACTIVE",
                    sort_order=0,
                ),
                ProductVariantModel(
                    id=variant_food,
                    organization_id=organization_id,
                    product_id=product_food,
                    name="Regular",
                    base_price_minor=1500,
                    is_default=True,
                    status="ACTIVE",
                    sort_order=0,
                ),
                KitchenRoutingRuleModel(
                    id=uuid4(),
                    organization_id=organization_id,
                    location_id=location_id,
                    station_id=bar.id,
                    scope="VARIANT",
                    variant_id=variant_drink,
                    category_id=None,
                    order_type="TAKEAWAY",
                    priority=10,
                    is_active=True,
                ),
                KitchenRoutingRuleModel(
                    id=uuid4(),
                    organization_id=organization_id,
                    location_id=location_id,
                    station_id=kitchen.id,
                    scope="CATEGORY",
                    category_id=category_food,
                    variant_id=None,
                    order_type=None,
                    priority=5,
                    is_active=True,
                ),
                KitchenRoutingRuleModel(
                    id=uuid4(),
                    organization_id=organization_id,
                    location_id=location_id,
                    station_id=expo.id,
                    scope="CATEGORY",
                    category_id=category_food,
                    variant_id=None,
                    order_type=None,
                    priority=5,
                    is_active=True,
                ),
            ]
        )
        order = SalesOrderModel(
            id=order_id,
            organization_id=organization_id,
            location_id=location_id,
            shift_id=shift_id,
            warehouse_id=warehouse_id,
            customer_id=uuid4(),
            customer_name_snapshot="Aruzhan Guest",
            customer_phone_snapshot="+77001234567",
            number=42,
            client_order_id=uuid4(),
            version=1,
            order_type="TAKEAWAY",
            status="PAID",
            currency_code="KZT",
            guest_count=2,
            table_label=None,
            note="No cutlery",
            subtotal_minor=6500,
            total_minor=6500,
            discount_total_minor=0,
            pricing_revision=1,
            created_by_user_id=user_id,
            paid_by_user_id=user_id,
            paid_at=ordered_at,
        )
        drink_item = SalesOrderItemModel(
            id=uuid4(),
            client_item_id=uuid4(),
            product_id=product_drink,
            product_variant_id=variant_drink,
            product_name="Flat White",
            variant_name="Large",
            quantity=2,
            base_price_minor=2500,
            modifier_price_minor=500,
            unit_price_minor=3000,
            line_total_minor=6000,
            discount_amount_minor=0,
            net_line_total_minor=6000,
            note="Extra hot",
        )
        drink_item.modifiers.append(
            SalesOrderItemModifierModel(
                id=uuid4(),
                modifier_group_id=uuid4(),
                modifier_group_name="Milk",
                modifier_option_id=uuid4(),
                modifier_option_name="Oat",
                price_delta_minor=500,
                sort_order=0,
            )
        )
        food_item = SalesOrderItemModel(
            id=uuid4(),
            client_item_id=uuid4(),
            product_id=product_food,
            product_variant_id=variant_food,
            product_name="Croissant",
            variant_name="Regular",
            quantity=1,
            base_price_minor=500,
            modifier_price_minor=0,
            unit_price_minor=500,
            line_total_minor=500,
            discount_amount_minor=0,
            net_line_total_minor=500,
            note=None,
        )
        order.items = [drink_item, food_item]
        session.add(order)
        session.add(
            PaymentModel(
                id=payment_id,
                organization_id=organization_id,
                location_id=location_id,
                order_id=order_id,
                shift_id=shift_id,
                client_payment_id=uuid4(),
                currency_code="KZT",
                amount_minor=6500,
                created_by_user_id=user_id,
                completed_at=ordered_at,
            )
        )
        await session.commit()

        service = KitchenService(session, _Organizations())
        ticket = await service.project_payment(organization_id, payment_id, order_id)
        await session.commit()
        ticket_id = ticket.id
        replay = await service.project_payment(organization_id, payment_id, order_id)
        assert replay.id == ticket.id
        assert await session.scalar(select(func.count(KitchenTicketModel.id))) == 1
        assert await session.scalar(select(func.count(KitchenTicketItemModel.id))) == 2
        work = tuple(
            await session.scalars(
                select(KitchenWorkItemModel).order_by(KitchenWorkItemModel.station_id)
            )
        )
        work_ids = tuple(item.id for item in work)
        assert {item.station_id for item in work} == {bar.id, kitchen.id}
        snapshot = TicketResponse.from_model(await service._ticket(organization_id, ticket_id))
        assert snapshot.offline_delayed is True
        assert snapshot.customer_name == "Aruzhan Guest"
        assert snapshot.note == "No cutlery"
        assert snapshot.items[0].modifiers[0].modifier_option_name == "Oat"

        session.expunge_all()
        _, board_tickets, _ = await service.board(
            _context(organization_id, user_id, membership_id), expo.id, None
        )
        board_snapshot = TicketResponse.from_model(
            board_tickets[0], station_id=expo.id, whole_order=True
        )
        assert len(board_snapshot.items) == 2
        assert sum(len(item.work_items) for item in board_snapshot.items) == 2

        context = _context(organization_id, user_id, membership_id)
        first_start = uuid4()
        await service.start_work(context, work_ids[0], first_start)
        replay_work = await service.start_work(context, work_ids[0], first_start)
        assert replay_work.status == KitchenWorkStatus.PREPARING
        with pytest.raises(KitchenActionIdempotencyConflict):
            await service.start_work(context, work_ids[1], first_start)
        await session.rollback()
        await service.start_work(context, work_ids[1], uuid4())
        await service.ready_work(context, work_ids[0], uuid4())
        ticket = await service.get_ticket(context, ticket_id)
        assert ticket.status == KitchenTicketStatus.PREPARING
        await service.ready_work(context, work_ids[1], uuid4())
        ticket = await service.get_ticket(context, ticket_id)
        assert ticket.status == KitchenTicketStatus.READY
        await service.complete_ticket(context, ticket_id, uuid4())
        assert (
            await service.get_ticket(context, ticket_id)
        ).status == KitchenTicketStatus.COMPLETED
        await service.recall_ticket(context, ticket_id, uuid4())
        assert (await service.get_ticket(context, ticket_id)).status == KitchenTicketStatus.READY
        await service.complete_ticket(context, ticket_id, uuid4())
        assert (
            await service.get_ticket(context, ticket_id)
        ).status == KitchenTicketStatus.COMPLETED
        assert await session.scalar(select(func.count(KitchenActionModel.id))) == 7
        event_names = set(await session.scalars(select(OutboxEventModel.event_name)))
        assert {
            "kitchen.ticket_created",
            "kitchen.work_started",
            "kitchen.work_ready",
            "kitchen.ticket_ready",
            "kitchen.ticket_completed",
            "kitchen.ticket_recalled",
        } <= event_names
    await engine.dispose()


def test_stage27_openapi_permissions_and_architecture() -> None:
    from beanly.main import app

    paths = app.openapi()["paths"]
    expected = {
        "/api/v1/kitchen/stations",
        "/api/v1/kitchen/stations/{station_id}",
        "/api/v1/kitchen/routing",
        "/api/v1/kitchen/routing/{rule_id}",
        "/api/v1/kitchen/stations/{station_id}/board",
        "/api/v1/kitchen/tickets/{ticket_id}",
        "/api/v1/kitchen/work-items/{work_item_id}/start",
        "/api/v1/kitchen/work-items/{work_item_id}/ready",
        "/api/v1/kitchen/tickets/{ticket_id}/complete",
        "/api/v1/kitchen/tickets/{ticket_id}/recall",
        "/api/v1/kitchen/readiness",
        "/api/v1/kitchen/reports/performance",
    }
    assert expected <= set(paths)
    assert {Permission.KITCHEN_READ, Permission.KITCHEN_WORK} <= permissions_for(
        MembershipRole.BARISTA
    )
    assert Permission.KITCHEN_READ in permissions_for(MembershipRole.CASHIER)
    assert {
        Permission.KITCHEN_READ,
        Permission.KITCHEN_WORK,
        Permission.KITCHEN_EXPO,
        Permission.KITCHEN_MANAGE,
        Permission.KITCHEN_REPORT,
    } <= permissions_for(MembershipRole.MANAGER)
    assert permissions_for(MembershipRole.ACCOUNTANT).intersection(
        {
            Permission.KITCHEN_READ,
            Permission.KITCHEN_WORK,
            Permission.KITCHEN_EXPO,
            Permission.KITCHEN_MANAGE,
            Permission.KITCHEN_REPORT,
        }
    ) == {Permission.KITCHEN_REPORT}


@pytest.mark.anyio
async def test_kitchen_api_tenant_location_and_role_boundaries(app_client) -> None:
    client, sessions = app_client
    headers, organization_id, location_id, _ = await _workspace(
        client, "stage27-owner@example.com", "Stage 27 owner"
    )
    _, _, foreign_location_id, _ = await _workspace(
        client, "stage27-foreign@example.com", "Stage 27 foreign"
    )
    listed = await client.get(
        "/api/v1/kitchen/stations",
        headers=headers,
        params={"location_id": str(location_id)},
    )
    assert listed.status_code == 200, listed.text
    assert [(row["code"], row["role"], row["is_default"]) for row in listed.json()] == [
        ("PREPARATION", "PREP_EXPO", True)
    ]
    hidden = await client.get(
        "/api/v1/kitchen/stations",
        headers=headers,
        params={"location_id": str(foreign_location_id)},
    )
    assert hidden.status_code == 404
    async with sessions() as session:
        membership = await session.scalar(
            select(OrganizationMembershipModel).where(
                OrganizationMembershipModel.organization_id == organization_id
            )
        )
        membership.role = "CASHIER"
        await session.commit()
    assert (
        await client.get(
            "/api/v1/kitchen/stations",
            headers=headers,
            params={"location_id": str(location_id)},
        )
    ).status_code == 200
    assert (
        await client.post(
            "/api/v1/kitchen/stations",
            headers=headers,
            json={
                "location_id": str(location_id),
                "name": "Bar",
                "code": "BAR",
                "role": "PREP",
            },
        )
    ).status_code == 403
    assert (
        await client.get("/api/v1/kitchen/reports/performance", headers=headers)
    ).status_code == 403
    async with sessions() as session:
        membership = await session.scalar(
            select(OrganizationMembershipModel).where(
                OrganizationMembershipModel.organization_id == organization_id
            )
        )
        membership.role = "ACCOUNTANT"
        await session.commit()
    assert (
        await client.get("/api/v1/kitchen/reports/performance", headers=headers)
    ).status_code == 200
    assert (
        await client.get(
            "/api/v1/kitchen/readiness",
            headers=headers,
            params={"location_id": str(location_id)},
        )
    ).status_code == 403
