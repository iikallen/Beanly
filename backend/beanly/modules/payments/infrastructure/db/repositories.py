from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from beanly.modules.payments.domain.entities import (
    Payment,
    PaymentMethodTotal,
    ShiftPaymentSummary,
)
from beanly.modules.payments.domain.enums import PaymentMethod
from beanly.modules.payments.domain.exceptions import PaymentConflict
from beanly.modules.payments.infrastructure.db.mappers import to_payment
from beanly.modules.payments.infrastructure.db.models import (
    PaymentLineModel,
    PaymentModel,
)


class SqlAlchemyPaymentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, value: Payment) -> Payment:
        model = PaymentModel(**_payment_values(value))
        model.lines = [PaymentLineModel(**_line_values(line)) for line in value.lines]
        self.session.add(model)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise PaymentConflict("Payment already exists") from exc
        return to_payment(model)

    async def get(
        self, organization_id: UUID, payment_id: UUID
    ) -> Payment | None:
        model = await self.session.scalar(
            _payment_query(organization_id).where(PaymentModel.id == payment_id)
        )
        return to_payment(model) if model else None

    async def get_by_order(
        self, organization_id: UUID, order_id: UUID
    ) -> Payment | None:
        model = await self.session.scalar(
            _payment_query(organization_id).where(PaymentModel.order_id == order_id)
        )
        return to_payment(model) if model else None

    async def get_by_client_id(
        self, organization_id: UUID, client_payment_id: UUID
    ) -> Payment | None:
        model = await self.session.scalar(
            _payment_query(organization_id).where(
                PaymentModel.client_payment_id == client_payment_id
            )
        )
        return to_payment(model) if model else None

    async def list(
        self,
        organization_id: UUID,
        location_ids: tuple[UUID, ...],
        *,
        shift_id: UUID | None,
        date_from: datetime | None,
        date_to: datetime | None,
        method: PaymentMethod | None,
    ) -> list[Payment]:
        if not location_ids:
            return []
        statement = _payment_query(organization_id).where(
            PaymentModel.location_id.in_(location_ids)
        )
        if shift_id is not None:
            statement = statement.where(PaymentModel.shift_id == shift_id)
        if date_from is not None:
            statement = statement.where(PaymentModel.completed_at >= date_from)
        if date_to is not None:
            statement = statement.where(PaymentModel.completed_at <= date_to)
        if method is not None:
            statement = statement.where(
                PaymentModel.id.in_(
                    select(PaymentLineModel.payment_id).where(
                        PaymentLineModel.method == method.value
                    )
                )
            )
        models = await self.session.scalars(
            statement.order_by(PaymentModel.completed_at.desc(), PaymentModel.id)
        )
        return [to_payment(model) for model in models]

    async def shift_summary(
        self, organization_id: UUID, shift_id: UUID
    ) -> ShiftPaymentSummary:
        totals = await self.session.execute(
            select(
                func.count(PaymentModel.id),
                func.coalesce(func.sum(PaymentModel.amount_minor), 0),
            ).where(
                PaymentModel.organization_id == organization_id,
                PaymentModel.shift_id == shift_id,
            )
        )
        orders_paid, gross_amount_minor = totals.one()
        method_rows = await self.session.execute(
            select(
                PaymentLineModel.method,
                func.coalesce(func.sum(PaymentLineModel.amount_minor), 0),
            )
            .join(PaymentModel, PaymentModel.id == PaymentLineModel.payment_id)
            .where(
                PaymentModel.organization_id == organization_id,
                PaymentModel.shift_id == shift_id,
            )
            .group_by(PaymentLineModel.method)
        )
        by_method = {PaymentMethod(method): int(amount) for method, amount in method_rows}
        return ShiftPaymentSummary(
            int(orders_paid),
            int(gross_amount_minor),
            tuple(
                PaymentMethodTotal(method, by_method[method])
                for method in PaymentMethod
                if method in by_method
            ),
        )

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()


def _payment_query(organization_id: UUID):
    return (
        select(PaymentModel)
        .where(PaymentModel.organization_id == organization_id)
        .options(selectinload(PaymentModel.lines))
        .execution_options(populate_existing=True)
    )


def _payment_values(value: Payment) -> dict[str, object]:
    return {
        "id": value.id,
        "organization_id": value.organization_id,
        "location_id": value.location_id,
        "order_id": value.order_id,
        "shift_id": value.shift_id,
        "client_payment_id": value.client_payment_id,
        "currency_code": value.currency_code,
        "amount_minor": value.amount_minor,
        "created_by_user_id": value.created_by_user_id,
        "completed_at": value.completed_at,
        "created_at": value.created_at,
        "updated_at": value.updated_at,
    }


def _line_values(value) -> dict[str, object]:
    return {
        "id": value.id,
        "payment_id": value.payment_id,
        "method": value.method.value,
        "amount_minor": value.amount_minor,
        "cash_received_minor": value.cash_received_minor,
        "change_minor": value.change_minor,
        "reference": value.reference,
        "sort_order": value.sort_order,
        "created_at": value.created_at,
    }
