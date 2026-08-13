from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from beanly.modules.analytics.application.source_ports import (
    AnalyticsBackfillSource,
    AnalyticsExpenseSnapshot,
    AnalyticsInventoryLineSnapshot,
    AnalyticsInventorySnapshot,
    AnalyticsPromotionSnapshot,
    AnalyticsRefundItemSnapshot,
    AnalyticsRefundSnapshot,
    AnalyticsSaleComponentSnapshot,
    AnalyticsSaleItemSnapshot,
    AnalyticsSaleSnapshot,
)
from beanly.modules.analytics.domain.exceptions import AnalyticsProjectionError
from beanly.modules.finance.infrastructure.db.models import ExpenseModel
from beanly.modules.inventory.infrastructure.db.models import (
    InventoryItemModel,
    InventoryTransactionLineModel,
    InventoryTransactionModel,
)
from beanly.modules.organizations.infrastructure.db.models import LocationModel
from beanly.modules.payments.infrastructure.db.models import PaymentModel
from beanly.modules.promotions.infrastructure.db.models import (
    SalesOrderDiscountAllocationModel,
    SalesOrderDiscountModel,
)
from beanly.modules.refunds.infrastructure.db.models import (
    RefundDiscountAllocationModel,
    RefundLineModel,
    RefundModel,
)
from beanly.modules.sales.infrastructure.db.models import (
    SalesOrderItemModel,
    SalesOrderModel,
)


class SqlAlchemyAnalyticsSourceReader:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def refund(self, organization_id: UUID, refund_id: UUID) -> AnalyticsRefundSnapshot:
        refund = await self.session.scalar(
            select(RefundModel)
            .options(selectinload(RefundModel.lines))
            .where(
                RefundModel.organization_id == organization_id,
                RefundModel.id == refund_id,
                RefundModel.status == "COMPLETED",
            )
        )
        if refund is None or refund.completed_at is None:
            raise AnalyticsProjectionError("Completed refund not found")
        item_ids = [line.order_item_id for line in refund.lines]
        items = {
            item.id: item
            for item in await self.session.scalars(
                select(SalesOrderItemModel).where(
                    SalesOrderItemModel.order_id == refund.order_id,
                    SalesOrderItemModel.id.in_(item_ids),
                )
            )
        }
        if len(items) != len(item_ids):
            raise AnalyticsProjectionError("Refund item snapshot not found")
        timezone = await self._timezone(organization_id, refund.location_id)
        promotion_rows = await self.session.execute(
            select(
                SalesOrderDiscountModel.promotion_id,
                SalesOrderDiscountModel.promotion_name,
                func.sum(RefundDiscountAllocationModel.discount_amount_minor),
                func.sum(RefundLineModel.net_refund_minor),
            )
            .join(
                RefundDiscountAllocationModel,
                RefundDiscountAllocationModel.order_discount_id
                == SalesOrderDiscountModel.id,
            )
            .join(
                RefundLineModel,
                RefundLineModel.id == RefundDiscountAllocationModel.refund_line_id,
            )
            .where(
                RefundLineModel.refund_id == refund.id,
                SalesOrderDiscountModel.promotion_id.is_not(None),
            )
            .group_by(
                SalesOrderDiscountModel.promotion_id,
                SalesOrderDiscountModel.promotion_name,
            )
        )
        return AnalyticsRefundSnapshot(
            refund.id,
            organization_id,
            refund.location_id,
            _as_utc(refund.completed_at),
            timezone,
            refund.currency_code,
            Decimal(refund.total_amount_minor) / 100,
            tuple(
                AnalyticsRefundItemSnapshot(
                    items[line.order_item_id].product_id,
                    items[line.order_item_id].product_variant_id,
                    items[line.order_item_id].product_name,
                    items[line.order_item_id].variant_name,
                    line.quantity,
                    Decimal(line.total_refund_minor) / 100,
                )
                for line in refund.lines
            ),
            tuple(
                AnalyticsPromotionSnapshot(
                    promotion_id,
                    name,
                    Decimal(0),
                    Decimal(amount) / 100,
                    refund_amount=Decimal(refund_amount) / 100,
                )
                for promotion_id, name, amount, refund_amount in promotion_rows
            ),
        )

    async def sale(self, organization_id: UUID, payment_id: UUID) -> AnalyticsSaleSnapshot:
        payment = await self.session.scalar(
            select(PaymentModel).where(
                PaymentModel.organization_id == organization_id,
                PaymentModel.id == payment_id,
            )
        )
        if payment is None:
            raise AnalyticsProjectionError("Completed payment not found")
        order = await self.session.scalar(
            select(SalesOrderModel)
            .options(
                selectinload(SalesOrderModel.items).selectinload(SalesOrderItemModel.components)
            )
            .where(
                SalesOrderModel.organization_id == organization_id,
                SalesOrderModel.id == payment.order_id,
                SalesOrderModel.status == "PAID",
            )
        )
        if order is None or order.paid_at is None:
            raise AnalyticsProjectionError("Paid sale not found")
        timezone = await self._timezone(organization_id, payment.location_id)
        promotion_rows = await self.session.execute(
            select(
                SalesOrderDiscountModel.promotion_id,
                SalesOrderDiscountModel.promotion_name,
                func.sum(SalesOrderDiscountAllocationModel.eligible_amount_minor),
                func.sum(SalesOrderDiscountAllocationModel.discount_amount_minor),
                func.count(func.distinct(SalesOrderDiscountModel.id)),
                func.sum(SalesOrderItemModel.quantity),
            )
            .join(
                SalesOrderDiscountAllocationModel,
                SalesOrderDiscountAllocationModel.order_discount_id
                == SalesOrderDiscountModel.id,
            )
            .join(
                SalesOrderItemModel,
                SalesOrderItemModel.id == SalesOrderDiscountAllocationModel.order_item_id,
            )
            .where(
                SalesOrderDiscountModel.order_id == order.id,
                SalesOrderDiscountModel.promotion_id.is_not(None),
            )
            .group_by(
                SalesOrderDiscountModel.promotion_id,
                SalesOrderDiscountModel.promotion_name,
            )
        )
        actual_costs: dict[UUID, Decimal | None] = {}
        actual_inventory_cogs: Decimal | None = None
        if order.inventory_transaction_id is not None:
            rows = list(
                await self.session.execute(
                    select(
                        InventoryTransactionLineModel.inventory_item_id,
                        InventoryTransactionLineModel.unit_cost_amount,
                        InventoryTransactionLineModel.total_cost_amount,
                    )
                    .join(
                        InventoryTransactionModel,
                        InventoryTransactionModel.id
                        == InventoryTransactionLineModel.transaction_id,
                    )
                    .where(
                        InventoryTransactionLineModel.transaction_id
                        == order.inventory_transaction_id,
                        InventoryTransactionModel.organization_id == organization_id,
                        InventoryTransactionModel.type == "SALE",
                        InventoryTransactionModel.status.in_(("POSTED", "REVERSED")),
                        InventoryTransactionModel.reference_type == "ORDER",
                        InventoryTransactionModel.reference_id == order.id,
                    )
                )
            )
            if not rows:
                raise AnalyticsProjectionError("Canonical SALE transaction not found")
            if any(row[2] is None for row in rows):
                raise AnalyticsProjectionError("Posted SALE cost snapshot is missing")
            actual_costs = {row[0]: row[1] for row in rows}
            actual_inventory_cogs = -sum((Decimal(row[2]) for row in rows), Decimal(0))
        items = tuple(
            AnalyticsSaleItemSnapshot(
                item.id,
                item.product_id,
                item.product_variant_id,
                item.product_name,
                item.variant_name,
                item.quantity,
                Decimal(item.line_total_minor) / 100,
                tuple(
                    AnalyticsSaleComponentSnapshot(
                        component.inventory_item_id,
                        component.quantity_per_unit,
                        actual_costs.get(component.inventory_item_id),
                    )
                    for component in item.components
                ),
                Decimal(item.line_total_minor) / 100,
                Decimal(item.discount_amount_minor) / 100,
            )
            for item in sorted(order.items, key=lambda value: str(value.id))
        )
        if (
            payment.order_id != order.id
            or payment.location_id != order.location_id
            or payment.currency_code != order.currency_code
        ):
            raise AnalyticsProjectionError("Payment and sale snapshots do not match")
        return AnalyticsSaleSnapshot(
            payment.id,
            order.id,
            organization_id,
            order.location_id,
            _as_utc(payment.completed_at),
            timezone,
            order.currency_code,
            order.order_type,
            Decimal(payment.amount_minor) / 100,
            order.cogs_amount or Decimal(0),
            order.cogs_status or "INCOMPLETE",
            items,
            actual_inventory_cogs,
            Decimal(order.subtotal_minor) / 100,
            Decimal(order.discount_total_minor) / 100,
            tuple(
                AnalyticsPromotionSnapshot(
                    promotion_id,
                    name,
                    Decimal(gross) / 100,
                    Decimal(discount) / 100,
                    int(applications),
                    int(items_count),
                )
                for promotion_id, name, gross, discount, applications, items_count in promotion_rows
            ),
        )

    async def inventory_transaction(
        self, organization_id: UUID, transaction_id: UUID
    ) -> AnalyticsInventorySnapshot:
        transaction = await self.session.scalar(
            select(InventoryTransactionModel).where(
                InventoryTransactionModel.organization_id == organization_id,
                InventoryTransactionModel.id == transaction_id,
                InventoryTransactionModel.status.in_(("POSTED", "REVERSED")),
            )
        )
        if transaction is None or transaction.posted_at is None:
            raise AnalyticsProjectionError("Posted inventory transaction not found")
        timezone = await self._timezone(organization_id, transaction.location_id)
        rows = await self.session.execute(
            select(InventoryTransactionLineModel, InventoryItemModel)
            .join(
                InventoryItemModel,
                InventoryItemModel.id == InventoryTransactionLineModel.inventory_item_id,
            )
            .where(
                InventoryTransactionLineModel.transaction_id == transaction.id,
                InventoryItemModel.organization_id == organization_id,
            )
            .order_by(InventoryTransactionLineModel.id)
        )
        return AnalyticsInventorySnapshot(
            transaction.id,
            organization_id,
            transaction.location_id,
            transaction.warehouse_id,
            transaction.type,
            _as_utc(transaction.posted_at),
            timezone,
            tuple(
                AnalyticsInventoryLineSnapshot(
                    line.inventory_item_id,
                    item.name,
                    item.base_unit,
                    line.quantity_delta,
                    line.total_cost_amount or Decimal(0),
                )
                for line, item in rows
            ),
        )

    async def expense(self, organization_id: UUID, expense_id: UUID) -> AnalyticsExpenseSnapshot:
        expense = await self.session.scalar(
            select(ExpenseModel).where(
                ExpenseModel.organization_id == organization_id,
                ExpenseModel.id == expense_id,
                ExpenseModel.status.in_(("POSTED", "REVERSED")),
            )
        )
        if expense is None or expense.posted_at is None:
            raise AnalyticsProjectionError("Posted expense not found")
        timezone = (
            await self._timezone(organization_id, expense.location_id)
            if expense.location_id is not None
            else None
        )
        return AnalyticsExpenseSnapshot(
            expense.id,
            organization_id,
            expense.location_id,
            Decimal(expense.amount_minor) / 100,
            _as_utc(expense.occurred_at),
            _as_utc(expense.reversed_at) if expense.reversed_at else None,
            timezone,
            expense.status,
        )

    async def paid_payments(
        self,
        organization_id: UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        *,
        limit: int | None = None,
        after: tuple[datetime, UUID] | None = None,
    ) -> tuple[AnalyticsBackfillSource, ...]:
        statement = (
            select(
                PaymentModel.organization_id,
                PaymentModel.id,
                PaymentModel.completed_at,
            )
            .join(SalesOrderModel, SalesOrderModel.id == PaymentModel.order_id)
            .where(SalesOrderModel.status == "PAID")
        )
        statement = _source_filters(
            statement,
            PaymentModel.organization_id,
            PaymentModel.completed_at,
            organization_id,
            date_from,
            date_to,
        )
        statement = _page(
            statement,
            PaymentModel.completed_at,
            PaymentModel.id,
            limit,
            after,
        )
        rows = await self.session.execute(statement)
        return tuple(AnalyticsBackfillSource(row[0], row[1], _as_utc(row[2])) for row in rows)

    async def posted_inventory_transactions(
        self,
        organization_id: UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        *,
        limit: int | None = None,
        after: tuple[datetime, UUID] | None = None,
    ) -> tuple[AnalyticsBackfillSource, ...]:
        model = InventoryTransactionModel
        statement = select(model.organization_id, model.id, model.posted_at).where(
            model.status.in_(("POSTED", "REVERSED")), model.posted_at.is_not(None)
        )
        statement = _source_filters(
            statement,
            model.organization_id,
            model.posted_at,
            organization_id,
            date_from,
            date_to,
        )
        statement = _page(statement, model.posted_at, model.id, limit, after)
        rows = await self.session.execute(statement)
        return tuple(AnalyticsBackfillSource(row[0], row[1], _as_utc(row[2])) for row in rows)

    async def posted_expenses(
        self,
        organization_id: UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        *,
        limit: int | None = None,
        after: tuple[datetime, UUID] | None = None,
    ) -> tuple[AnalyticsBackfillSource, ...]:
        model = ExpenseModel
        statement = select(model.organization_id, model.id, model.occurred_at).where(
            model.status.in_(("POSTED", "REVERSED"))
        )
        if organization_id is not None:
            statement = statement.where(model.organization_id == organization_id)
        if date_from is not None or date_to is not None:
            start, end = _utc_bounds(date_from, date_to)
            statement = statement.where(
                or_(
                    model.occurred_at.between(start, end),
                    model.reversed_at.between(start, end),
                )
            )
        statement = _page(statement, model.occurred_at, model.id, limit, after)
        rows = await self.session.execute(statement)
        return tuple(AnalyticsBackfillSource(row[0], row[1], _as_utc(row[2])) for row in rows)

    async def _timezone(self, organization_id: UUID, location_id: UUID) -> str:
        value = await self.session.scalar(
            select(LocationModel.timezone).where(
                LocationModel.organization_id == organization_id,
                LocationModel.id == location_id,
            )
        )
        if value is None:
            raise AnalyticsProjectionError("Analytics source location not found")
        return value


def _source_filters(
    statement,
    organization_column,
    timestamp_column,
    organization_id: UUID | None,
    date_from: date | None,
    date_to: date | None,
):
    if organization_id is not None:
        statement = statement.where(organization_column == organization_id)
    if date_from is not None or date_to is not None:
        start, end = _utc_bounds(date_from, date_to)
        statement = statement.where(timestamp_column.between(start, end))
    return statement


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _utc_bounds(date_from: date | None, date_to: date | None) -> tuple[datetime, datetime]:
    first = date_from or date.min
    last = date_to or date.max
    if first == date.min:
        start = datetime.min.replace(tzinfo=UTC)
    else:
        start = datetime.combine(first - timedelta(days=1), time.min, UTC)
    if last == date.max:
        end = datetime.max.replace(tzinfo=UTC)
    else:
        end = datetime.combine(last + timedelta(days=2), time.min, UTC)
    return start, end


def _page(statement, timestamp_column, id_column, limit, after):
    if after is not None:
        occurred_at, source_id = after
        statement = statement.where(
            or_(
                timestamp_column > occurred_at,
                and_(timestamp_column == occurred_at, id_column > source_id),
            )
        )
    statement = statement.order_by(timestamp_column, id_column)
    return statement.limit(limit) if limit is not None else statement
