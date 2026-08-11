from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from beanly.modules.offline_pos.api.schemas import OfflineOrderRequest
from beanly.modules.offline_pos.domain.exceptions import OrderChangedOnServer
from beanly.modules.offline_pos.infrastructure.db.models import (
    PosCatalogSnapshotModel,
    PosDeviceModel,
    PosOfflineSessionModel,
)
from beanly.modules.offline_pos.infrastructure.snapshot_resolver import resolve_snapshot_item
from beanly.modules.organizations.application.queries.get_organization import GetOrganizationQuery
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.sales.application.order_service import _snapshot_item
from beanly.modules.sales.domain.entities import SalesOrder
from beanly.modules.sales.domain.enums import OrderStatus
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
            if order.offline_session_id != session.id or order.pos_device_id != device.id:
                raise OrderChangedOnServer("Order belongs to another POS session")
            if request.base_server_version != order.version:
                raise OrderChangedOnServer("Order changed on server")
            if order.status != OrderStatus.OPEN:
                raise OrderChangedOnServer("Order is immutable on server")
            order = await self.repository.update_order(
                replace(
                    order,
                    order_type=request.order_type,
                    offline_display_number=request.offline_display_number,
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
