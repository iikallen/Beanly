from dataclasses import replace
from datetime import UTC, datetime, time
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select

from beanly.modules.offline_pos.api.schemas import OfflineOrderRequest
from beanly.modules.offline_pos.domain.exceptions import OrderChangedOnServer
from beanly.modules.offline_pos.infrastructure.db.models import (
    PosCatalogSnapshotModel,
    PosDeviceModel,
    PosOfflineSessionModel,
)
from beanly.modules.offline_pos.infrastructure.snapshot_resolver import resolve_snapshot_item
from beanly.modules.online_ordering.domain.enums import OnlineOrderStatus
from beanly.modules.online_ordering.infrastructure.db.models import OnlineOrderModel
from beanly.modules.organizations.application.queries.get_organization import GetOrganizationQuery
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.promotions.domain.entities import Promotion, PromotionSchedule, PromotionTarget
from beanly.modules.promotions.domain.enums import (
    ApplicationMode,
    DiscountKind,
    PromotionScope,
    PromotionStatus,
    StackingPolicy,
    TargetRole,
    TargetType,
)
from beanly.modules.promotions.infrastructure.pricing_service import reprice_order
from beanly.modules.sales.application.order_service import _snapshot_item
from beanly.modules.sales.domain.entities import SalesOrder
from beanly.modules.sales.domain.enums import OrderSource, OrderStatus
from beanly.modules.sales.domain.exceptions import OrderImmutable
from beanly.modules.sales.domain.repositories import SalesRepository


class OfflineSalesGateway:
    def __init__(self, repository: SalesRepository, organizations: OrganizationService) -> None:
        self.repository = repository
        self.organizations = organizations

    async def reconcile_staged(
        self,
        context: TenantContext,
        device: PosDeviceModel,
        session: PosOfflineSessionModel,
        snapshot: PosCatalogSnapshotModel,
        request: OfflineOrderRequest,
    ) -> SalesOrder:
        order = await self.repository.get_order_by_client_id(
            context.organization_id, request.client_order_id
        )
        if order is None:
            if request.base_server_version is not None:
                raise OrderChangedOnServer("New offline order cannot have a server version")
            organization = await self.organizations.get_organization(
                GetOrganizationQuery(context.user_id, context.organization_id)
            )
            recorded_at = datetime.now(UTC)
            order = await self.repository.add_order(
                SalesOrder(
                    id=uuid4(),
                    organization_id=context.organization_id,
                    location_id=session.location_id,
                    shift_id=session.shift_id,
                    warehouse_id=session.warehouse_id,
                    number=await self.repository.next_order_number(),
                    client_order_id=request.client_order_id,
                    order_type=request.order_type,
                    status=OrderStatus.OPEN,
                    currency_code=organization.currency_code,
                    guest_count=None,
                    table_label=None,
                    note=None,
                    subtotal_minor=0,
                    total_minor=0,
                    created_by_user_id=session.actor_user_id,
                    cancelled_by_user_id=None,
                    cancelled_at=None,
                    cancel_reason=None,
                    paid_by_user_id=None,
                    paid_at=None,
                    created_at=recorded_at,
                    updated_at=recorded_at,
                    version=1,
                    pos_device_id=device.id,
                    offline_session_id=session.id,
                    client_created_at=request.created_at.astimezone(UTC),
                    offline_display_number=request.offline_display_number,
                )
            )
        else:
            order = await self.repository.get_order(context.organization_id, order.id, lock=True)
            if order is None:
                raise OrderChangedOnServer("Order disappeared during sync")
            if request.base_server_version != order.version:
                raise OrderChangedOnServer("Order changed on server")
            if order.status != OrderStatus.OPEN:
                raise OrderChangedOnServer("Order is immutable on server")
            owned_by_session = (
                order.offline_session_id == session.id and order.pos_device_id == device.id
            )
            claimable_online_order = (
                order.offline_session_id is None
                and order.pos_device_id is None
                and order.order_source in (OrderSource.ONLINE, OrderSource.QR)
                and order.location_id == session.location_id
                and order.shift_id == session.shift_id
                and order.warehouse_id == session.warehouse_id
            )
            if claimable_online_order:
                claimable_online_order = bool(
                    await self.repository.session.scalar(
                        select(OnlineOrderModel.id).where(
                            OnlineOrderModel.organization_id == context.organization_id,
                            OnlineOrderModel.sales_order_id == order.id,
                            OnlineOrderModel.status
                            == OnlineOrderStatus.AWAITING_PAYMENT.value,
                        )
                    )
                )
            if not owned_by_session and not claimable_online_order:
                raise OrderChangedOnServer("Order belongs to another POS session")
            order = await self.repository.update_order(
                replace(
                    order,
                    order_type=request.order_type,
                    offline_display_number=request.offline_display_number,
                    pos_device_id=device.id,
                    offline_session_id=session.id,
                    updated_at=datetime.now(UTC),
                    version=order.version + 1,
                )
            )

        existing = {value.client_item_id: value for value in order.items}
        desired_ids = {value.client_item_id for value in request.items}
        now = datetime.now(UTC)
        for item in request.items:
            resolved = resolve_snapshot_item(
                snapshot.private_payload,
                item.variant_id,
                tuple(item.selected_option_ids),
            )
            current = existing.get(item.client_item_id)
            staged = _snapshot_item(
                order.id,
                item.client_item_id,
                resolved,
                item.quantity,
                item.note.strip() or None if item.note is not None else None,
                now,
                item_id=current.id if current else None,
                created_at=current.created_at if current else None,
            )
            if current is None:
                await self.repository.add_item(staged)
            else:
                await self.repository.replace_item_configuration(staged)
        for item in order.items:
            if item.client_item_id not in desired_ids:
                await self.repository.delete_item(order.id, item.id)
        order = await self.repository.recalculate_order_totals(context.organization_id, order.id)
        occurred_at = request.payment.completed_at if request.payment else request.updated_at
        if order.order_source in (OrderSource.ONLINE, OrderSource.QR):
            if request.manual_promotion_ids:
                raise OrderImmutable("Online order promotions are server-authoritative")
            await reprice_order(
                self.repository.session,
                context.organization_id,
                order.id,
                occurred_at=occurred_at,
            )
            order = await self.repository.get_order(context.organization_id, order.id)
            assert order is not None
            if request.status == "CANCELLED":
                raise OrderImmutable("Online orders must be cancelled through Online Orders")
            if request.status == "PAID" and not order.items:
                raise OrderImmutable("Paid offline order must contain items")
            return order

        promotions = _compiled_promotions(snapshot.public_payload, context.organization_id)
        requested = set(request.manual_promotion_ids)
        allowed_manual = {
            value.id
            for value in promotions
            if value.application_mode == ApplicationMode.MANUAL
            and not value.requires_override_permission
        }
        if not requested <= allowed_manual:
            raise OrderImmutable("Offline manual promotion is not allowed by the snapshot")
        await reprice_order(
            self.repository.session,
            context.organization_id,
            order.id,
            occurred_at=occurred_at,
            promotion_snapshot=promotions,
            manual_promotion_ids=tuple(sorted(requested, key=str)),
        )
        order = await self.repository.get_order(context.organization_id, order.id)
        assert order is not None
        if request.status == "CANCELLED":
            order = await self.repository.update_order(
                replace(
                    order,
                    status=OrderStatus.CANCELLED,
                    cancelled_by_user_id=session.actor_user_id,
                    cancelled_at=request.updated_at.astimezone(UTC),
                    cancel_reason="Cancelled offline",
                    updated_at=datetime.now(UTC),
                    version=order.version + 1,
                )
            )
        if request.status == "PAID" and not order.items:
            raise OrderImmutable("Paid offline order must contain items")
        return order


def _compiled_promotions(
    payload: dict[str, object], organization_id: UUID
) -> tuple[Promotion, ...]:
    rows = payload.get("promotions", [])
    if not isinstance(rows, list):
        return ()
    values = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        promotion_id = UUID(str(row["promotion_id"]))
        created_at = datetime.fromisoformat(str(row["created_at"])).astimezone(UTC)
        values.append(
            Promotion(
                promotion_id,
                organization_id,
                str(row["name"]),
                str(row["name"]),
                PromotionStatus.ACTIVE,
                ApplicationMode(str(row["application_mode"])),
                DiscountKind(str(row["kind"])),
                PromotionScope(str(row["scope"])),
                Decimal(str(row["percent_rate"])) if row.get("percent_rate") else None,
                int(str(row["amount_minor"])) if row.get("amount_minor") else None,
                int(str(row["fixed_price_minor"])) if row.get("fixed_price_minor") else None,
                int(row["priority"]),
                StackingPolicy(str(row["stacking"])),
                bool(row["include_modifier_price"]),
                int(str(row["minimum_subtotal_minor"]))
                if row.get("minimum_subtotal_minor")
                else None,
                int(str(row["maximum_discount_minor"]))
                if row.get("maximum_discount_minor")
                else None,
                datetime.fromisoformat(str(row["valid_from"])) if row.get("valid_from") else None,
                datetime.fromisoformat(str(row["valid_to"])) if row.get("valid_to") else None,
                True,
                bool(row.get("requires_override_permission", False)),
                UUID(int=0),
                created_at,
                created_at,
                (),
                tuple(
                    PromotionSchedule(
                        UUID(int=index + 1),
                        promotion_id,
                        int(item["weekday"]),
                        time.fromisoformat(str(item["start_local_time"])),
                        time.fromisoformat(str(item["end_local_time"])),
                    )
                    for index, item in enumerate(row.get("schedules", []))
                ),
                tuple(
                    PromotionTarget(
                        UUID(int=index + 1000),
                        promotion_id,
                        TargetRole(str(item["role"])),
                        TargetType(str(item["target_type"])),
                        UUID(str(item["target_id"])) if item.get("target_id") else None,
                        int(item["quantity"]),
                        int(item["sort_order"]),
                    )
                    for index, item in enumerate(row.get("targets", []))
                ),
            )
        )
    return tuple(values)
