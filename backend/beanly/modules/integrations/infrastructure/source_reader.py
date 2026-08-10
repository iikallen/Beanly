from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from beanly.modules.integrations.application.dto import (
    FiscalItem,
    FiscalPaymentLine,
    FiscalSaleCommand,
)
from beanly.modules.integrations.domain.exceptions import IntegrationNotFound
from beanly.modules.payments.infrastructure.db.models import PaymentModel
from beanly.modules.sales.infrastructure.db.models import SalesOrderModel


class SqlAlchemyIntegrationSourceReader:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def fiscal_sale(
        self, organization_id: UUID, payment_id: UUID
    ) -> FiscalSaleCommand:
        payment = await self.session.scalar(
            select(PaymentModel)
            .options(selectinload(PaymentModel.lines))
            .where(
                PaymentModel.id == payment_id,
                PaymentModel.organization_id == organization_id,
            )
        )
        if payment is None:
            raise IntegrationNotFound("Payment not found")
        order = await self.session.scalar(
            select(SalesOrderModel)
            .options(selectinload(SalesOrderModel.items))
            .where(
                SalesOrderModel.id == payment.order_id,
                SalesOrderModel.organization_id == organization_id,
                SalesOrderModel.status == "PAID",
            )
        )
        if order is None:
            raise IntegrationNotFound("Paid sales order not found")
        return FiscalSaleCommand(
            payment_id=payment.id,
            order_number=order.number,
            occurred_at=payment.completed_at,
            currency=payment.currency_code,
            items=tuple(
                FiscalItem(
                    name=(
                        f"{item.product_name} - {item.variant_name}"
                        if item.variant_name
                        else item.product_name
                    ),
                    quantity=item.quantity,
                    unit_price_minor=item.unit_price_minor,
                    total_minor=item.line_total_minor,
                )
                for item in order.items
            ),
            payment_lines=tuple(
                FiscalPaymentLine(method=line.method, amount_minor=line.amount_minor)
                for line in payment.lines
            ),
            total_minor=payment.amount_minor,
        )
