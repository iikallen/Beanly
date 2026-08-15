from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from beanly.modules.integrations.infrastructure.db.models import IntegrationJobModel
from beanly.modules.promotions.application.pricing_engine import largest_remainder_allocate
from beanly.modules.promotions.infrastructure.db.models import (
    SalesOrderDiscountAllocationModel,
)
from beanly.modules.refunds.domain.entities import Refund
from beanly.modules.refunds.domain.exceptions import RefundConflict
from beanly.modules.refunds.infrastructure.db.mappers import to_refund
from beanly.modules.refunds.infrastructure.db.models import (
    RefundDiscountAllocationModel,
    RefundLineModel,
    RefundModel,
    RefundPaymentLineModel,
)


class SqlAlchemyRefundRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, organization_id: UUID, refund_id: UUID) -> Refund | None:
        value = await self.session.scalar(
            _query(organization_id).where(RefundModel.id == refund_id)
        )
        return to_refund(value) if value else None

    async def get_by_client_id(
        self, organization_id: UUID, client_refund_id: UUID
    ) -> Refund | None:
        value = await self.session.scalar(
            _query(organization_id).where(RefundModel.client_refund_id == client_refund_id)
        )
        return to_refund(value) if value else None

    async def add(self, value: Refund) -> Refund:
        try:
            model = await self.session.get(RefundModel, value.id)
            if model is None:
                model = RefundModel(
                    id=value.id,
                    organization_id=value.organization_id,
                    location_id=value.location_id,
                    order_id=value.order_id,
                    payment_id=value.payment_id,
                    client_refund_id=value.client_refund_id,
                    status=value.status.value,
                    reason=value.reason.value,
                    note=value.note,
                    currency_code=value.currency_code,
                    total_amount_minor=value.total_amount_minor,
                    fulfillment_fee_minor=value.fulfillment_fee_minor,
                    inventory_transaction_id=value.inventory_transaction_id,
                    cogs_reversal_amount=value.cogs_reversal_amount,
                    cogs_quality_status=value.cogs_quality_status,
                    created_by_user_id=value.created_by_user_id,
                    created_at=value.created_at,
                    completed_by_user_id=value.completed_by_user_id,
                    completed_at=value.completed_at,
                    failed_at=value.failed_at,
                    failure_code=value.failure_code,
                    lines=[
                        RefundLineModel(
                            **{
                                "id": line.id,
                                "refund_id": line.refund_id,
                                "order_item_id": line.order_item_id,
                                "quantity": line.quantity,
                                "restock_quantity": line.restock_quantity,
                                "unit_refund_minor": line.unit_refund_minor,
                                "total_refund_minor": line.total_refund_minor,
                                "gross_refund_minor": line.gross_refund_minor,
                                "discount_refund_minor": line.discount_refund_minor,
                                "net_refund_minor": line.net_refund_minor,
                                "created_at": line.created_at,
                            }
                        )
                        for line in value.lines
                    ],
                    payment_lines=[
                        RefundPaymentLineModel(
                            **{
                                "id": line.id,
                                "refund_id": line.refund_id,
                                "original_payment_line_id": line.original_payment_line_id,
                                "method": line.method,
                                "amount_minor": line.amount_minor,
                                "external_refund_confirmed": line.external_refund_confirmed,
                                "reference": line.reference,
                                "created_at": line.created_at,
                            }
                        )
                        for line in value.payment_lines
                    ],
                )
                self.session.add(model)
                await self.session.flush()
                await self._add_discount_allocations(value)
            else:
                model.status = value.status.value
                model.inventory_transaction_id = value.inventory_transaction_id
                model.cogs_reversal_amount = value.cogs_reversal_amount
                model.cogs_quality_status = value.cogs_quality_status
                model.completed_by_user_id = value.completed_by_user_id
                model.completed_at = value.completed_at
                model.failed_at = value.failed_at
                model.failure_code = value.failure_code
            await self.session.flush()
        except IntegrityError as exc:
            raise RefundConflict("Refund persistence conflict") from exc
        return value

    async def _add_discount_allocations(self, value: Refund) -> None:
        for line in value.lines:
            if line.discount_refund_minor == 0:
                continue
            rows = list(
                await self.session.execute(
                    select(
                        SalesOrderDiscountAllocationModel.order_discount_id,
                        SalesOrderDiscountAllocationModel.discount_amount_minor,
                    )
                    .where(SalesOrderDiscountAllocationModel.order_item_id == line.order_item_id)
                    .order_by(
                        SalesOrderDiscountAllocationModel.sort_order,
                        SalesOrderDiscountAllocationModel.order_discount_id,
                    )
                )
            )
            if not rows:
                raise RefundConflict("Refund discount has no order allocation")
            existing_rows = list(
                await self.session.execute(
                    select(
                        RefundDiscountAllocationModel.order_discount_id,
                        func.sum(RefundDiscountAllocationModel.discount_amount_minor),
                    )
                    .join(
                        RefundLineModel,
                        RefundLineModel.id == RefundDiscountAllocationModel.refund_line_id,
                    )
                    .join(RefundModel, RefundModel.id == RefundLineModel.refund_id)
                    .where(
                        RefundLineModel.order_item_id == line.order_item_id,
                        RefundModel.status == "COMPLETED",
                    )
                    .group_by(RefundDiscountAllocationModel.order_discount_id)
                )
            )
            existing = {discount_id: int(amount) for discount_id, amount in existing_rows}
            cumulative = sum(existing.values()) + line.discount_refund_minor
            desired = largest_remainder_allocate(cumulative, tuple(rows))
            for discount_id, amount in desired.items():
                delta = amount - existing.get(discount_id, 0)
                if delta > 0:
                    self.session.add(
                        RefundDiscountAllocationModel(
                            id=uuid4(),
                            refund_line_id=line.id,
                            order_discount_id=discount_id,
                            discount_amount_minor=delta,
                        )
                    )

    async def list(self, organization_id: UUID, **filters) -> list[Refund]:
        statement = _query(organization_id)
        location_ids = filters.get("location_ids", ())
        if not location_ids:
            return []
        statement = statement.where(RefundModel.location_id.in_(location_ids))
        for field in ("location_id", "order_id", "payment_id", "status"):
            value = filters.get(field)
            if value is not None:
                statement = statement.where(
                    getattr(RefundModel, field) == getattr(value, "value", value)
                )
        if filters.get("date_from") is not None:
            statement = statement.where(RefundModel.created_at >= filters["date_from"])
        if filters.get("date_to") is not None:
            statement = statement.where(RefundModel.created_at <= filters["date_to"])
        values = await self.session.scalars(
            statement.order_by(RefundModel.created_at.desc(), RefundModel.id)
        )
        return [to_refund(value) for value in values.unique()]

    async def fiscal_status(self, organization_id: UUID, refund_id: UUID):
        job = await self.session.scalar(
            select(IntegrationJobModel)
            .where(
                IntegrationJobModel.organization_id == organization_id,
                IntegrationJobModel.source_type == "REFUND",
                IntegrationJobModel.source_id == refund_id,
                IntegrationJobModel.job_type == "FISCALIZE_REFUND",
            )
            .order_by(IntegrationJobModel.created_at.desc())
        )
        if job is None:
            return "NOT_CONFIGURED", None, None
        return job.status, job.external_number, job.external_url

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()

    async def dashboard_summary(
        self,
        organization_id: UUID,
        location_ids: tuple[UUID, ...],
        date_from: datetime,
        date_to: datetime,
    ) -> int:
        value = await self.session.scalar(
            select(func.coalesce(func.sum(RefundModel.total_amount_minor), 0)).where(
                *_dashboard_filters(organization_id, location_ids, date_from, date_to)
            )
        )
        return int(value or 0)

    async def dashboard_trend(
        self,
        organization_id: UUID,
        location_ids: tuple[UUID, ...],
        buckets: tuple[tuple[datetime, datetime], ...],
    ) -> tuple[int, ...]:
        if not buckets:
            return ()
        columns = tuple(
            func.coalesce(
                func.sum(
                    case(
                        (
                            (RefundModel.completed_at >= date_from)
                            & (RefundModel.completed_at < date_to),
                            RefundModel.total_amount_minor,
                        ),
                        else_=0,
                    )
                ),
                0,
            )
            for date_from, date_to in buckets
        )
        row = (
            await self.session.execute(
                select(*columns).where(
                    RefundModel.organization_id == organization_id,
                    RefundModel.location_id.in_(location_ids),
                    RefundModel.status == "COMPLETED",
                    RefundModel.completed_at >= buckets[0][0],
                    RefundModel.completed_at < buckets[-1][1],
                )
            )
        ).one()
        return tuple(int(value or 0) for value in row)

    async def dashboard_locations(
        self,
        organization_id: UUID,
        location_ids: tuple[UUID, ...],
        date_from: datetime,
        date_to: datetime,
    ) -> tuple[tuple[UUID, int], ...]:
        rows = (
            await self.session.execute(
                select(
                    RefundModel.location_id,
                    func.coalesce(func.sum(RefundModel.total_amount_minor), 0),
                )
                .where(*_dashboard_filters(organization_id, location_ids, date_from, date_to))
                .group_by(RefundModel.location_id)
            )
        ).all()
        return tuple((location_id, int(amount or 0)) for location_id, amount in rows)


def _query(organization_id: UUID):
    return (
        select(RefundModel)
        .where(RefundModel.organization_id == organization_id)
        .options(selectinload(RefundModel.lines), selectinload(RefundModel.payment_lines))
        .execution_options(populate_existing=True)
    )


def _dashboard_filters(
    organization_id: UUID,
    location_ids: tuple[UUID, ...],
    date_from: datetime,
    date_to: datetime,
) -> tuple[object, ...]:
    return (
        RefundModel.organization_id == organization_id,
        RefundModel.location_id.in_(location_ids),
        RefundModel.status == "COMPLETED",
        RefundModel.completed_at >= date_from,
        RefundModel.completed_at < date_to,
    )
