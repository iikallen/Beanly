from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from beanly.modules.purchasing.domain.entities import (
    GoodsReceipt,
    GoodsReceiptLine,
    PurchaseOrder,
    PurchaseOrderLine,
    Supplier,
)
from beanly.modules.purchasing.domain.enums import GoodsReceiptStatus, PurchaseOrderStatus
from beanly.modules.purchasing.infrastructure.db.mappers import (
    to_order,
    to_order_line,
    to_receipt,
    to_receipt_line,
    to_supplier,
)
from beanly.modules.purchasing.infrastructure.db.models import (
    GoodsReceiptLineModel,
    GoodsReceiptModel,
    PurchaseOrderLineModel,
    PurchaseOrderModel,
    SupplierModel,
)


class SqlAlchemyPurchasingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_supplier(self, supplier: Supplier) -> Supplier:
        model = SupplierModel(
            id=supplier.id,
            organization_id=supplier.organization_id,
            name=supplier.name,
            contact_name=supplier.contact_name,
            phone=supplier.phone,
            email=supplier.email,
            tax_id=supplier.tax_id,
            address=supplier.address,
            note=supplier.note,
            is_active=supplier.is_active,
            created_at=supplier.created_at,
            updated_at=supplier.updated_at,
        )
        self.session.add(model)
        await self.session.flush()
        return to_supplier(model)

    async def update_supplier(self, supplier: Supplier) -> Supplier:
        await self.session.execute(
            update(SupplierModel)
            .where(
                SupplierModel.organization_id == supplier.organization_id,
                SupplierModel.id == supplier.id,
            )
            .values(
                name=supplier.name,
                contact_name=supplier.contact_name,
                phone=supplier.phone,
                email=supplier.email,
                tax_id=supplier.tax_id,
                address=supplier.address,
                note=supplier.note,
                is_active=supplier.is_active,
                updated_at=supplier.updated_at,
            )
        )
        await self.session.flush()
        return supplier

    async def get_supplier(self, organization_id: UUID, supplier_id: UUID) -> Supplier | None:
        model = await self.session.scalar(
            select(SupplierModel).where(
                SupplierModel.organization_id == organization_id,
                SupplierModel.id == supplier_id,
            )
        )
        return to_supplier(model) if model else None

    async def list_suppliers(self, organization_id: UUID, include_inactive: bool) -> list[Supplier]:
        statement = select(SupplierModel).where(SupplierModel.organization_id == organization_id)
        if not include_inactive:
            statement = statement.where(SupplierModel.is_active.is_(True))
        models = await self.session.scalars(
            statement.order_by(SupplierModel.name, SupplierModel.id)
        )
        return [to_supplier(model) for model in models]

    async def next_order_number(self) -> str:
        value = await self._next_number("purchase_order_number_seq", PurchaseOrderModel)
        return f"PO-{value:06d}"

    async def next_receipt_number(self) -> str:
        value = await self._next_number("goods_receipt_number_seq", GoodsReceiptModel)
        return f"GR-{value:06d}"

    async def _next_number(self, sequence: str, model) -> int:
        if self.session.get_bind().dialect.name == "postgresql":
            value = await self.session.scalar(select(func.nextval(sequence)))
        else:
            value = (await self.session.scalar(select(func.count()).select_from(model))) + 1
        if value is None:
            raise RuntimeError("Document sequence did not return a value")
        return int(value)

    async def add_order(self, order: PurchaseOrder) -> PurchaseOrder:
        model = PurchaseOrderModel(
            id=order.id,
            organization_id=order.organization_id,
            location_id=order.location_id,
            warehouse_id=order.warehouse_id,
            supplier_id=order.supplier_id,
            number=order.number,
            status=order.status.value,
            currency_code=order.currency_code,
            ordered_at=order.ordered_at,
            expected_at=order.expected_at,
            note=order.note,
            created_by=order.created_by,
            created_at=order.created_at,
            updated_at=order.updated_at,
        )
        self.session.add(model)
        await self.session.flush()
        return to_order(model)

    async def update_order(self, order: PurchaseOrder) -> PurchaseOrder:
        await self.session.execute(
            update(PurchaseOrderModel)
            .where(
                PurchaseOrderModel.organization_id == order.organization_id,
                PurchaseOrderModel.id == order.id,
            )
            .values(
                location_id=order.location_id,
                warehouse_id=order.warehouse_id,
                supplier_id=order.supplier_id,
                status=order.status.value,
                ordered_at=order.ordered_at,
                expected_at=order.expected_at,
                note=order.note,
                updated_at=order.updated_at,
            )
        )
        await self.session.flush()
        return order

    async def get_order(
        self, organization_id: UUID, order_id: UUID, *, lock: bool = False
    ) -> PurchaseOrder | None:
        statement = select(PurchaseOrderModel).where(
            PurchaseOrderModel.organization_id == organization_id,
            PurchaseOrderModel.id == order_id,
        )
        if lock:
            statement = statement.with_for_update()
        model = await self.session.scalar(statement)
        return to_order(model) if model else None

    async def list_orders(
        self,
        organization_id: UUID,
        location_ids: tuple[UUID, ...],
        supplier_id: UUID | None,
        location_id: UUID | None,
        warehouse_id: UUID | None,
        status: PurchaseOrderStatus | None,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> list[PurchaseOrder]:
        if not location_ids:
            return []
        statement = select(PurchaseOrderModel).where(
            PurchaseOrderModel.organization_id == organization_id,
            PurchaseOrderModel.location_id.in_(location_ids),
        )
        for column, value in (
            (PurchaseOrderModel.supplier_id, supplier_id),
            (PurchaseOrderModel.location_id, location_id),
            (PurchaseOrderModel.warehouse_id, warehouse_id),
            (PurchaseOrderModel.status, status.value if status else None),
        ):
            if value is not None:
                statement = statement.where(column == value)
        if date_from is not None:
            statement = statement.where(PurchaseOrderModel.created_at >= date_from)
        if date_to is not None:
            statement = statement.where(PurchaseOrderModel.created_at <= date_to)
        models = await self.session.scalars(
            statement.order_by(PurchaseOrderModel.created_at.desc(), PurchaseOrderModel.id)
        )
        return [to_order(model) for model in models]

    async def add_order_lines(self, lines: tuple[PurchaseOrderLine, ...]) -> None:
        self.session.add_all(
            PurchaseOrderLineModel(
                id=line.id,
                purchase_order_id=line.purchase_order_id,
                inventory_item_id=line.inventory_item_id,
                ordered_quantity=line.ordered_quantity,
                base_quantity=line.base_quantity,
                purchase_unit=line.purchase_unit,
                unit_multiplier=line.unit_multiplier,
                unit_price=line.unit_price,
                line_total_minor=line.line_total_minor,
                created_at=line.created_at,
                updated_at=line.updated_at,
            )
            for line in lines
        )
        await self.session.flush()

    async def replace_order_lines(
        self,
        organization_id: UUID,
        order_id: UUID,
        lines: tuple[PurchaseOrderLine, ...],
    ) -> None:
        owned_order = select(PurchaseOrderModel.id).where(
            PurchaseOrderModel.organization_id == organization_id,
            PurchaseOrderModel.id == order_id,
        )
        await self.session.execute(
            delete(PurchaseOrderLineModel).where(
                PurchaseOrderLineModel.purchase_order_id.in_(owned_order)
            )
        )
        await self.add_order_lines(lines)

    async def get_order_lines(
        self, organization_id: UUID, order_id: UUID
    ) -> tuple[PurchaseOrderLine, ...]:
        models = await self.session.scalars(
            select(PurchaseOrderLineModel)
            .join(PurchaseOrderModel)
            .where(
                PurchaseOrderModel.organization_id == organization_id,
                PurchaseOrderLineModel.purchase_order_id == order_id,
            )
            .order_by(PurchaseOrderLineModel.created_at, PurchaseOrderLineModel.id)
        )
        return tuple(to_order_line(model) for model in models)

    async def received_totals(self, organization_id: UUID, order_id: UUID) -> dict[UUID, Decimal]:
        rows = (
            await self.session.execute(
                select(
                    GoodsReceiptLineModel.purchase_order_line_id,
                    func.sum(GoodsReceiptLineModel.base_quantity),
                )
                .join(GoodsReceiptModel)
                .where(
                    GoodsReceiptModel.organization_id == organization_id,
                    GoodsReceiptModel.purchase_order_id == order_id,
                    GoodsReceiptModel.status == GoodsReceiptStatus.POSTED.value,
                    GoodsReceiptLineModel.purchase_order_line_id.is_not(None),
                )
                .group_by(GoodsReceiptLineModel.purchase_order_line_id)
            )
        ).all()
        return {line_id: total for line_id, total in rows if line_id is not None}

    async def add_receipt(self, receipt: GoodsReceipt) -> GoodsReceipt:
        model = GoodsReceiptModel(
            id=receipt.id,
            organization_id=receipt.organization_id,
            location_id=receipt.location_id,
            warehouse_id=receipt.warehouse_id,
            purchase_order_id=receipt.purchase_order_id,
            supplier_id=receipt.supplier_id,
            number=receipt.number,
            status=receipt.status.value,
            document_number=receipt.document_number,
            received_at=receipt.received_at,
            note=receipt.note,
            created_by=receipt.created_by,
            created_at=receipt.created_at,
            updated_at=receipt.updated_at,
            posted_by=receipt.posted_by,
            posted_at=receipt.posted_at,
            reversed_by=receipt.reversed_by,
            reversed_at=receipt.reversed_at,
            inventory_transaction_id=receipt.inventory_transaction_id,
        )
        self.session.add(model)
        await self.session.flush()
        return to_receipt(model)

    async def update_receipt(self, receipt: GoodsReceipt) -> GoodsReceipt:
        await self.session.execute(
            update(GoodsReceiptModel)
            .where(
                GoodsReceiptModel.organization_id == receipt.organization_id,
                GoodsReceiptModel.id == receipt.id,
            )
            .values(
                location_id=receipt.location_id,
                warehouse_id=receipt.warehouse_id,
                supplier_id=receipt.supplier_id,
                status=receipt.status.value,
                document_number=receipt.document_number,
                received_at=receipt.received_at,
                note=receipt.note,
                updated_at=receipt.updated_at,
                posted_by=receipt.posted_by,
                posted_at=receipt.posted_at,
                reversed_by=receipt.reversed_by,
                reversed_at=receipt.reversed_at,
                inventory_transaction_id=receipt.inventory_transaction_id,
            )
        )
        await self.session.flush()
        return receipt

    async def get_receipt(
        self, organization_id: UUID, receipt_id: UUID, *, lock: bool = False
    ) -> GoodsReceipt | None:
        statement = select(GoodsReceiptModel).where(
            GoodsReceiptModel.organization_id == organization_id,
            GoodsReceiptModel.id == receipt_id,
        )
        if lock:
            statement = statement.with_for_update()
        model = await self.session.scalar(statement)
        return to_receipt(model) if model else None

    async def list_receipts(
        self,
        organization_id: UUID,
        location_ids: tuple[UUID, ...],
        purchase_order_id: UUID | None,
        supplier_id: UUID | None,
        status: GoodsReceiptStatus | None,
    ) -> list[GoodsReceipt]:
        if not location_ids:
            return []
        statement = select(GoodsReceiptModel).where(
            GoodsReceiptModel.organization_id == organization_id,
            GoodsReceiptModel.location_id.in_(location_ids),
        )
        for column, value in (
            (GoodsReceiptModel.purchase_order_id, purchase_order_id),
            (GoodsReceiptModel.supplier_id, supplier_id),
            (GoodsReceiptModel.status, status.value if status else None),
        ):
            if value is not None:
                statement = statement.where(column == value)
        models = await self.session.scalars(
            statement.order_by(GoodsReceiptModel.received_at.desc(), GoodsReceiptModel.id)
        )
        return [to_receipt(model) for model in models]

    async def add_receipt_lines(self, lines: tuple[GoodsReceiptLine, ...]) -> None:
        self.session.add_all(
            GoodsReceiptLineModel(
                id=line.id,
                goods_receipt_id=line.goods_receipt_id,
                purchase_order_line_id=line.purchase_order_line_id,
                inventory_item_id=line.inventory_item_id,
                received_quantity=line.received_quantity,
                base_quantity=line.base_quantity,
                purchase_unit=line.purchase_unit,
                unit_multiplier=line.unit_multiplier,
                unit_price=line.unit_price,
                line_total_minor=line.line_total_minor,
                created_at=line.created_at,
            )
            for line in lines
        )
        await self.session.flush()

    async def replace_receipt_lines(
        self,
        organization_id: UUID,
        receipt_id: UUID,
        lines: tuple[GoodsReceiptLine, ...],
    ) -> None:
        owned = select(GoodsReceiptModel.id).where(
            GoodsReceiptModel.organization_id == organization_id,
            GoodsReceiptModel.id == receipt_id,
        )
        await self.session.execute(
            delete(GoodsReceiptLineModel).where(GoodsReceiptLineModel.goods_receipt_id.in_(owned))
        )
        await self.add_receipt_lines(lines)

    async def get_receipt_lines(
        self, organization_id: UUID, receipt_id: UUID
    ) -> tuple[GoodsReceiptLine, ...]:
        models = await self.session.scalars(
            select(GoodsReceiptLineModel)
            .join(GoodsReceiptModel)
            .where(
                GoodsReceiptModel.organization_id == organization_id,
                GoodsReceiptLineModel.goods_receipt_id == receipt_id,
            )
            .order_by(GoodsReceiptLineModel.created_at, GoodsReceiptLineModel.id)
        )
        return tuple(to_receipt_line(model) for model in models)

    async def posted_receipt_count(self, organization_id: UUID, order_id: UUID) -> int:
        value = await self.session.scalar(
            select(func.count())
            .select_from(GoodsReceiptModel)
            .where(
                GoodsReceiptModel.organization_id == organization_id,
                GoodsReceiptModel.purchase_order_id == order_id,
                GoodsReceiptModel.status == GoodsReceiptStatus.POSTED.value,
            )
        )
        return int(value or 0)

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()
