from dataclasses import replace
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError

from beanly.core.events import DomainEventSink, NullDomainEventSink
from beanly.modules.organizations.application.queries.get_organization import (
    GetOrganizationQuery,
)
from beanly.modules.organizations.application.queries.list_locations import (
    ListLocationsQuery,
)
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.purchasing.application.commands import (
    CreateGoodsReceiptCommand,
    CreatePurchaseOrderCommand,
    CreateSupplierReturnCommand,
    PurchaseLineInput,
    ReceiptLineInput,
    SupplierInput,
    SupplierReturnLineInput,
    UpdateGoodsReceiptCommand,
    UpdatePurchaseOrderCommand,
    UpdateSupplierReturnCommand,
)
from beanly.modules.purchasing.application.dto import (
    GoodsReceiptDetail,
    OrderListRow,
    PurchaseOrderDetail,
    ReceiptListRow,
    SupplierReturnDetail,
    SupplierReturnListRow,
)
from beanly.modules.purchasing.application.ports import (
    InventoryGateway,
    InventoryResources,
    PurchaseStockLine,
    ReturnStockLine,
)
from beanly.modules.purchasing.domain.entities import (
    GoodsReceipt,
    GoodsReceiptLine,
    PurchaseOrder,
    PurchaseOrderLine,
    Supplier,
    SupplierReturn,
    SupplierReturnLine,
)
from beanly.modules.purchasing.domain.enums import (
    GoodsReceiptStatus,
    PurchaseOrderStatus,
    SupplierReturnStatus,
)
from beanly.modules.purchasing.domain.events import (
    GoodsReceiptCreated,
    GoodsReceiptPosted,
    GoodsReceiptReversed,
    PurchaseOrderCreated,
    PurchaseOrderPartiallyReceived,
    PurchaseOrderReceived,
    PurchaseOrderSubmitted,
    SupplierCreated,
    SupplierReturnCreated,
    SupplierReturnPosted,
    SupplierReturnReversed,
)
from beanly.modules.purchasing.domain.exceptions import (
    DuplicatePurchasingResource,
    InvalidPurchaseQuantity,
    InvalidPurchasingOperation,
    OverReceiptConfirmationRequired,
    PurchasingNotFound,
)
from beanly.modules.purchasing.domain.repositories import PurchasingRepository

_SIX_PLACES = Decimal("0.000001")
_MONEY_MINOR = Decimal("100")
_KNOWN_MULTIPLIERS = {
    ("g", "g"): Decimal(1),
    ("kg", "g"): Decimal(1000),
    ("ml", "ml"): Decimal(1),
    ("l", "ml"): Decimal(1000),
    ("pcs", "pcs"): Decimal(1),
}


class PurchasingService:
    def __init__(
        self,
        repository: PurchasingRepository,
        organizations: OrganizationService,
        inventory: InventoryGateway,
        sink: DomainEventSink | None = None,
    ) -> None:
        self.repository = repository
        self.organizations = organizations
        self.inventory = inventory
        self.sink = sink or NullDomainEventSink()

    async def create_supplier(self, context: TenantContext, value: SupplierInput) -> Supplier:
        now = datetime.now(UTC)
        supplier = Supplier(
            uuid4(),
            context.organization_id,
            _required_text(value.name, 200, "Supplier name"),
            _text(value.contact_name, 150),
            _text(value.phone, 50),
            _email(value.email),
            _text(value.tax_id, 100),
            _text(value.address, 2000),
            _text(value.note, 2000),
            True,
            now,
            now,
        )
        try:
            created = await self.repository.add_supplier(supplier)
            await self.sink.stage(SupplierCreated(context.organization_id, created.id))
            await self.repository.commit()
        except IntegrityError as exc:
            await self.repository.rollback()
            raise DuplicatePurchasingResource from exc
        except Exception:
            await self.repository.rollback()
            raise
        return created

    async def list_suppliers(
        self, context: TenantContext, include_inactive: bool = False
    ) -> list[Supplier]:
        return await self.repository.list_suppliers(context.organization_id, include_inactive)

    async def get_supplier(self, context: TenantContext, supplier_id: UUID) -> Supplier:
        supplier = await self.repository.get_supplier(context.organization_id, supplier_id)
        if supplier is None:
            raise PurchasingNotFound
        return supplier

    async def update_supplier(
        self, context: TenantContext, supplier_id: UUID, value: SupplierInput
    ) -> Supplier:
        supplier = await self.get_supplier(context, supplier_id)
        updated = replace(
            supplier,
            name=_required_text(value.name, 200, "Supplier name"),
            contact_name=_text(value.contact_name, 150),
            phone=_text(value.phone, 50),
            email=_email(value.email),
            tax_id=_text(value.tax_id, 100),
            address=_text(value.address, 2000),
            note=_text(value.note, 2000),
            updated_at=datetime.now(UTC),
        )
        try:
            await self.repository.update_supplier(updated)
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise
        return updated

    async def deactivate_supplier(self, context: TenantContext, supplier_id: UUID) -> Supplier:
        supplier = await self.get_supplier(context, supplier_id)
        if not supplier.is_active:
            return supplier
        updated = replace(supplier, is_active=False, updated_at=datetime.now(UTC))
        try:
            await self.repository.update_supplier(updated)
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise
        return updated

    async def create_order(
        self, context: TenantContext, command: CreatePurchaseOrderCommand
    ) -> PurchaseOrderDetail:
        supplier = await self._active_supplier(context, command.supplier_id)
        resources = await self._resources(
            context,
            command.location_id,
            command.warehouse_id,
            tuple(line.inventory_item_id for line in command.lines),
        )
        organization = await self.organizations.get_organization(
            GetOrganizationQuery(context.user_id, context.organization_id)
        )
        now = datetime.now(UTC)
        order = PurchaseOrder(
            uuid4(),
            context.organization_id,
            command.location_id,
            command.warehouse_id,
            supplier.id,
            await self.repository.next_order_number(),
            PurchaseOrderStatus.DRAFT,
            organization.currency_code,
            None,
            command.expected_at,
            _text(command.note, 2000),
            context.user_id,
            now,
            now,
        )
        lines = self._order_lines(order.id, command.lines, resources, now)
        try:
            await self.repository.add_order(order)
            await self.repository.add_order_lines(lines)
            await self.sink.stage(PurchaseOrderCreated(context.organization_id, order.id))
            await self.repository.commit()
        except IntegrityError as exc:
            await self.repository.rollback()
            raise DuplicatePurchasingResource from exc
        except Exception:
            await self.repository.rollback()
            raise
        return PurchaseOrderDetail(order, lines, {}, supplier.name)

    async def list_orders(
        self,
        context: TenantContext,
        supplier_id: UUID | None = None,
        location_id: UUID | None = None,
        warehouse_id: UUID | None = None,
        status: PurchaseOrderStatus | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[OrderListRow]:
        locations = await self._location_ids(context)
        if location_id is not None and location_id not in locations:
            raise PurchasingNotFound
        orders = await self.repository.list_orders(
            context.organization_id,
            locations,
            supplier_id,
            location_id,
            warehouse_id,
            status,
            date_from,
            date_to,
        )
        rows: list[OrderListRow] = []
        for order in orders:
            supplier = await self.repository.get_supplier(
                context.organization_id, order.supplier_id
            )
            lines = await self.repository.get_order_lines(context.organization_id, order.id)
            rows.append(
                OrderListRow(
                    order,
                    supplier.name if supplier else "Unknown supplier",
                    sum(line.line_total_minor for line in lines),
                )
            )
        return rows

    async def get_order(self, context: TenantContext, order_id: UUID) -> PurchaseOrderDetail:
        order = await self.repository.get_order(context.organization_id, order_id)
        if order is None:
            raise PurchasingNotFound
        await self._ensure_location(context, order.location_id)
        supplier = await self.get_supplier(context, order.supplier_id)
        lines = await self.repository.get_order_lines(context.organization_id, order.id)
        received = await self.repository.received_totals(context.organization_id, order.id)
        return PurchaseOrderDetail(order, lines, received, supplier.name)

    async def update_order(
        self,
        context: TenantContext,
        order_id: UUID,
        command: UpdatePurchaseOrderCommand,
    ) -> PurchaseOrderDetail:
        order = await self._locked_order(context, order_id)
        if order.status != PurchaseOrderStatus.DRAFT:
            raise InvalidPurchasingOperation("Only draft orders can be edited")
        supplier_id = command.supplier_id or order.supplier_id
        await self._active_supplier(context, supplier_id)
        location_id = command.location_id or order.location_id
        warehouse_id = command.warehouse_id or order.warehouse_id
        current_lines = await self.repository.get_order_lines(context.organization_id, order.id)
        values = command.lines
        item_ids = (
            tuple(line.inventory_item_id for line in values)
            if values is not None
            else tuple(line.inventory_item_id for line in current_lines)
        )
        resources = await self._resources(context, location_id, warehouse_id, item_ids)
        now = datetime.now(UTC)
        updated = replace(
            order,
            supplier_id=supplier_id,
            location_id=location_id,
            warehouse_id=warehouse_id,
            expected_at=(command.expected_at if command.expected_at_set else order.expected_at),
            note=_text(command.note, 2000) if command.note_set else order.note,
            updated_at=now,
        )
        try:
            await self.repository.update_order(updated)
            if values is not None:
                await self.repository.replace_order_lines(
                    context.organization_id,
                    order.id,
                    self._order_lines(order.id, values, resources, now),
                )
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise
        return await self.get_order(context, order.id)

    async def submit_order(self, context: TenantContext, order_id: UUID) -> PurchaseOrderDetail:
        order = await self._locked_order(context, order_id)
        if order.status != PurchaseOrderStatus.DRAFT:
            raise InvalidPurchasingOperation("Only draft orders can be submitted")
        lines = await self.repository.get_order_lines(context.organization_id, order.id)
        if not lines:
            raise InvalidPurchasingOperation("Purchase order has no lines")
        now = datetime.now(UTC)
        updated = replace(
            order,
            status=PurchaseOrderStatus.ORDERED,
            ordered_at=now,
            updated_at=now,
        )
        try:
            await self.repository.update_order(updated)
            await self.sink.stage(PurchaseOrderSubmitted(context.organization_id, order.id))
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise
        return await self.get_order(context, order.id)

    async def cancel_order(self, context: TenantContext, order_id: UUID) -> PurchaseOrderDetail:
        order = await self._locked_order(context, order_id)
        if order.status not in {PurchaseOrderStatus.DRAFT, PurchaseOrderStatus.ORDERED}:
            raise InvalidPurchasingOperation("Order cannot be cancelled")
        if await self.repository.posted_receipt_count(context.organization_id, order.id):
            raise InvalidPurchasingOperation("Received orders cannot be cancelled")
        updated = replace(
            order,
            status=PurchaseOrderStatus.CANCELLED,
            updated_at=datetime.now(UTC),
        )
        try:
            await self.repository.update_order(updated)
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise
        return await self.get_order(context, order.id)

    async def create_receipt(
        self, context: TenantContext, command: CreateGoodsReceiptCommand
    ) -> GoodsReceiptDetail:
        supplier = await self.get_supplier(context, command.supplier_id)
        order: PurchaseOrder | None = None
        if command.purchase_order_id is not None:
            order = await self._locked_order(context, command.purchase_order_id)
            if order.status not in {
                PurchaseOrderStatus.ORDERED,
                PurchaseOrderStatus.PARTIALLY_RECEIVED,
            }:
                raise InvalidPurchasingOperation("Order cannot receive goods")
            if (
                order.supplier_id != command.supplier_id
                or order.location_id != command.location_id
                or order.warehouse_id != command.warehouse_id
            ):
                raise InvalidPurchasingOperation("Receipt does not match purchase order")
        elif not supplier.is_active:
            raise InvalidPurchasingOperation("Inactive supplier cannot be used")
        resources = await self._resources(
            context,
            command.location_id,
            command.warehouse_id,
            tuple(line.inventory_item_id for line in command.lines),
        )
        now = datetime.now(UTC)
        receipt = GoodsReceipt(
            uuid4(),
            context.organization_id,
            command.location_id,
            command.warehouse_id,
            command.purchase_order_id,
            supplier.id,
            await self.repository.next_receipt_number(),
            GoodsReceiptStatus.DRAFT,
            _text(command.document_number, 100),
            command.received_at,
            _text(command.note, 2000),
            context.user_id,
            now,
            now,
            None,
            None,
            None,
            None,
            None,
        )
        order_lines = (
            await self.repository.get_order_lines(context.organization_id, order.id)
            if order is not None
            else ()
        )
        lines = self._receipt_lines(receipt.id, command.lines, resources, order_lines, now)
        try:
            await self.repository.add_receipt(receipt)
            await self.repository.add_receipt_lines(lines)
            await self.sink.stage(GoodsReceiptCreated(context.organization_id, receipt.id))
            await self.repository.commit()
        except IntegrityError as exc:
            await self.repository.rollback()
            raise DuplicatePurchasingResource from exc
        except Exception:
            await self.repository.rollback()
            raise
        return GoodsReceiptDetail(receipt, lines, supplier.name, order.number if order else None)

    async def create_order_receipt(
        self,
        context: TenantContext,
        order_id: UUID,
        lines: tuple[ReceiptLineInput, ...],
        document_number: str | None,
        received_at: datetime,
        note: str | None,
    ) -> GoodsReceiptDetail:
        order = await self._locked_order(context, order_id)
        return await self.create_receipt(
            context,
            CreateGoodsReceiptCommand(
                order.supplier_id,
                order.location_id,
                order.warehouse_id,
                order.id,
                document_number,
                received_at,
                note,
                lines,
            ),
        )

    async def list_receipts(
        self,
        context: TenantContext,
        purchase_order_id: UUID | None = None,
        supplier_id: UUID | None = None,
        status: GoodsReceiptStatus | None = None,
    ) -> list[ReceiptListRow]:
        receipts = await self.repository.list_receipts(
            context.organization_id,
            await self._location_ids(context),
            purchase_order_id,
            supplier_id,
            status,
        )
        rows: list[ReceiptListRow] = []
        for receipt in receipts:
            supplier = await self.repository.get_supplier(
                context.organization_id, receipt.supplier_id
            )
            lines = await self.repository.get_receipt_lines(context.organization_id, receipt.id)
            rows.append(
                ReceiptListRow(
                    receipt,
                    supplier.name if supplier else "Unknown supplier",
                    sum(line.line_total_minor for line in lines),
                )
            )
        return rows

    async def get_receipt(self, context: TenantContext, receipt_id: UUID) -> GoodsReceiptDetail:
        receipt = await self.repository.get_receipt(context.organization_id, receipt_id)
        if receipt is None:
            raise PurchasingNotFound
        await self._ensure_location(context, receipt.location_id)
        supplier = await self.get_supplier(context, receipt.supplier_id)
        order_number = None
        if receipt.purchase_order_id is not None:
            order = await self.repository.get_order(
                context.organization_id, receipt.purchase_order_id
            )
            order_number = order.number if order else None
        return GoodsReceiptDetail(
            receipt,
            await self.repository.get_receipt_lines(context.organization_id, receipt.id),
            supplier.name,
            order_number,
            await self.repository.returned_totals(context.organization_id, receipt.id),
        )

    async def update_receipt(
        self,
        context: TenantContext,
        receipt_id: UUID,
        command: UpdateGoodsReceiptCommand,
    ) -> GoodsReceiptDetail:
        receipt = await self._locked_receipt(context, receipt_id)
        if receipt.status != GoodsReceiptStatus.DRAFT:
            raise InvalidPurchasingOperation("Posted receipts are immutable")
        if receipt.purchase_order_id is not None and any(
            value is not None
            for value in (command.supplier_id, command.location_id, command.warehouse_id)
        ):
            raise InvalidPurchasingOperation("Linked receipt routing is immutable")
        supplier_id = command.supplier_id or receipt.supplier_id
        location_id = command.location_id or receipt.location_id
        warehouse_id = command.warehouse_id or receipt.warehouse_id
        await self.get_supplier(context, supplier_id)
        current_lines = await self.repository.get_receipt_lines(context.organization_id, receipt.id)
        values = command.lines
        item_ids = (
            tuple(line.inventory_item_id for line in values)
            if values is not None
            else tuple(line.inventory_item_id for line in current_lines)
        )
        resources = await self._resources(context, location_id, warehouse_id, item_ids)
        order_lines = (
            await self.repository.get_order_lines(
                context.organization_id, receipt.purchase_order_id
            )
            if receipt.purchase_order_id is not None
            else ()
        )
        now = datetime.now(UTC)
        updated = replace(
            receipt,
            supplier_id=supplier_id,
            location_id=location_id,
            warehouse_id=warehouse_id,
            document_number=(
                _text(command.document_number, 100)
                if command.document_number_set
                else receipt.document_number
            ),
            received_at=command.received_at or receipt.received_at,
            note=_text(command.note, 2000) if command.note_set else receipt.note,
            updated_at=now,
        )
        try:
            await self.repository.update_receipt(updated)
            if values is not None:
                await self.repository.replace_receipt_lines(
                    context.organization_id,
                    receipt.id,
                    self._receipt_lines(receipt.id, values, resources, order_lines, now),
                )
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise
        return await self.get_receipt(context, receipt.id)

    async def post_receipt(
        self,
        context: TenantContext,
        receipt_id: UUID,
        confirm_over_receipt: bool,
    ) -> GoodsReceiptDetail:
        inventory_events: tuple[object, ...] = ()
        purchasing_events: list[object] = []
        try:
            receipt = await self._locked_receipt(context, receipt_id)
            if receipt.status == GoodsReceiptStatus.POSTED:
                await self.repository.commit()
                return await self.get_receipt(context, receipt.id)
            if receipt.status != GoodsReceiptStatus.DRAFT:
                raise InvalidPurchasingOperation("Receipt cannot be posted")
            lines = await self.repository.get_receipt_lines(context.organization_id, receipt.id)
            if not lines:
                raise InvalidPurchasingOperation("Receipt has no lines")
            resources = await self._resources(
                context,
                receipt.location_id,
                receipt.warehouse_id,
                tuple(line.inventory_item_id for line in lines),
            )
            order: PurchaseOrder | None = None
            if receipt.purchase_order_id is not None:
                order = await self._locked_order(context, receipt.purchase_order_id)
                organization = await self.organizations.get_organization(
                    GetOrganizationQuery(context.user_id, context.organization_id)
                )
                if order.currency_code != organization.currency_code:
                    raise InvalidPurchasingOperation(
                        "Purchase order currency no longer matches the organization"
                    )
                if order.status not in {
                    PurchaseOrderStatus.ORDERED,
                    PurchaseOrderStatus.PARTIALLY_RECEIVED,
                }:
                    raise InvalidPurchasingOperation("Order cannot receive goods")
                await self._check_over_receipt(context, order, lines, confirm_over_receipt)
            stock_lines = tuple(
                PurchaseStockLine(
                    line.inventory_item_id,
                    line.base_quantity,
                    resources.items[line.inventory_item_id].base_unit,
                    _acquisition_total(line.received_quantity, line.unit_price),
                )
                for line in lines
            )
            staged = await self.inventory.receive_purchase(
                context,
                receipt.id,
                receipt.warehouse_id,
                f"Goods receipt {receipt.number}",
                stock_lines,
            )
            inventory_events = staged.events
            now = datetime.now(UTC)
            posted = replace(
                receipt,
                status=GoodsReceiptStatus.POSTED,
                posted_by=context.user_id,
                posted_at=now,
                updated_at=now,
                inventory_transaction_id=staged.transaction_id,
            )
            await self.repository.update_receipt(posted)
            purchasing_events.append(
                GoodsReceiptPosted(context.organization_id, receipt.id, staged.transaction_id)
            )
            if order is not None:
                event = await self._recalculate_order(context, order)
                if event is not None:
                    purchasing_events.append(event)
            await self.sink.stage_many((*inventory_events, *purchasing_events))
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise
        return await self.get_receipt(context, receipt_id)

    async def reverse_receipt(self, context: TenantContext, receipt_id: UUID) -> GoodsReceiptDetail:
        inventory_events: tuple[object, ...] = ()
        purchasing_events: list[object] = []
        try:
            receipt = await self._locked_receipt(context, receipt_id)
            if receipt.status != GoodsReceiptStatus.POSTED:
                raise InvalidPurchasingOperation("Only posted receipts can be reversed")
            if receipt.inventory_transaction_id is None:
                raise InvalidPurchasingOperation("Receipt has no inventory transaction")
            linked_returns = await self.repository.list_returns(
                context.organization_id,
                await self._location_ids(context),
                None,
                None,
                receipt.id,
                SupplierReturnStatus.POSTED,
            )
            if linked_returns:
                raise InvalidPurchasingOperation(
                    "Goods receipt with posted supplier returns cannot be reversed"
                )
            staged = await self.inventory.reverse_purchase(
                context,
                receipt.inventory_transaction_id,
                receipt.id,
            )
            inventory_events = staged.events
            now = datetime.now(UTC)
            reversed_receipt = replace(
                receipt,
                status=GoodsReceiptStatus.REVERSED,
                reversed_by=context.user_id,
                reversed_at=now,
                updated_at=now,
            )
            await self.repository.update_receipt(reversed_receipt)
            purchasing_events.append(GoodsReceiptReversed(context.organization_id, receipt.id))
            if receipt.purchase_order_id is not None:
                order = await self._locked_order(context, receipt.purchase_order_id)
                event = await self._recalculate_order(context, order)
                if event is not None:
                    purchasing_events.append(event)
            await self.sink.stage_many((*inventory_events, *purchasing_events))
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise
        return await self.get_receipt(context, receipt_id)

    async def create_supplier_return(
        self,
        context: TenantContext,
        command: CreateSupplierReturnCommand,
    ) -> SupplierReturnDetail:
        supplier = await self._active_supplier(context, command.supplier_id)
        resources = await self._resources(
            context,
            command.location_id,
            command.warehouse_id,
            tuple(line.inventory_item_id for line in command.lines),
        )
        receipt, receipt_lines = await self._linked_receipt(
            context,
            command.goods_receipt_id,
            supplier.id,
            command.location_id,
            command.warehouse_id,
        )
        now = datetime.now(UTC)
        supplier_return = SupplierReturn(
            uuid4(),
            context.organization_id,
            command.location_id,
            command.warehouse_id,
            supplier.id,
            receipt.id if receipt else None,
            await self.repository.next_return_number(),
            SupplierReturnStatus.DRAFT,
            _text(command.document_number, 100),
            command.returned_at,
            _text(command.note, 2000),
            context.user_id,
            None,
            None,
            None,
            None,
            None,
            now,
            now,
        )
        lines = self._return_lines(supplier_return.id, command.lines, resources, receipt_lines, now)
        if receipt is not None:
            await self._check_return_limit(context, supplier_return, lines, receipt_lines)
        try:
            await self.repository.add_return(supplier_return)
            await self.repository.add_return_lines(lines)
            await self.sink.stage(
                SupplierReturnCreated(context.organization_id, supplier_return.id)
            )
            await self.repository.commit()
        except IntegrityError as exc:
            await self.repository.rollback()
            raise DuplicatePurchasingResource from exc
        except Exception:
            await self.repository.rollback()
            raise
        return await self.get_supplier_return(context, supplier_return.id)

    async def list_supplier_returns(
        self,
        context: TenantContext,
        supplier_id: UUID | None = None,
        warehouse_id: UUID | None = None,
        goods_receipt_id: UUID | None = None,
        status: SupplierReturnStatus | None = None,
    ) -> list[SupplierReturnListRow]:
        values = await self.repository.list_returns(
            context.organization_id,
            await self._location_ids(context),
            supplier_id,
            warehouse_id,
            goods_receipt_id,
            status,
        )
        rows = []
        for value in values:
            supplier = await self.repository.get_supplier(
                context.organization_id, value.supplier_id
            )
            receipt = (
                await self.repository.get_receipt(context.organization_id, value.goods_receipt_id)
                if value.goods_receipt_id is not None
                else None
            )
            lines = await self.repository.get_return_lines(context.organization_id, value.id)
            rows.append(
                SupplierReturnListRow(
                    value,
                    supplier.name if supplier else "Unknown supplier",
                    receipt.number if receipt else None,
                    sum(line.line_total_minor for line in lines),
                )
            )
        return rows

    async def get_supplier_return(
        self, context: TenantContext, return_id: UUID
    ) -> SupplierReturnDetail:
        value = await self.repository.get_return(context.organization_id, return_id)
        if value is None:
            raise PurchasingNotFound
        await self._ensure_location(context, value.location_id)
        supplier = await self.get_supplier(context, value.supplier_id)
        receipt = (
            await self.repository.get_receipt(context.organization_id, value.goods_receipt_id)
            if value.goods_receipt_id is not None
            else None
        )
        totals = (
            await self.repository.returned_totals(context.organization_id, value.goods_receipt_id)
            if value.goods_receipt_id is not None
            else {}
        )
        return SupplierReturnDetail(
            value,
            await self.repository.get_return_lines(context.organization_id, value.id),
            supplier.name,
            receipt.number if receipt else None,
            totals,
        )

    async def update_supplier_return(
        self,
        context: TenantContext,
        return_id: UUID,
        command: UpdateSupplierReturnCommand,
    ) -> SupplierReturnDetail:
        value = await self._locked_return(context, return_id)
        if value.status != SupplierReturnStatus.DRAFT:
            raise InvalidPurchasingOperation("Posted supplier returns are immutable")
        supplier_id = command.supplier_id or value.supplier_id
        location_id = command.location_id or value.location_id
        warehouse_id = command.warehouse_id or value.warehouse_id
        goods_receipt_id = (
            command.goods_receipt_id if command.goods_receipt_id_set else value.goods_receipt_id
        )
        await self._active_supplier(context, supplier_id)
        current_lines = await self.repository.get_return_lines(context.organization_id, value.id)
        item_ids = (
            tuple(line.inventory_item_id for line in command.lines)
            if command.lines is not None
            else tuple(line.inventory_item_id for line in current_lines)
        )
        resources = await self._resources(context, location_id, warehouse_id, item_ids)
        receipt, receipt_lines = await self._linked_receipt(
            context,
            goods_receipt_id,
            supplier_id,
            location_id,
            warehouse_id,
        )
        now = datetime.now(UTC)
        updated = replace(
            value,
            supplier_id=supplier_id,
            location_id=location_id,
            warehouse_id=warehouse_id,
            goods_receipt_id=receipt.id if receipt else None,
            document_number=(
                _text(command.document_number, 100)
                if command.document_number_set
                else value.document_number
            ),
            returned_at=command.returned_at or value.returned_at,
            note=_text(command.note, 2000) if command.note_set else value.note,
            updated_at=now,
        )
        lines = (
            self._return_lines(value.id, command.lines, resources, receipt_lines, now)
            if command.lines is not None
            else current_lines
        )
        if receipt is not None:
            await self._check_return_limit(context, updated, lines, receipt_lines)
        elif any(line.goods_receipt_line_id is not None for line in lines):
            raise InvalidPurchasingOperation(
                "Unlinked supplier return lines cannot reference receipt lines"
            )
        try:
            await self.repository.update_return(updated)
            if command.lines is not None:
                await self.repository.replace_return_lines(context.organization_id, value.id, lines)
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise
        return await self.get_supplier_return(context, value.id)

    async def post_supplier_return(
        self, context: TenantContext, return_id: UUID
    ) -> SupplierReturnDetail:
        try:
            value = await self._locked_return(context, return_id)
            if value.status == SupplierReturnStatus.POSTED:
                await self.repository.commit()
                return await self.get_supplier_return(context, value.id)
            if value.status != SupplierReturnStatus.DRAFT:
                raise InvalidPurchasingOperation("Supplier return cannot be posted")
            lines = await self.repository.get_return_lines(context.organization_id, value.id)
            if not lines:
                raise InvalidPurchasingOperation("Supplier return has no lines")
            resources = await self._resources(
                context,
                value.location_id,
                value.warehouse_id,
                tuple(line.inventory_item_id for line in lines),
            )
            receipt, receipt_lines = await self._linked_receipt(
                context,
                value.goods_receipt_id,
                value.supplier_id,
                value.location_id,
                value.warehouse_id,
                lock=True,
            )
            if receipt is not None:
                await self._check_return_limit(context, value, lines, receipt_lines)
            staged = await self.inventory.return_to_supplier(
                context,
                value.id,
                value.warehouse_id,
                f"Supplier return {value.number}",
                tuple(
                    ReturnStockLine(
                        line.inventory_item_id,
                        line.base_quantity,
                        resources.items[line.inventory_item_id].base_unit,
                    )
                    for line in lines
                ),
            )
            now = datetime.now(UTC)
            posted = replace(
                value,
                status=SupplierReturnStatus.POSTED,
                posted_by=context.user_id,
                posted_at=now,
                inventory_transaction_id=staged.transaction_id,
                updated_at=now,
            )
            await self.repository.update_return(posted)
            await self.sink.stage_many(
                (
                    *staged.events,
                    SupplierReturnPosted(context.organization_id, value.id, staged.transaction_id),
                )
            )
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise
        return await self.get_supplier_return(context, return_id)

    async def reverse_supplier_return(
        self, context: TenantContext, return_id: UUID
    ) -> SupplierReturnDetail:
        try:
            value = await self._locked_return(context, return_id)
            if value.status != SupplierReturnStatus.POSTED:
                raise InvalidPurchasingOperation("Only posted supplier returns can be reversed")
            if value.inventory_transaction_id is None:
                raise InvalidPurchasingOperation("Supplier return has no inventory transaction")
            staged = await self.inventory.reverse_supplier_return(
                context, value.inventory_transaction_id, value.id
            )
            now = datetime.now(UTC)
            reversed_value = replace(
                value,
                status=SupplierReturnStatus.REVERSED,
                reversed_by=context.user_id,
                reversed_at=now,
                updated_at=now,
            )
            await self.repository.update_return(reversed_value)
            await self.sink.stage_many(
                (*staged.events, SupplierReturnReversed(context.organization_id, value.id))
            )
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise
        return await self.get_supplier_return(context, return_id)

    async def _linked_receipt(
        self,
        context: TenantContext,
        receipt_id: UUID | None,
        supplier_id: UUID,
        location_id: UUID,
        warehouse_id: UUID,
        *,
        lock: bool = False,
    ) -> tuple[GoodsReceipt | None, tuple[GoodsReceiptLine, ...]]:
        if receipt_id is None:
            return None, ()
        receipt = await self.repository.get_receipt(context.organization_id, receipt_id, lock=lock)
        if receipt is None:
            raise PurchasingNotFound
        await self._ensure_location(context, receipt.location_id)
        if receipt.status != GoodsReceiptStatus.POSTED:
            raise InvalidPurchasingOperation("Linked goods receipt must be posted")
        if receipt.supplier_id != supplier_id:
            raise InvalidPurchasingOperation("Supplier does not match goods receipt")
        if receipt.location_id != location_id or receipt.warehouse_id != warehouse_id:
            raise InvalidPurchasingOperation("Warehouse does not match goods receipt")
        return receipt, await self.repository.get_receipt_lines(context.organization_id, receipt.id)

    async def _check_return_limit(
        self,
        context: TenantContext,
        value: SupplierReturn,
        lines: tuple[SupplierReturnLine, ...],
        receipt_lines: tuple[GoodsReceiptLine, ...],
    ) -> None:
        if value.goods_receipt_id is None:
            return
        received = {line.id: line for line in receipt_lines}
        returned = await self.repository.returned_totals(
            context.organization_id,
            value.goods_receipt_id,
            exclude_return_id=value.id,
        )
        for line in lines:
            source = received.get(line.goods_receipt_line_id)
            if source is None or source.inventory_item_id != line.inventory_item_id:
                raise InvalidPurchasingOperation("Return line does not match goods receipt")
            if returned.get(source.id, Decimal(0)) + line.base_quantity > source.base_quantity:
                raise InvalidPurchasingOperation("Return quantity exceeds received quantity")

    def _return_lines(
        self,
        return_id: UUID,
        values: tuple[SupplierReturnLineInput, ...],
        resources: InventoryResources,
        receipt_lines: tuple[GoodsReceiptLine, ...],
        now: datetime,
    ) -> tuple[SupplierReturnLine, ...]:
        linked = {line.id: line for line in receipt_lines}
        result = []
        for value in values:
            source = linked.get(value.goods_receipt_line_id)
            if receipt_lines:
                if source is None or source.inventory_item_id != value.inventory_item_id:
                    raise InvalidPurchasingOperation("Return line does not match goods receipt")
                quantity = _decimal(value.quantity, positive=True, label="Return quantity")
                unit, multiplier, price = (
                    source.purchase_unit,
                    source.unit_multiplier,
                    source.unit_price,
                )
            else:
                if value.goods_receipt_line_id is not None:
                    raise InvalidPurchasingOperation(
                        "Unlinked supplier return cannot reference a receipt line"
                    )
                if value.purchase_unit is None or value.unit_price is None:
                    raise InvalidPurchaseQuantity(
                        "purchase_unit and unit_price are required for unlinked returns"
                    )
                quantity, unit, multiplier, price = _line_values(
                    value.quantity,
                    value.purchase_unit,
                    value.unit_multiplier,
                    value.unit_price,
                    resources.items[value.inventory_item_id].base_unit,
                )
            result.append(
                SupplierReturnLine(
                    uuid4(),
                    return_id,
                    source.id if source else None,
                    value.inventory_item_id,
                    quantity,
                    _base_quantity(quantity, multiplier),
                    unit,
                    multiplier,
                    price,
                    _line_total_minor(quantity, price),
                    now,
                )
            )
        return tuple(result)

    async def _locked_return(self, context: TenantContext, return_id: UUID) -> SupplierReturn:
        value = await self.repository.get_return(context.organization_id, return_id, lock=True)
        if value is None:
            raise PurchasingNotFound
        await self._ensure_location(context, value.location_id)
        return value

    async def _recalculate_order(
        self, context: TenantContext, order: PurchaseOrder
    ) -> object | None:
        lines = await self.repository.get_order_lines(context.organization_id, order.id)
        received = await self.repository.received_totals(context.organization_id, order.id)
        if lines and all(received.get(line.id, Decimal(0)) >= line.base_quantity for line in lines):
            status = PurchaseOrderStatus.RECEIVED
            event: object | None = PurchaseOrderReceived(context.organization_id, order.id)
        elif any(value > 0 for value in received.values()):
            status = PurchaseOrderStatus.PARTIALLY_RECEIVED
            event = PurchaseOrderPartiallyReceived(context.organization_id, order.id)
        else:
            status = PurchaseOrderStatus.ORDERED
            event = None
        if order.status == status:
            return None
        await self.repository.update_order(
            replace(order, status=status, updated_at=datetime.now(UTC))
        )
        return event

    async def _check_over_receipt(
        self,
        context: TenantContext,
        order: PurchaseOrder,
        receipt_lines: tuple[GoodsReceiptLine, ...],
        confirmed: bool,
    ) -> None:
        ordered = {
            line.id: line
            for line in await self.repository.get_order_lines(context.organization_id, order.id)
        }
        received = await self.repository.received_totals(context.organization_id, order.id)
        for line in receipt_lines:
            order_line = ordered.get(line.purchase_order_line_id)
            if order_line is None or order_line.inventory_item_id != line.inventory_item_id:
                raise InvalidPurchasingOperation("Receipt line does not match purchase order")
            if (
                received.get(order_line.id, Decimal(0)) + line.base_quantity
                > order_line.base_quantity
                and not confirmed
            ):
                raise OverReceiptConfirmationRequired

    async def _resources(
        self,
        context: TenantContext,
        location_id: UUID,
        warehouse_id: UUID,
        item_ids: tuple[UUID, ...],
    ) -> InventoryResources:
        if not item_ids or len(set(item_ids)) != len(item_ids):
            raise InvalidPurchaseQuantity("Lines must contain unique inventory items")
        resources = await self.inventory.validate_resources(context, warehouse_id, item_ids)
        if resources.location_id != location_id:
            raise PurchasingNotFound
        return resources

    def _order_lines(
        self,
        order_id: UUID,
        values: tuple[PurchaseLineInput, ...],
        resources: InventoryResources,
        now: datetime,
    ) -> tuple[PurchaseOrderLine, ...]:
        result = []
        for value in values:
            quantity, unit, multiplier, price = _line_values(
                value.quantity,
                value.purchase_unit,
                value.unit_multiplier,
                value.unit_price,
                resources.items[value.inventory_item_id].base_unit,
            )
            result.append(
                PurchaseOrderLine(
                    uuid4(),
                    order_id,
                    value.inventory_item_id,
                    quantity,
                    _base_quantity(quantity, multiplier),
                    unit,
                    multiplier,
                    price,
                    _line_total_minor(quantity, price),
                    now,
                    now,
                )
            )
        return tuple(result)

    def _receipt_lines(
        self,
        receipt_id: UUID,
        values: tuple[ReceiptLineInput, ...],
        resources: InventoryResources,
        order_lines: tuple[PurchaseOrderLine, ...],
        now: datetime,
    ) -> tuple[GoodsReceiptLine, ...]:
        by_id = {line.id: line for line in order_lines}
        result = []
        for value in values:
            if order_lines:
                source = by_id.get(value.purchase_order_line_id)
                if source is None or source.inventory_item_id != value.inventory_item_id:
                    raise InvalidPurchasingOperation("Receipt line does not match purchase order")
            quantity, unit, multiplier, price = _line_values(
                value.quantity,
                value.purchase_unit,
                value.unit_multiplier,
                value.unit_price,
                resources.items[value.inventory_item_id].base_unit,
            )
            result.append(
                GoodsReceiptLine(
                    uuid4(),
                    receipt_id,
                    value.purchase_order_line_id,
                    value.inventory_item_id,
                    quantity,
                    _base_quantity(quantity, multiplier),
                    unit,
                    multiplier,
                    price,
                    _line_total_minor(quantity, price),
                    now,
                )
            )
        return tuple(result)

    async def _active_supplier(self, context: TenantContext, supplier_id: UUID) -> Supplier:
        supplier = await self.get_supplier(context, supplier_id)
        if not supplier.is_active:
            raise InvalidPurchasingOperation("Inactive supplier cannot be used")
        return supplier

    async def _locked_order(self, context: TenantContext, order_id: UUID) -> PurchaseOrder:
        order = await self.repository.get_order(context.organization_id, order_id, lock=True)
        if order is None:
            raise PurchasingNotFound
        await self._ensure_location(context, order.location_id)
        return order

    async def _locked_receipt(self, context: TenantContext, receipt_id: UUID) -> GoodsReceipt:
        receipt = await self.repository.get_receipt(context.organization_id, receipt_id, lock=True)
        if receipt is None:
            raise PurchasingNotFound
        await self._ensure_location(context, receipt.location_id)
        return receipt

    async def _location_ids(self, context: TenantContext) -> tuple[UUID, ...]:
        locations = await self.organizations.list_locations(
            ListLocationsQuery(context.user_id, context.organization_id)
        )
        return tuple(location.id for location in locations if location.is_active)

    async def _ensure_location(self, context: TenantContext, location_id: UUID) -> None:
        if location_id not in await self._location_ids(context):
            raise PurchasingNotFound


def _line_values(
    quantity: Decimal,
    purchase_unit: str,
    explicit_multiplier: Decimal | None,
    unit_price: Decimal,
    base_unit: str,
) -> tuple[Decimal, str, Decimal, Decimal]:
    quantity = _decimal(quantity, positive=True, label="Quantity")
    price = _decimal(unit_price, positive=False, label="Unit price")
    unit = _required_text(purchase_unit, 50, "Purchase unit").lower()
    known = _KNOWN_MULTIPLIERS.get((unit, base_unit))
    if known is None and explicit_multiplier is None:
        raise InvalidPurchaseQuantity("unit_multiplier is required for custom purchase units")
    multiplier = known or _decimal(explicit_multiplier, positive=True, label="Unit multiplier")
    return quantity, unit, multiplier, price


def _decimal(value: Decimal | None, *, positive: bool, label: str) -> Decimal:
    if value is None or not value.is_finite():
        raise InvalidPurchaseQuantity(f"{label} must be a finite decimal string")
    if value.as_tuple().exponent < -6:
        raise InvalidPurchaseQuantity(f"{label} supports at most 6 decimal places")
    if value != 0 and value.adjusted() > 13:
        raise InvalidPurchaseQuantity(f"{label} exceeds NUMERIC(20, 6)")
    if positive and value <= 0:
        raise InvalidPurchaseQuantity(f"{label} must be greater than zero")
    if not positive and value < 0:
        raise InvalidPurchaseQuantity(f"{label} cannot be negative")
    return value


def _base_quantity(quantity: Decimal, multiplier: Decimal) -> Decimal:
    value = quantity * multiplier
    if value.as_tuple().exponent < -6:
        value = value.quantize(_SIX_PLACES, rounding=ROUND_HALF_UP)
    return _decimal(value, positive=True, label="Base quantity")


def _line_total_minor(quantity: Decimal, unit_price: Decimal) -> int:
    try:
        value = int((quantity * unit_price * _MONEY_MINOR).quantize(1, rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError, OverflowError) as exc:
        raise InvalidPurchaseQuantity("Line total exceeds BIGINT") from exc
    if value > 9_223_372_036_854_775_807:
        raise InvalidPurchaseQuantity("Line total exceeds BIGINT")
    return value


def _acquisition_total(quantity: Decimal, unit_price: Decimal) -> Decimal:
    return (quantity * unit_price).quantize(_SIX_PLACES, rounding=ROUND_HALF_UP)


def _required_text(value: str, maximum: int, label: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{label} must contain between 1 and {maximum} characters")
    return normalized


def _text(value: str | None, maximum: int) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if len(normalized) > maximum:
        raise ValueError("Text is too long")
    return normalized or None


def _email(value: str | None) -> str | None:
    normalized = _text(value, 255)
    return normalized.casefold() if normalized else None
