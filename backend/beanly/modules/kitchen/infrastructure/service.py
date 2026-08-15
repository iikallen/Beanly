import hashlib
import json
from datetime import UTC, date, datetime, time, timedelta
from statistics import median
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from beanly.core.events.outbox.repositories import OutboxRepository
from beanly.core.events.outbox.writer import OutboxEventSink
from beanly.core.observability.metrics import metrics
from beanly.modules.kitchen.domain.enums import (
    KitchenRoutingScope,
    KitchenStationRole,
    KitchenTicketStatus,
    KitchenWorkStatus,
)
from beanly.modules.kitchen.domain.events import (
    KitchenTicketCompleted,
    KitchenTicketCreated,
    KitchenTicketReady,
    KitchenTicketRecalled,
    KitchenWorkReady,
    KitchenWorkStarted,
)
from beanly.modules.kitchen.domain.exceptions import (
    KitchenActionIdempotencyConflict,
    KitchenInvalid,
    KitchenNotFound,
    KitchenWorkNotReady,
)
from beanly.modules.kitchen.infrastructure.db.models import (
    KitchenActionModel,
    KitchenRoutingRuleModel,
    KitchenStationModel,
    KitchenTicketItemModel,
    KitchenTicketItemModifierModel,
    KitchenTicketModel,
    KitchenWorkItemModel,
)
from beanly.modules.menu.infrastructure.db.models import (
    MenuCategoryModel,
    ProductModel,
    ProductVariantModel,
)
from beanly.modules.online_ordering.infrastructure.db.models import (
    OnlineOrderFulfillmentModel,
    OnlineOrderModel,
)
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.organizations.infrastructure.db.models import OrganizationModel
from beanly.modules.payments.infrastructure.db.models import PaymentModel
from beanly.modules.sales.infrastructure.db.models import SalesOrderItemModel, SalesOrderModel


class KitchenService:
    def __init__(self, session: AsyncSession, organizations: OrganizationService) -> None:
        self.session = session
        self.organizations = organizations
        self.events = OutboxEventSink(OutboxRepository(session))

    async def cancel_order(self, organization_id: UUID, order_id: UUID) -> None:
        ticket = await self.session.scalar(
            select(KitchenTicketModel)
            .options(selectinload(KitchenTicketModel.work_items))
            .where(
                KitchenTicketModel.organization_id == organization_id,
                KitchenTicketModel.order_id == order_id,
            )
            .with_for_update()
        )
        if ticket is None or ticket.status in {
            KitchenTicketStatus.CANCELLED.value,
            KitchenTicketStatus.COMPLETED.value,
        }:
            return
        ticket.status = KitchenTicketStatus.CANCELLED.value
        ticket.updated_at = datetime.now(UTC)
        ticket.version = await self._next_version(ticket.location_id, ticket.version)
        for work in ticket.work_items:
            work.status = "CANCELLED"
            work.updated_at = ticket.updated_at
        await self.session.flush()

    async def stage_order_ready(
        self, organization_id: UUID, order_id: UUID, occurred_at: datetime
    ) -> KitchenTicketModel:
        ticket = await self.session.scalar(
            select(KitchenTicketModel)
            .options(selectinload(KitchenTicketModel.work_items))
            .where(
                KitchenTicketModel.organization_id == organization_id,
                KitchenTicketModel.order_id == order_id,
            )
            .with_for_update()
        )
        if ticket is None:
            raise KitchenNotFound("Kitchen ticket has not been created")
        if ticket.status == KitchenTicketStatus.READY.value:
            return ticket
        if ticket.status not in {
            KitchenTicketStatus.QUEUED.value,
            KitchenTicketStatus.PREPARING.value,
        }:
            raise KitchenInvalid("Kitchen ticket cannot be marked ready")
        events = []
        for work in ticket.work_items:
            if work.status != KitchenWorkStatus.READY.value:
                work.status = KitchenWorkStatus.READY.value
                work.ready_at = work.updated_at = occurred_at
                events.append(
                    KitchenWorkReady(organization_id, ticket.id, work.id, work.station_id)
                )
        ticket.status = KitchenTicketStatus.READY.value
        ticket.ready_at = ticket.updated_at = occurred_at
        ticket.version = await self._next_version(ticket.location_id, ticket.version)
        events.append(KitchenTicketReady(organization_id, ticket.id, ticket.order_id))
        await self.events.stage_many(tuple(events), occurred_at=occurred_at)
        await self.session.flush()
        return ticket

    async def stage_order_complete(
        self, organization_id: UUID, order_id: UUID, occurred_at: datetime
    ) -> KitchenTicketModel:
        ticket = await self.session.scalar(
            select(KitchenTicketModel)
            .where(
                KitchenTicketModel.organization_id == organization_id,
                KitchenTicketModel.order_id == order_id,
            )
            .with_for_update()
        )
        if ticket is None:
            raise KitchenNotFound("Kitchen ticket has not been created")
        if ticket.status == KitchenTicketStatus.COMPLETED.value:
            return ticket
        if ticket.status != KitchenTicketStatus.READY.value:
            raise KitchenWorkNotReady("Kitchen ticket is not ready")
        ticket.status = KitchenTicketStatus.COMPLETED.value
        ticket.completed_at = ticket.updated_at = occurred_at
        ticket.version = await self._next_version(ticket.location_id, ticket.version)
        await self.events.stage(
            KitchenTicketCompleted(organization_id, ticket.id, ticket.order_id),
            occurred_at=occurred_at,
        )
        await self.session.flush()
        return ticket

    async def list_stations(self, context: TenantContext, location_id: UUID):
        await self._location(context, location_id)
        await self._ensure_default(context.organization_id, location_id)
        await self.session.commit()
        return tuple(
            await self.session.scalars(
                select(KitchenStationModel)
                .where(
                    KitchenStationModel.organization_id == context.organization_id,
                    KitchenStationModel.location_id == location_id,
                )
                .order_by(KitchenStationModel.sort_order, KitchenStationModel.name)
            )
        )

    async def create_station(self, context: TenantContext, payload):
        await self._location(context, payload.location_id)
        model = KitchenStationModel(
            id=uuid4(),
            organization_id=context.organization_id,
            location_id=payload.location_id,
            name=payload.name.strip(),
            code=payload.code.strip().upper(),
            role=payload.role,
            is_default=False,
            is_active=True,
            warning_after_seconds=payload.warning_after_seconds,
            late_after_seconds=payload.late_after_seconds,
            sort_order=payload.sort_order,
        )
        self.session.add(model)
        return await self._commit(model)

    async def update_station(self, context: TenantContext, station_id: UUID, payload):
        model = await self._station(context.organization_id, station_id, lock=True)
        await self._location(context, model.location_id)
        for name in (
            "name",
            "code",
            "role",
            "is_active",
            "warning_after_seconds",
            "late_after_seconds",
            "sort_order",
        ):
            value = getattr(payload, name)
            if value is not None:
                setattr(model, name, value.strip().upper() if name == "code" else value)
        if model.is_default and model.is_active is False:
            raise KitchenInvalid("Default kitchen station cannot be deactivated")
        return await self._commit(model)

    async def list_routing(self, context: TenantContext, location_id: UUID):
        await self._location(context, location_id)
        return tuple(
            await self.session.scalars(
                select(KitchenRoutingRuleModel)
                .where(
                    KitchenRoutingRuleModel.organization_id == context.organization_id,
                    KitchenRoutingRuleModel.location_id == location_id,
                )
                .order_by(KitchenRoutingRuleModel.priority.desc(), KitchenRoutingRuleModel.id)
            )
        )

    async def create_routing(self, context: TenantContext, payload):
        await self._location(context, payload.location_id)
        station = await self._station(context.organization_id, payload.station_id)
        if station.location_id != payload.location_id:
            raise KitchenInvalid("Station belongs to a different location")
        target = (
            await self.session.scalar(
                select(MenuCategoryModel.id).where(
                    MenuCategoryModel.id == payload.category_id,
                    MenuCategoryModel.organization_id == context.organization_id,
                )
            )
            if payload.scope == KitchenRoutingScope.CATEGORY
            else await self.session.scalar(
                select(ProductVariantModel.id).where(
                    ProductVariantModel.id == payload.variant_id,
                    ProductVariantModel.organization_id == context.organization_id,
                )
            )
        )
        if target is None:
            raise KitchenInvalid("Kitchen routing target not found")
        model = KitchenRoutingRuleModel(
            id=uuid4(),
            organization_id=context.organization_id,
            location_id=payload.location_id,
            station_id=payload.station_id,
            scope=payload.scope,
            category_id=payload.category_id,
            variant_id=payload.variant_id,
            order_type=payload.order_type,
            priority=payload.priority,
            is_active=True,
        )
        self.session.add(model)
        return await self._commit(model)

    async def delete_routing(self, context: TenantContext, rule_id: UUID) -> None:
        model = await self.session.scalar(
            select(KitchenRoutingRuleModel)
            .where(
                KitchenRoutingRuleModel.id == rule_id,
                KitchenRoutingRuleModel.organization_id == context.organization_id,
            )
            .with_for_update()
        )
        if model is None:
            raise KitchenNotFound("Kitchen routing rule not found")
        await self._location(context, model.location_id)
        await self.session.delete(model)
        await self.session.commit()

    async def project_payment(
        self, organization_id: UUID, payment_id: UUID, order_id: UUID
    ) -> KitchenTicketModel:
        existing = await self.session.scalar(
            select(KitchenTicketModel).where(
                KitchenTicketModel.organization_id == organization_id,
                KitchenTicketModel.order_id == order_id,
            )
        )
        if existing is not None:
            return existing
        payment = await self.session.scalar(
            select(PaymentModel).where(
                PaymentModel.id == payment_id,
                PaymentModel.organization_id == organization_id,
                PaymentModel.order_id == order_id,
            )
        )
        order = await self.session.scalar(
            select(SalesOrderModel)
            .options(
                selectinload(SalesOrderModel.items).selectinload(SalesOrderItemModel.modifiers)
            )
            .where(
                SalesOrderModel.id == order_id,
                SalesOrderModel.organization_id == organization_id,
            )
        )
        if payment is None or order is None or order.status != "PAID":
            raise KitchenInvalid("Payment source is not a paid order")
        fulfillment = await self.session.scalar(
            select(OnlineOrderFulfillmentModel)
            .join(
                OnlineOrderModel,
                OnlineOrderModel.id == OnlineOrderFulfillmentModel.online_order_id,
            )
            .where(
                OnlineOrderModel.organization_id == organization_id,
                OnlineOrderModel.sales_order_id == order_id,
            )
        )
        stations = await self._active_stations(organization_id, order.location_id)
        default = next((value for value in stations if value.is_default), None)
        if default is None:
            default = await self._ensure_default(organization_id, order.location_id)
            stations = (*stations, default)
        rules = tuple(
            await self.session.scalars(
                select(KitchenRoutingRuleModel).where(
                    KitchenRoutingRuleModel.organization_id == organization_id,
                    KitchenRoutingRuleModel.location_id == order.location_id,
                    KitchenRoutingRuleModel.is_active.is_(True),
                )
            )
        )
        product_ids = tuple({item.product_id for item in order.items})
        category_rows = await self.session.execute(
            select(ProductModel.id, ProductModel.category_id).where(
                ProductModel.id.in_(product_ids),
                ProductModel.organization_id == organization_id,
            )
        )
        categories = {row.id: row.category_id for row in category_rows}
        if len(categories) != len(product_ids):
            raise KitchenInvalid("Paid order contains an unknown product snapshot")
        fired_at = datetime.now(UTC)
        ticket = KitchenTicketModel(
            id=uuid4(),
            organization_id=organization_id,
            location_id=order.location_id,
            order_id=order.id,
            payment_id=payment.id,
            shift_id=order.shift_id,
            order_number=order.number,
            order_type=order.order_type,
            order_source=order.order_source,
            customer_id=order.customer_id,
            customer_name=order.customer_name_snapshot,
            customer_phone=order.customer_phone_snapshot,
            table_label=order.table_label,
            guest_count=order.guest_count,
            note=order.note,
            fulfillment_type=(fulfillment.fulfillment_type if fulfillment else None),
            promised_at=(fulfillment.promised_at if fulfillment else None),
            guest_instructions=(fulfillment.guest_instructions if fulfillment else None),
            status=KitchenTicketStatus.QUEUED,
            ordered_at=_utc(payment.completed_at),
            fired_at=fired_at,
            version=await self._next_version(order.location_id),
        )
        station_by_id = {value.id: value for value in stations}
        for sort_order, source in enumerate(order.items):
            item = KitchenTicketItemModel(
                id=uuid4(),
                order_item_id=source.id,
                product_id=source.product_id,
                variant_id=source.product_variant_id,
                category_id=categories[source.product_id],
                product_name=source.product_name,
                variant_name=source.variant_name,
                quantity=source.quantity,
                note=source.note,
                sort_order=sort_order,
            )
            item.modifiers = [
                KitchenTicketItemModifierModel(
                    id=uuid4(),
                    modifier_group_id=modifier.modifier_group_id,
                    modifier_group_name=modifier.modifier_group_name,
                    modifier_option_id=modifier.modifier_option_id,
                    modifier_option_name=modifier.modifier_option_name,
                    sort_order=modifier.sort_order,
                )
                for modifier in sorted(source.modifiers, key=lambda value: value.sort_order)
            ]
            route_ids = self._route_ids(
                rules,
                variant_id=source.product_variant_id,
                category_id=categories[source.product_id],
                order_type=order.order_type,
            )
            prep_ids = {
                station_id
                for station_id in route_ids
                if station_id in station_by_id
                and station_by_id[station_id].role != KitchenStationRole.EXPO
            }
            if not prep_ids:
                prep_ids = {default.id}
            item.work_items = [
                KitchenWorkItemModel(
                    id=uuid4(),
                    organization_id=organization_id,
                    location_id=order.location_id,
                    ticket_id=ticket.id,
                    ticket_item_id=item.id,
                    station_id=station_id,
                    status=KitchenWorkStatus.QUEUED,
                )
                for station_id in sorted(prep_ids, key=str)
            ]
            ticket.items.append(item)
        if len(ticket.items) != len(order.items):
            raise KitchenInvalid("Kitchen ticket item snapshot is incomplete")
        try:
            async with self.session.begin_nested():
                self.session.add(ticket)
                await self.session.flush()
        except IntegrityError:
            existing = await self.session.scalar(
                select(KitchenTicketModel).where(
                    KitchenTicketModel.organization_id == organization_id,
                    KitchenTicketModel.order_id == order_id,
                )
            )
            if existing is None:
                raise
            return existing
        await self.events.stage(
            KitchenTicketCreated(organization_id, ticket.id, order.id, payment.id),
            occurred_at=fired_at,
        )
        metrics.kitchen_tickets.add(1, {"location_id": str(order.location_id)})
        return ticket

    async def board(
        self, context: TenantContext, station_id: UUID, after_version: int | None
    ) -> tuple[KitchenStationModel, tuple[KitchenTicketModel, ...], int]:
        station = await self._station(context.organization_id, station_id)
        await self._location(context, station.location_id)
        ticket_ids = select(KitchenWorkItemModel.ticket_id).where(
            KitchenWorkItemModel.station_id == station.id
        )
        where = [
            KitchenTicketModel.organization_id == context.organization_id,
            KitchenTicketModel.location_id == station.location_id,
            KitchenTicketModel.status != KitchenTicketStatus.CANCELLED,
        ]
        if station.role == KitchenStationRole.PREP:
            where.append(KitchenTicketModel.id.in_(ticket_ids))
        if after_version is not None and after_version > 0:
            where.append(KitchenTicketModel.version >= after_version)
        tickets = tuple(
            await self.session.scalars(
                select(KitchenTicketModel)
                .options(
                    selectinload(KitchenTicketModel.items).selectinload(
                        KitchenTicketItemModel.modifiers
                    ),
                    selectinload(KitchenTicketModel.items).selectinload(
                        KitchenTicketItemModel.work_items
                    ),
                    selectinload(KitchenTicketModel.work_items),
                )
                .where(*where)
                .order_by(KitchenTicketModel.fired_at, KitchenTicketModel.id)
            )
        )
        cursor = max((ticket.version for ticket in tickets), default=after_version or 0)
        return station, tickets, cursor

    async def get_ticket(self, context: TenantContext, ticket_id: UUID):
        ticket = await self._ticket(context.organization_id, ticket_id)
        await self._location(context, ticket.location_id)
        return ticket

    async def start_work(self, context: TenantContext, work_item_id: UUID, client_action_id: UUID):
        return await self._work_action(context, work_item_id, client_action_id, start=True)

    async def ready_work(self, context: TenantContext, work_item_id: UUID, client_action_id: UUID):
        return await self._work_action(context, work_item_id, client_action_id, start=False)

    async def _work_action(self, context, work_item_id, client_action_id, *, start):
        action_type = "START" if start else "READY"
        await self._lock_action(context.organization_id)
        replay = await self._replay(
            context.organization_id, client_action_id, action_type, work_item_id
        )
        if replay:
            return await self._work(context.organization_id, work_item_id)
        work = await self._work(context.organization_id, work_item_id, lock=True)
        await self._location(context, work.location_id)
        ticket = await self._ticket(context.organization_id, work.ticket_id, lock=True)
        now = datetime.now(UTC)
        events: list[object] = []
        if start:
            if work.status != KitchenWorkStatus.QUEUED:
                raise KitchenInvalid("Only queued kitchen work can be started")
            work.status = KitchenWorkStatus.PREPARING
            work.started_at = now
            if ticket.started_at is None:
                ticket.started_at = now
                metrics.kitchen_queue_seconds.record(
                    max(0.0, (now - _utc(ticket.fired_at)).total_seconds())
                )
            ticket.status = KitchenTicketStatus.PREPARING
            events.append(
                KitchenWorkStarted(context.organization_id, ticket.id, work.id, work.station_id)
            )
        else:
            if work.status != KitchenWorkStatus.PREPARING:
                raise KitchenInvalid("Only preparing kitchen work can be marked ready")
            work.status = KitchenWorkStatus.READY
            work.ready_at = now
            events.append(
                KitchenWorkReady(context.organization_id, ticket.id, work.id, work.station_id)
            )
            station = await self._station(context.organization_id, work.station_id)
            elapsed = max(0.0, (now - _utc(work.started_at or now)).total_seconds())
            if elapsed >= station.late_after_seconds:
                metrics.kitchen_late_tickets.add(
                    1, {"location_id": str(ticket.location_id), "station_id": str(station.id)}
                )
            statuses = tuple(
                await self.session.scalars(
                    select(KitchenWorkItemModel.status).where(
                        KitchenWorkItemModel.ticket_id == ticket.id,
                        KitchenWorkItemModel.id != work.id,
                    )
                )
            )
            if all(value == KitchenWorkStatus.READY for value in statuses):
                ticket.status = KitchenTicketStatus.READY
                ticket.ready_at = now
                events.append(
                    KitchenTicketReady(context.organization_id, ticket.id, ticket.order_id)
                )
                metrics.kitchen_tickets_ready.add(1, {"location_id": str(ticket.location_id)})
                metrics.kitchen_prep_seconds.record(
                    max(0.0, (now - _utc(ticket.started_at or ticket.fired_at)).total_seconds())
                )
            else:
                ticket.status = KitchenTicketStatus.PREPARING
        ticket.version = await self._next_version(ticket.location_id, ticket.version)
        ticket.updated_at = now
        await self._record_action(
            context, client_action_id, action_type, work.id, work.status, ticket.version
        )
        await self.events.stage_many(tuple(events), occurred_at=now)
        await self._commit(work)
        return work

    async def complete_ticket(self, context, ticket_id, client_action_id):
        return await self._ticket_action(context, ticket_id, client_action_id, recall=False)

    async def recall_ticket(self, context, ticket_id, client_action_id):
        return await self._ticket_action(context, ticket_id, client_action_id, recall=True)

    async def _ticket_action(self, context, ticket_id, client_action_id, *, recall):
        action_type = "RECALL" if recall else "COMPLETE"
        await self._lock_action(context.organization_id)
        replay = await self._replay(
            context.organization_id, client_action_id, action_type, ticket_id
        )
        if replay:
            return await self._ticket(context.organization_id, ticket_id)
        ticket = await self._ticket(context.organization_id, ticket_id, lock=True)
        await self._location(context, ticket.location_id)
        now = datetime.now(UTC)
        if recall:
            if ticket.status != KitchenTicketStatus.COMPLETED:
                raise KitchenInvalid("Only completed kitchen tickets can be recalled")
            ticket.status = KitchenTicketStatus.READY
            ticket.completed_at = None
            event = KitchenTicketRecalled(context.organization_id, ticket.id, ticket.order_id)
        else:
            if ticket.status != KitchenTicketStatus.READY:
                raise KitchenWorkNotReady("All required kitchen work must be ready")
            ticket.status = KitchenTicketStatus.COMPLETED
            ticket.completed_at = now
            event = KitchenTicketCompleted(context.organization_id, ticket.id, ticket.order_id)
            metrics.kitchen_tickets_completed.add(1, {"location_id": str(ticket.location_id)})
            metrics.kitchen_ready_to_pickup_seconds.record(
                max(0.0, (now - _utc(ticket.ready_at or now)).total_seconds())
            )
        ticket.version = await self._next_version(ticket.location_id, ticket.version)
        ticket.updated_at = now
        await self._record_action(
            context, client_action_id, action_type, ticket.id, ticket.status, ticket.version
        )
        await self.events.stage(event, occurred_at=now)
        return await self._commit(ticket)

    async def readiness(self, context: TenantContext, location_id: UUID):
        await self._location(context, location_id)
        stations = await self.list_stations(context, location_id)
        active = tuple(value for value in stations if value.is_active)
        default = next((value for value in active if value.is_default), None)
        return {
            "ready": bool(active and default),
            "active_stations": len(active),
            "default_station": default,
            "unrouted_variants": [],
        }

    async def performance(
        self,
        context: TenantContext,
        *,
        location_id: UUID | None,
        date_from: date | None,
        date_to: date | None,
    ):
        if location_id:
            await self._location(context, location_id)
        allowed = await self._allowed_locations(context)
        conditions = [KitchenTicketModel.organization_id == context.organization_id]
        if location_id:
            conditions.append(KitchenTicketModel.location_id == location_id)
        elif allowed is not None:
            conditions.append(KitchenTicketModel.location_id.in_(allowed))
        if date_from:
            conditions.append(
                KitchenTicketModel.completed_at >= datetime.combine(date_from, time.min, UTC)
            )
        if date_to:
            conditions.append(
                KitchenTicketModel.completed_at
                < datetime.combine(date_to + timedelta(days=1), time.min, UTC)
            )
        rows = (
            await self.session.execute(
                select(
                    KitchenWorkItemModel.location_id,
                    KitchenWorkItemModel.station_id,
                    KitchenStationModel.name,
                    KitchenStationModel.late_after_seconds,
                    KitchenWorkItemModel.started_at,
                    KitchenWorkItemModel.ready_at,
                )
                .join(KitchenTicketModel, KitchenTicketModel.id == KitchenWorkItemModel.ticket_id)
                .join(
                    KitchenStationModel, KitchenStationModel.id == KitchenWorkItemModel.station_id
                )
                .where(
                    *conditions,
                    KitchenTicketModel.status == KitchenTicketStatus.COMPLETED,
                    KitchenWorkItemModel.ready_at.is_not(None),
                )
            )
        ).all()
        groups: dict[tuple, list[tuple[float, int]]] = {}
        for loc, station, name, late, started, ready in rows:
            seconds = max(0.0, (_utc(ready) - _utc(started)).total_seconds())
            groups.setdefault((loc, station, name), []).append((seconds, late))
        result = []
        for (loc, station, name), values in groups.items():
            durations = sorted(value[0] for value in values)
            late_count = sum(value[0] >= value[1] for value in values)
            result.append(
                {
                    "location_id": loc,
                    "station_id": station,
                    "station_name": name,
                    "completed_count": len(durations),
                    "average_seconds": sum(durations) / len(durations),
                    "p50_seconds": median(durations),
                    "p95_seconds": durations[max(0, int(len(durations) * 0.95 + 0.999) - 1)],
                    "late_percent": late_count * 100 / len(durations),
                }
            )
        return result

    async def _allowed_locations(self, context):
        if context.location_access == "ALL":
            return None
        from beanly.modules.organizations.infrastructure.db.models import MembershipLocationModel

        return tuple(
            await self.session.scalars(
                select(MembershipLocationModel.location_id).where(
                    MembershipLocationModel.membership_id == context.membership_id
                )
            )
        )

    async def _location(self, context, location_id):
        try:
            await self.organizations.ensure_location_access(context, location_id)
        except Exception as exc:
            raise KitchenNotFound("Kitchen location not found") from exc

    async def _station(self, organization_id, station_id, *, lock=False):
        query = select(KitchenStationModel).where(
            KitchenStationModel.id == station_id,
            KitchenStationModel.organization_id == organization_id,
        )
        model = await self.session.scalar(query.with_for_update() if lock else query)
        if model is None:
            raise KitchenNotFound("Kitchen station not found")
        return model

    async def _ticket(self, organization_id, ticket_id, *, lock=False):
        query = (
            select(KitchenTicketModel)
            .options(
                selectinload(KitchenTicketModel.items).selectinload(
                    KitchenTicketItemModel.modifiers
                ),
                selectinload(KitchenTicketModel.items).selectinload(
                    KitchenTicketItemModel.work_items
                ),
                selectinload(KitchenTicketModel.work_items),
            )
            .where(
                KitchenTicketModel.id == ticket_id,
                KitchenTicketModel.organization_id == organization_id,
            )
        )
        model = await self.session.scalar(query.with_for_update() if lock else query)
        if model is None:
            raise KitchenNotFound("Kitchen ticket not found")
        return model

    async def _work(self, organization_id, work_item_id, *, lock=False):
        query = select(KitchenWorkItemModel).where(
            KitchenWorkItemModel.id == work_item_id,
            KitchenWorkItemModel.organization_id == organization_id,
        )
        model = await self.session.scalar(query.with_for_update() if lock else query)
        if model is None:
            raise KitchenNotFound("Kitchen work item not found")
        return model

    async def _active_stations(self, organization_id, location_id):
        return tuple(
            await self.session.scalars(
                select(KitchenStationModel).where(
                    KitchenStationModel.organization_id == organization_id,
                    KitchenStationModel.location_id == location_id,
                    KitchenStationModel.is_active.is_(True),
                )
            )
        )

    async def _ensure_default(self, organization_id, location_id):
        existing = await self.session.scalar(
            select(KitchenStationModel).where(
                KitchenStationModel.organization_id == organization_id,
                KitchenStationModel.location_id == location_id,
                KitchenStationModel.is_default.is_(True),
            )
        )
        if existing:
            return existing
        model = KitchenStationModel(
            id=uuid5(NAMESPACE_URL, f"beanly:kitchen:default:{location_id}"),
            organization_id=organization_id,
            location_id=location_id,
            name="Preparation",
            code="PREPARATION",
            role=KitchenStationRole.PREP_EXPO,
            is_default=True,
            is_active=True,
            warning_after_seconds=600,
            late_after_seconds=900,
            sort_order=0,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(model)
                await self.session.flush()
        except IntegrityError:
            return await self.session.scalar(
                select(KitchenStationModel).where(
                    KitchenStationModel.location_id == location_id,
                    KitchenStationModel.is_default.is_(True),
                )
            )
        return model

    @staticmethod
    def _route_ids(rules, *, variant_id, category_id, order_type):
        matched = []
        for rule in rules:
            if rule.order_type is not None and rule.order_type != order_type:
                continue
            if rule.scope == KitchenRoutingScope.VARIANT and rule.variant_id == variant_id:
                score = 4 if rule.order_type else 3
            elif rule.scope == KitchenRoutingScope.CATEGORY and rule.category_id == category_id:
                score = 2 if rule.order_type else 1
            else:
                continue
            matched.append((score, rule.priority, rule.station_id))
        if not matched:
            return set()
        best_score = max(value[0] for value in matched)
        best_priority = max(value[1] for value in matched if value[0] == best_score)
        return {
            value[2] for value in matched if value[0] == best_score and value[1] == best_priority
        }

    async def _next_version(self, location_id, current=0):
        maximum = await self.session.scalar(
            select(func.max(KitchenTicketModel.version)).where(
                KitchenTicketModel.location_id == location_id
            )
        )
        return max(int(maximum or 0), int(current)) + 1

    async def _replay(self, organization_id, client_action_id, action_type, resource_id):
        action = await self.session.scalar(
            select(KitchenActionModel).where(
                KitchenActionModel.organization_id == organization_id,
                KitchenActionModel.client_action_id == client_action_id,
            )
        )
        if action is None:
            return None
        expected = _payload_hash(action_type, resource_id)
        if action.payload_hash != expected:
            raise KitchenActionIdempotencyConflict("Kitchen action id was reused")
        return action

    async def _lock_action(self, organization_id: UUID) -> None:
        await self.session.scalar(
            select(OrganizationModel.id)
            .where(OrganizationModel.id == organization_id)
            .with_for_update()
        )

    async def _record_action(
        self, context, client_action_id, action_type, resource_id, status, version
    ):
        self.session.add(
            KitchenActionModel(
                id=uuid4(),
                organization_id=context.organization_id,
                location_id=(await self._resource_location(action_type, resource_id)),
                client_action_id=client_action_id,
                action_type=action_type,
                resource_id=resource_id,
                payload_hash=_payload_hash(action_type, resource_id),
                result_payload={"status": str(status), "version": version},
                actor_user_id=context.user_id,
            )
        )
        await self.session.flush()

    async def _resource_location(self, action_type, resource_id):
        if action_type in {"START", "READY"}:
            return await self.session.scalar(
                select(KitchenWorkItemModel.location_id).where(
                    KitchenWorkItemModel.id == resource_id
                )
            )
        return await self.session.scalar(
            select(KitchenTicketModel.location_id).where(KitchenTicketModel.id == resource_id)
        )

    async def _commit(self, value):
        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return value


def _payload_hash(action_type: str, resource_id: UUID) -> str:
    raw = json.dumps({"action": action_type, "resource_id": str(resource_id)}, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
