from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from beanly.modules.fiscal.domain.tax import vat_minor
from beanly.modules.fiscal.infrastructure.db.models import (
    FiscalSaleSnapshotLineModel,
    FiscalSaleSnapshotModel,
)
from beanly.modules.integrations.application.dto import (
    FiscalItem,
    FiscalPaymentLine,
    FiscalRefundCommand,
    FiscalSaleCommand,
)
from beanly.modules.integrations.domain.exceptions import (
    FiscalOriginalReceiptPending,
    IntegrationNotFound,
)
from beanly.modules.integrations.infrastructure.db.models import IntegrationJobModel
from beanly.modules.payments.infrastructure.db.models import PaymentModel
from beanly.modules.refunds.infrastructure.db.models import RefundModel
from beanly.modules.sales.infrastructure.db.models import SalesOrderModel


class SqlAlchemyIntegrationSourceReader:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def fiscal_sale(self, organization_id: UUID, payment_id: UUID) -> FiscalSaleCommand:
        snapshot = await self.session.scalar(
            select(FiscalSaleSnapshotModel)
            .options(selectinload(FiscalSaleSnapshotModel.lines))
            .where(
                FiscalSaleSnapshotModel.organization_id == organization_id,
                FiscalSaleSnapshotModel.payment_id == payment_id,
            )
        )
        if snapshot is None:
            raise IntegrationNotFound("Fiscal sale snapshot not found")
        payment = await self.session.scalar(
            select(PaymentModel)
            .options(selectinload(PaymentModel.lines))
            .where(
                PaymentModel.organization_id == organization_id,
                PaymentModel.id == payment_id,
            )
        )
        order_number = await self.session.scalar(
            select(SalesOrderModel.number).where(
                SalesOrderModel.organization_id == organization_id,
                SalesOrderModel.id == snapshot.order_id,
                SalesOrderModel.status == "PAID",
            )
        )
        if payment is None or order_number is None:
            raise IntegrationNotFound("Paid fiscal source not found")
        return FiscalSaleCommand(
            payment_id=payment.id,
            order_number=order_number,
            occurred_at=snapshot.occurred_at,
            currency=snapshot.currency_code,
            items=tuple(_item(line) for line in snapshot.lines),
            payment_lines=tuple(
                FiscalPaymentLine(method=line.method, amount_minor=line.amount_minor)
                for line in payment.lines
            ),
            total_minor=snapshot.total_minor,
            discount_total_minor=snapshot.discount_total_minor,
        )

    async def fiscal_refund(
        self, organization_id: UUID, refund_id: UUID, connection_id: UUID
    ) -> FiscalRefundCommand:
        refund = await self.session.scalar(
            select(RefundModel)
            .options(selectinload(RefundModel.lines), selectinload(RefundModel.payment_lines))
            .where(
                RefundModel.organization_id == organization_id,
                RefundModel.id == refund_id,
                RefundModel.status == "COMPLETED",
            )
        )
        if refund is None or refund.completed_at is None:
            raise IntegrationNotFound("Completed refund not found")
        snapshot = await self.session.scalar(
            select(FiscalSaleSnapshotModel)
            .options(selectinload(FiscalSaleSnapshotModel.lines))
            .where(
                FiscalSaleSnapshotModel.organization_id == organization_id,
                FiscalSaleSnapshotModel.payment_id == refund.payment_id,
            )
        )
        if snapshot is None:
            raise IntegrationNotFound("Original fiscal snapshot not found")
        external_id = await self.session.scalar(
            select(IntegrationJobModel.external_id).where(
                IntegrationJobModel.organization_id == organization_id,
                IntegrationJobModel.connection_id == connection_id,
                IntegrationJobModel.job_type == "FISCALIZE_PAYMENT",
                IntegrationJobModel.source_type == "PAYMENT",
                IntegrationJobModel.source_id == refund.payment_id,
                IntegrationJobModel.status == "SUCCESS",
            )
        )
        if external_id is None:
            raise FiscalOriginalReceiptPending
        snapshot_lines = {line.order_item_id: line for line in snapshot.lines}
        items = []
        for line in refund.lines:
            original = snapshot_lines.get(line.order_item_id)
            if original is None:
                raise IntegrationNotFound("Refund fiscal item snapshot not found")
            vat = vat_minor(line.total_refund_minor, original.vat_rate)
            items.append(
                FiscalItem(
                    fiscal_name=original.fiscal_name,
                    quantity=line.quantity,
                    unit_price_minor=line.unit_refund_minor,
                    total_minor=line.total_refund_minor,
                    gross_total_minor=line.gross_refund_minor,
                    discount_minor=line.discount_refund_minor,
                    nkt_code=original.nkt_code,
                    nkt_code_type=original.nkt_code_type,
                    unit_code=original.unit_code,
                    vat_rate=original.vat_rate,
                    vat_amount_minor=vat,
                    marking_codes=tuple(original.marking_codes),
                )
            )
        return FiscalRefundCommand(
            refund.id,
            refund.payment_id,
            external_id,
            refund.completed_at,
            refund.currency_code,
            tuple(items),
            tuple(
                FiscalPaymentLine(line.method, line.amount_minor) for line in refund.payment_lines
            ),
            refund.total_amount_minor,
            refund.reason,
            sum(line.gross_refund_minor for line in refund.lines),
            sum(line.discount_refund_minor for line in refund.lines),
        )


def _item(line: FiscalSaleSnapshotLineModel) -> FiscalItem:
    return FiscalItem(
        fiscal_name=line.fiscal_name,
        quantity=line.quantity,
        unit_price_minor=line.unit_price_minor,
        total_minor=line.total_minor,
        gross_total_minor=line.gross_total_minor,
        discount_minor=line.discount_minor,
        nkt_code=line.nkt_code,
        nkt_code_type=line.nkt_code_type,
        unit_code=line.unit_code,
        vat_rate=line.vat_rate,
        vat_amount_minor=line.vat_amount_minor,
        marking_codes=tuple(line.marking_codes),
    )
