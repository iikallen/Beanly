from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from beanly.modules.finance.application.source_ports import (
    FinanceCountSnapshot,
    FinancePaymentLineSnapshot,
    FinancePaymentSnapshot,
    FinanceRefundPaymentLineSnapshot,
    FinanceRefundSnapshot,
    FinanceSaleSnapshot,
    FinanceWriteOffSnapshot,
)
from beanly.modules.finance.domain.exceptions import FinanceNotFound
from beanly.modules.inventory.infrastructure.db.models import (
    InventoryCountLineModel,
    InventoryCountModel,
    WriteOffModel,
)
from beanly.modules.payments.infrastructure.db.models import PaymentModel
from beanly.modules.refunds.infrastructure.db.models import RefundModel
from beanly.modules.sales.infrastructure.db.models import SalesOrderModel


class SqlAlchemyFinanceSourceReader:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def refund(self, organization_id: UUID, refund_id: UUID) -> FinanceRefundSnapshot:
        value = await self.session.scalar(
            select(RefundModel)
            .options(selectinload(RefundModel.payment_lines))
            .where(
                RefundModel.organization_id == organization_id,
                RefundModel.id == refund_id,
                RefundModel.status == "COMPLETED",
            )
        )
        if value is None or value.completed_at is None:
            raise FinanceNotFound("Completed refund not found")
        return FinanceRefundSnapshot(
            value.id,
            value.organization_id,
            value.location_id,
            value.currency_code,
            value.total_amount_minor,
            value.cogs_reversal_amount,
            value.cogs_quality_status,
            value.completed_at,
            tuple(
                FinanceRefundPaymentLineSnapshot(line.id, line.method, line.amount_minor)
                for line in value.payment_lines
            ),
        )

    async def payment(self, organization_id: UUID, payment_id: UUID) -> FinancePaymentSnapshot:
        model = await self.session.scalar(
            select(PaymentModel)
            .options(selectinload(PaymentModel.lines))
            .where(
                PaymentModel.organization_id == organization_id,
                PaymentModel.id == payment_id,
            )
        )
        if model is None:
            raise FinanceNotFound("Payment not found")
        return FinancePaymentSnapshot(
            model.id,
            model.order_id,
            model.organization_id,
            model.location_id,
            model.currency_code,
            model.amount_minor,
            model.completed_at,
            tuple(
                FinancePaymentLineSnapshot(line.id, line.method, line.amount_minor)
                for line in sorted(model.lines, key=lambda value: value.sort_order)
            ),
        )

    async def sale(self, organization_id: UUID, order_id: UUID) -> FinanceSaleSnapshot:
        model = await self.session.scalar(
            select(SalesOrderModel).where(
                SalesOrderModel.organization_id == organization_id,
                SalesOrderModel.id == order_id,
                SalesOrderModel.status == "PAID",
            )
        )
        if model is None or model.paid_at is None:
            raise FinanceNotFound("Paid sale not found")
        return FinanceSaleSnapshot(
            model.id,
            model.organization_id,
            model.location_id,
            model.currency_code,
            model.cogs_amount or Decimal(0),
            model.cogs_status or "INCOMPLETE",
            model.paid_at,
            model.subtotal_minor,
            model.discount_total_minor,
        )

    async def writeoff(self, organization_id: UUID, writeoff_id: UUID) -> FinanceWriteOffSnapshot:
        model = await self.session.scalar(
            select(WriteOffModel).where(
                WriteOffModel.organization_id == organization_id,
                WriteOffModel.id == writeoff_id,
                WriteOffModel.status.in_(("POSTED", "REVERSED")),
            )
        )
        if model is None or model.posted_at is None or model.total_cost_amount is None:
            raise FinanceNotFound("Posted inventory write-off not found")
        return FinanceWriteOffSnapshot(
            model.id,
            model.organization_id,
            model.location_id,
            model.total_cost_amount,
            model.posted_at,
            model.status,
            model.reversed_at,
        )

    async def count(self, organization_id: UUID, inventory_count_id: UUID) -> FinanceCountSnapshot:
        count = await self.session.scalar(
            select(InventoryCountModel).where(
                InventoryCountModel.organization_id == organization_id,
                InventoryCountModel.id == inventory_count_id,
                InventoryCountModel.status == "POSTED",
            )
        )
        if count is None or count.posted_at is None:
            raise FinanceNotFound("Posted inventory count not found")
        costs = await self.session.scalars(
            select(InventoryCountLineModel.difference_cost_amount).where(
                InventoryCountLineModel.inventory_count_id == inventory_count_id,
                InventoryCountLineModel.difference_cost_amount.is_not(None),
            )
        )
        loss = Decimal(0)
        gain = Decimal(0)
        for value in costs:
            if value < 0:
                loss += -value
            elif value > 0:
                gain += value
        return FinanceCountSnapshot(
            count.id,
            count.organization_id,
            count.location_id,
            count.posted_at,
            loss,
            gain,
        )

    async def paid_payment_ids(self) -> tuple[tuple[UUID, UUID], ...]:
        rows = await self.session.execute(
            select(PaymentModel.organization_id, PaymentModel.id).order_by(PaymentModel.id)
        )
        return tuple(rows)

    async def posted_writeoff_ids(self) -> tuple[tuple[UUID, UUID], ...]:
        rows = await self.session.execute(
            select(WriteOffModel.organization_id, WriteOffModel.id)
            .where(WriteOffModel.status.in_(("POSTED", "REVERSED")))
            .order_by(WriteOffModel.id)
        )
        return tuple(rows)

    async def posted_count_ids(self) -> tuple[tuple[UUID, UUID], ...]:
        rows = await self.session.execute(
            select(InventoryCountModel.organization_id, InventoryCountModel.id)
            .where(InventoryCountModel.status == "POSTED")
            .order_by(InventoryCountModel.id)
        )
        return tuple(rows)
