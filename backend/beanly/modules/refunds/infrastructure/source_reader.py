from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from beanly.modules.inventory.infrastructure.db.models import InventoryTransactionLineModel
from beanly.modules.payments.infrastructure.db.models import PaymentModel
from beanly.modules.refunds.application.dto import (
    PreviewLine,
    PreviewPaymentLine,
    RefundInput,
    RefundPreview,
)
from beanly.modules.refunds.application.ports import RefundPlan, ReturnStockLine
from beanly.modules.refunds.domain.exceptions import (
    ExternalRefundNotConfirmed,
    InvalidRefund,
    OrderNotRefundable,
    RefundPaymentAmountExceeded,
    RefundQuantityExceeded,
    RefundTotalMismatch,
)
from beanly.modules.refunds.infrastructure.db.models import (
    RefundLineModel,
    RefundModel,
    RefundPaymentLineModel,
)
from beanly.modules.sales.infrastructure.db.models import SalesOrderItemModel, SalesOrderModel


class SqlAlchemyRefundSourceReader:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def payment_location(
        self, organization_id: UUID, payment_id: UUID
    ) -> UUID | None:
        return await self.session.scalar(
            select(PaymentModel.location_id).where(
                PaymentModel.organization_id == organization_id,
                PaymentModel.id == payment_id,
            )
        )

    async def lock_payment(self, organization_id: UUID, payment_id: UUID) -> UUID:
        value = await self.session.scalar(
            select(PaymentModel.location_id)
            .where(
                PaymentModel.organization_id == organization_id,
                PaymentModel.id == payment_id,
            )
            .with_for_update()
        )
        if value is None:
            raise OrderNotRefundable("Payment not found")
        return value

    async def plan(
        self,
        organization_id: UUID,
        value: RefundInput,
        *,
        lock: bool,
        require_external_confirmation: bool,
    ) -> RefundPlan:
        payment_statement = (
            select(PaymentModel)
            .options(selectinload(PaymentModel.lines))
            .where(
                PaymentModel.organization_id == organization_id, PaymentModel.id == value.payment_id
            )
        )
        if lock:
            payment_statement = payment_statement.with_for_update()
        payment = await self.session.scalar(payment_statement)
        if payment is None:
            raise OrderNotRefundable("Payment not found")
        order_statement = (
            select(SalesOrderModel)
            .options(
                selectinload(SalesOrderModel.items).selectinload(SalesOrderItemModel.components)
            )
            .where(
                SalesOrderModel.organization_id == organization_id,
                SalesOrderModel.id == payment.order_id,
            )
        )
        if lock:
            order_statement = order_statement.with_for_update()
        order = await self.session.scalar(order_statement)
        if order is None or order.status != "PAID":
            raise OrderNotRefundable("Only PAID orders can be refunded")
        if not value.lines or not value.payment_lines:
            raise InvalidRefund("Refund lines and payment lines are required")
        if len({line.order_item_id for line in value.lines}) != len(value.lines):
            raise InvalidRefund("Duplicate refund order item")
        if len({line.original_payment_line_id for line in value.payment_lines}) != len(
            value.payment_lines
        ):
            raise InvalidRefund("Duplicate refund payment line")

        item_map = {item.id: item for item in order.items}
        refunded_rows = await self.session.execute(
            select(
                RefundLineModel.order_item_id, func.coalesce(func.sum(RefundLineModel.quantity), 0)
            )
            .join(RefundModel, RefundModel.id == RefundLineModel.refund_id)
            .where(
                RefundModel.organization_id == organization_id,
                RefundModel.payment_id == payment.id,
                RefundModel.status == "COMPLETED",
            )
            .group_by(RefundLineModel.order_item_id)
        )
        refunded = {item_id: int(quantity) for item_id, quantity in refunded_rows}
        preview_lines: list[PreviewLine] = []
        for requested in value.lines:
            item = item_map.get(requested.order_item_id)
            if item is None:
                raise InvalidRefund("Refund item does not belong to the paid order")
            if requested.quantity <= 0 or not 0 <= requested.restock_quantity <= requested.quantity:
                raise InvalidRefund("Invalid refund or restock quantity")
            previous = refunded.get(item.id, 0)
            available = item.quantity - previous
            if requested.quantity > available:
                raise RefundQuantityExceeded("Refund quantity exceeds the original sale")
            preview_lines.append(
                PreviewLine(
                    item.id,
                    item.product_name,
                    item.variant_name,
                    item.quantity,
                    previous,
                    available,
                    requested.quantity,
                    requested.restock_quantity,
                    item.unit_price_minor,
                    item.unit_price_minor * requested.quantity,
                )
            )

        payment_map = {line.id: line for line in payment.lines}
        refunded_payment_rows = await self.session.execute(
            select(
                RefundPaymentLineModel.original_payment_line_id,
                func.coalesce(func.sum(RefundPaymentLineModel.amount_minor), 0),
            )
            .join(RefundModel, RefundModel.id == RefundPaymentLineModel.refund_id)
            .where(
                RefundModel.organization_id == organization_id,
                RefundModel.payment_id == payment.id,
                RefundModel.status == "COMPLETED",
            )
            .group_by(RefundPaymentLineModel.original_payment_line_id)
        )
        refunded_payments = {line_id: int(amount) for line_id, amount in refunded_payment_rows}
        preview_payments: list[PreviewPaymentLine] = []
        for requested in value.payment_lines:
            line = payment_map.get(requested.original_payment_line_id)
            if line is None:
                raise InvalidRefund("Refund payment line does not belong to the payment")
            previous = refunded_payments.get(line.id, 0)
            available = line.amount_minor - previous
            if requested.amount_minor <= 0 or requested.amount_minor > available:
                raise RefundPaymentAmountExceeded("Refund exceeds the original payment line")
            if (
                require_external_confirmation
                and line.method in {"CARD", "OTHER"}
                and not requested.external_refund_confirmed
            ):
                raise ExternalRefundNotConfirmed("External refund must be confirmed")
            preview_payments.append(
                PreviewPaymentLine(
                    line.id,
                    line.method,
                    line.amount_minor,
                    previous,
                    available,
                    requested.amount_minor,
                )
            )
        total = sum(line.total_refund_minor for line in preview_lines)
        if total <= 0 or total != sum(line.amount_minor for line in preview_payments):
            raise RefundTotalMismatch("Refund item and payment totals must match")

        costs = {}
        if order.inventory_transaction_id is not None:
            rows = await self.session.execute(
                select(
                    InventoryTransactionLineModel.inventory_item_id,
                    InventoryTransactionLineModel.unit_cost_amount,
                ).where(
                    InventoryTransactionLineModel.transaction_id == order.inventory_transaction_id
                )
            )
            costs = {item_id: cost for item_id, cost in rows if cost is not None}
        stock: dict[tuple[UUID, str], tuple[Decimal, Decimal]] = {}
        for requested in value.lines:
            if requested.restock_quantity == 0:
                continue
            item = item_map[requested.order_item_id]
            for component in item.components:
                cost = costs.get(component.inventory_item_id)
                if cost is None:
                    raise InvalidRefund("Original SALE cost snapshot is unavailable")
                key = (component.inventory_item_id, component.base_unit)
                quantity = component.quantity_per_unit * requested.restock_quantity
                previous_quantity, previous_cost = stock.get(key, (Decimal(0), Decimal(0)))
                if previous_quantity and previous_cost != cost:
                    raise InvalidRefund("Original SALE has conflicting component costs")
                stock[key] = (previous_quantity + quantity, Decimal(cost))
        return RefundPlan(
            RefundPreview(
                payment.id,
                order.id,
                payment.currency_code,
                total,
                tuple(preview_lines),
                tuple(preview_payments),
            ),
            order.location_id,
            order.warehouse_id,
            payment.currency_code,
            order.cogs_status or "INCOMPLETE",
            tuple(
                ReturnStockLine(item_id, unit, quantity, cost)
                for (item_id, unit), (quantity, cost) in sorted(
                    stock.items(), key=lambda row: str(row[0][0])
                )
            ),
        )
