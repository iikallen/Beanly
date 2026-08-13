from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from beanly.modules.analytics.application.dto import (
    HourlySalesDelta,
    InventoryConsumptionDailyDelta,
    LocationMetricsDailyDelta,
    ProductSalesDailyDelta,
    PromotionDailyDelta,
    SalesDailyDelta,
)
from beanly.modules.analytics.application.ports import (
    ConsumptionAggregate,
    HourAggregate,
    LocationAggregate,
    OverviewAggregate,
    ProductAggregate,
)
from beanly.modules.analytics.domain.enums import ProductGroupBy, ProductSort
from beanly.modules.analytics.infrastructure.db.models import (
    AnalyticsHourlySalesModel,
    AnalyticsInventoryConsumptionDailyModel,
    AnalyticsLocationMetricsDailyModel,
    AnalyticsProductSalesDailyModel,
    AnalyticsProjectionReceiptModel,
    AnalyticsPromotionsDailyModel,
    AnalyticsSalesDailyModel,
)
from beanly.modules.organizations.infrastructure.db.models import (
    LocationModel,
    OrganizationModel,
)


class SqlAlchemyAnalyticsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _insert(self, model):
        dialect = self.session.get_bind().dialect.name
        if dialect == "postgresql":
            return pg_insert(model)
        if dialect == "sqlite":
            return sqlite_insert(model)
        raise RuntimeError(f"Analytics projections do not support {dialect}")

    async def add_receipt(
        self,
        projection_name: str,
        source_type: str,
        source_id: UUID,
        organization_id: UUID,
        source_event_id: UUID | None,
        source_occurred_at: datetime,
    ) -> bool:
        statement = (
            self._insert(AnalyticsProjectionReceiptModel)
            .values(
                projection_name=projection_name,
                source_type=source_type,
                source_id=source_id,
                organization_id=organization_id,
                source_event_id=source_event_id,
                source_occurred_at=source_occurred_at,
                projected_at=datetime.now(UTC),
            )
            .on_conflict_do_nothing(index_elements=("projection_name", "source_type", "source_id"))
            .returning(AnalyticsProjectionReceiptModel.source_id)
        )
        return (await self.session.scalar(statement)) is not None

    async def upsert_sales(self, delta: SalesDailyDelta) -> None:
        insert = self._insert(AnalyticsSalesDailyModel).values(**_values(delta))
        excluded = insert.excluded
        await self.session.execute(
            insert.on_conflict_do_update(
                index_elements=("organization_id", "location_id", "local_date"),
                set_={
                    "revenue_amount": AnalyticsSalesDailyModel.revenue_amount
                    + excluded.revenue_amount,
                    "gross_revenue_amount": AnalyticsSalesDailyModel.gross_revenue_amount
                    + excluded.gross_revenue_amount,
                    "discount_amount": AnalyticsSalesDailyModel.discount_amount
                    + excluded.discount_amount,
                    "paid_orders": AnalyticsSalesDailyModel.paid_orders + excluded.paid_orders,
                    "items_sold": AnalyticsSalesDailyModel.items_sold + excluded.items_sold,
                    "cogs_amount": AnalyticsSalesDailyModel.cogs_amount + excluded.cogs_amount,
                    "incomplete_cogs_orders": AnalyticsSalesDailyModel.incomplete_cogs_orders
                    + excluded.incomplete_cogs_orders,
                    "dine_in_orders": AnalyticsSalesDailyModel.dine_in_orders
                    + excluded.dine_in_orders,
                    "takeaway_orders": AnalyticsSalesDailyModel.takeaway_orders
                    + excluded.takeaway_orders,
                    "delivery_orders": AnalyticsSalesDailyModel.delivery_orders
                    + excluded.delivery_orders,
                    "refund_amount": AnalyticsSalesDailyModel.refund_amount
                    + excluded.refund_amount,
                    "refund_count": AnalyticsSalesDailyModel.refund_count + excluded.refund_count,
                    "refunded_items": AnalyticsSalesDailyModel.refunded_items
                    + excluded.refunded_items,
                    "updated_at": excluded.updated_at,
                },
            )
        )

    async def upsert_product(self, delta: ProductSalesDailyDelta) -> None:
        insert = self._insert(AnalyticsProductSalesDailyModel).values(**_values(delta))
        excluded = insert.excluded
        await self.session.execute(
            insert.on_conflict_do_update(
                index_elements=(
                    "organization_id",
                    "location_id",
                    "local_date",
                    "product_variant_id",
                ),
                set_={
                    "quantity_sold": AnalyticsProductSalesDailyModel.quantity_sold
                    + excluded.quantity_sold,
                    "orders_count": AnalyticsProductSalesDailyModel.orders_count
                    + excluded.orders_count,
                    "revenue_amount": AnalyticsProductSalesDailyModel.revenue_amount
                    + excluded.revenue_amount,
                    "gross_revenue_amount": AnalyticsProductSalesDailyModel.gross_revenue_amount
                    + excluded.gross_revenue_amount,
                    "discount_amount": AnalyticsProductSalesDailyModel.discount_amount
                    + excluded.discount_amount,
                    "cogs_amount": AnalyticsProductSalesDailyModel.cogs_amount
                    + excluded.cogs_amount,
                    "incomplete_cogs_orders": (
                        AnalyticsProductSalesDailyModel.incomplete_cogs_orders
                        + excluded.incomplete_cogs_orders
                    ),
                    "refund_amount": AnalyticsProductSalesDailyModel.refund_amount
                    + excluded.refund_amount,
                    "refunded_quantity": AnalyticsProductSalesDailyModel.refunded_quantity
                    + excluded.refunded_quantity,
                    "refund_orders": AnalyticsProductSalesDailyModel.refund_orders
                    + excluded.refund_orders,
                    "updated_at": excluded.updated_at,
                },
            )
        )

    async def upsert_promotion(self, delta: PromotionDailyDelta) -> None:
        insert = self._insert(AnalyticsPromotionsDailyModel).values(**_values(delta))
        excluded = insert.excluded
        columns = (
            "orders_count",
            "applications_count",
            "items_count",
            "gross_eligible_amount",
            "discount_amount",
            "net_revenue_amount",
            "refund_amount",
        )
        await self.session.execute(
            insert.on_conflict_do_update(
                index_elements=(
                    "organization_id",
                    "location_id",
                    "local_date",
                    "promotion_id",
                ),
                set_={
                    **{
                        column: getattr(AnalyticsPromotionsDailyModel, column)
                        + getattr(excluded, column)
                        for column in columns
                    },
                    "promotion_name": excluded.promotion_name,
                    "updated_at": excluded.updated_at,
                },
            )
        )

    async def upsert_hour(self, delta: HourlySalesDelta) -> None:
        insert = self._insert(AnalyticsHourlySalesModel).values(**_values(delta))
        excluded = insert.excluded
        await self.session.execute(
            insert.on_conflict_do_update(
                index_elements=(
                    "organization_id",
                    "location_id",
                    "local_date",
                    "local_hour",
                ),
                set_={
                    "revenue_amount": AnalyticsHourlySalesModel.revenue_amount
                    + excluded.revenue_amount,
                    "paid_orders": AnalyticsHourlySalesModel.paid_orders + excluded.paid_orders,
                    "items_sold": AnalyticsHourlySalesModel.items_sold + excluded.items_sold,
                    "cogs_amount": AnalyticsHourlySalesModel.cogs_amount + excluded.cogs_amount,
                    "updated_at": excluded.updated_at,
                },
            )
        )

    async def upsert_location(self, delta: LocationMetricsDailyDelta) -> None:
        insert = self._insert(AnalyticsLocationMetricsDailyModel).values(**_values(delta))
        excluded = insert.excluded
        columns = (
            "revenue_amount",
            "paid_orders",
            "items_sold",
            "cogs_amount",
            "operating_expenses",
            "inventory_losses",
            "inventory_gains",
            "incomplete_cogs_orders",
            "refund_amount",
        )
        await self.session.execute(
            insert.on_conflict_do_update(
                index_elements=("organization_id", "location_id", "local_date"),
                set_={
                    **{
                        column: getattr(AnalyticsLocationMetricsDailyModel, column)
                        + getattr(excluded, column)
                        for column in columns
                    },
                    "updated_at": excluded.updated_at,
                },
            )
        )

    async def upsert_consumption(self, delta: InventoryConsumptionDailyDelta) -> None:
        insert = self._insert(AnalyticsInventoryConsumptionDailyModel).values(**_values(delta))
        excluded = insert.excluded
        columns = (
            "sale_quantity",
            "sale_cost_amount",
            "writeoff_quantity",
            "writeoff_cost_amount",
            "adjustment_quantity",
        )
        await self.session.execute(
            insert.on_conflict_do_update(
                index_elements=(
                    "organization_id",
                    "location_id",
                    "warehouse_id",
                    "local_date",
                    "inventory_item_id",
                ),
                set_={
                    **{
                        column: getattr(AnalyticsInventoryConsumptionDailyModel, column)
                        + getattr(excluded, column)
                        for column in columns
                    },
                    "updated_at": excluded.updated_at,
                },
            )
        )

    async def organization_currency(self, organization_id: UUID) -> str:
        value = await self.session.scalar(
            select(OrganizationModel.currency_code).where(OrganizationModel.id == organization_id)
        )
        if value is None:
            raise ValueError("Organization not found")
        return value

    async def overview(
        self,
        organization_id: UUID,
        date_from: date,
        date_to: date,
        location_ids: set[UUID] | None,
    ) -> OverviewAggregate:
        sales = AnalyticsSalesDailyModel
        statement = select(
            func.coalesce(func.sum(sales.revenue_amount), 0),
            func.coalesce(func.sum(sales.paid_orders), 0),
            func.coalesce(func.sum(sales.items_sold), 0),
            func.coalesce(func.sum(sales.cogs_amount), 0),
            func.coalesce(func.sum(sales.incomplete_cogs_orders), 0),
            func.coalesce(func.sum(sales.refund_amount), 0),
        ).where(
            sales.organization_id == organization_id,
            sales.local_date.between(date_from, date_to),
        )
        statement = _locations(statement, sales.location_id, location_ids)
        row = (await self.session.execute(statement)).one()
        location = AnalyticsLocationMetricsDailyModel
        loss_statement = select(func.coalesce(func.sum(location.inventory_losses), 0)).where(
            location.organization_id == organization_id,
            location.local_date.between(date_from, date_to),
        )
        loss_statement = _locations(loss_statement, location.location_id, location_ids)
        losses = await self.session.scalar(loss_statement)
        return OverviewAggregate(
            Decimal(row[0]),
            int(row[1]),
            int(row[2]),
            Decimal(row[3]),
            Decimal(losses or 0),
            int(row[4]),
            Decimal(row[5]),
        )

    async def products(
        self,
        organization_id: UUID,
        date_from: date,
        date_to: date,
        location_ids: set[UUID] | None,
        group_by: ProductGroupBy,
        sort_by: ProductSort,
        limit: int | None,
    ) -> tuple[ProductAggregate, ...]:
        model = AnalyticsProductSalesDailyModel
        revenue = func.sum(model.revenue_amount).label("revenue")
        quantity = func.sum(model.quantity_sold).label("quantity")
        cogs = func.sum(model.cogs_amount).label("cogs")
        orders = func.sum(model.orders_count).label("orders")
        incomplete = func.sum(model.incomplete_cogs_orders).label("incomplete")
        refund = func.sum(model.refund_amount).label("refund")
        refunded_quantity = func.sum(model.refunded_quantity).label("refunded_quantity")
        refund_orders = func.sum(model.refund_orders).label("refund_orders")
        if group_by == ProductGroupBy.PRODUCT:
            keys = (model.product_id,)
            variant_id = None
            variant_name = None
        else:
            keys = (model.product_id, model.product_variant_id)
            variant_id = model.product_variant_id
            variant_name = func.max(model.variant_name)
        statement = select(
            model.product_id,
            variant_id,
            func.max(model.product_name),
            variant_name,
            quantity,
            revenue,
            orders,
            cogs,
            incomplete,
            refund,
            refunded_quantity,
            refund_orders,
        ).where(
            model.organization_id == organization_id,
            model.local_date.between(date_from, date_to),
        )
        statement = _locations(statement, model.location_id, location_ids).group_by(*keys)
        order = {
            ProductSort.REVENUE: revenue - refund,
            ProductSort.QUANTITY: quantity,
            ProductSort.GROSS_PROFIT: revenue - refund - cogs,
        }[sort_by]
        statement = statement.order_by(order.desc(), model.product_id)
        if limit is not None:
            statement = statement.limit(limit)
        rows = await self.session.execute(statement)
        return tuple(
            ProductAggregate(
                row[0],
                row[1],
                row[2],
                row[3],
                int(row[4]),
                Decimal(row[5]),
                int(row[6]),
                Decimal(row[7]),
                int(row[8]),
                Decimal(row[9]),
                int(row[10]),
                int(row[11]),
            )
            for row in rows
        )

    async def hours(
        self,
        organization_id: UUID,
        date_from: date,
        date_to: date,
        location_ids: set[UUID] | None,
    ) -> tuple[HourAggregate, ...]:
        model = AnalyticsHourlySalesModel
        statement = select(
            model.local_date,
            model.local_hour,
            func.sum(model.revenue_amount),
            func.sum(model.paid_orders),
            func.sum(model.items_sold),
        ).where(
            model.organization_id == organization_id,
            model.local_date.between(date_from, date_to),
        )
        statement = (
            _locations(statement, model.location_id, location_ids)
            .group_by(model.local_date, model.local_hour)
            .order_by(model.local_date, model.local_hour)
        )
        rows = await self.session.execute(statement)
        return tuple(
            HourAggregate(row[0], row[1], Decimal(row[2]), int(row[3]), int(row[4])) for row in rows
        )

    async def consumption(
        self,
        organization_id: UUID,
        date_from: date,
        date_to: date,
        location_ids: set[UUID] | None,
        warehouse_id: UUID | None,
        inventory_item_id: UUID | None,
    ) -> tuple[ConsumptionAggregate, ...]:
        model = AnalyticsInventoryConsumptionDailyModel
        sums = [
            func.sum(getattr(model, column))
            for column in (
                "sale_quantity",
                "sale_cost_amount",
                "writeoff_quantity",
                "writeoff_cost_amount",
                "adjustment_quantity",
            )
        ]
        statement = select(
            model.inventory_item_id,
            func.max(model.inventory_item_name),
            func.max(model.base_unit),
            *sums,
        ).where(
            model.organization_id == organization_id,
            model.local_date.between(date_from, date_to),
        )
        statement = _locations(statement, model.location_id, location_ids)
        if warehouse_id is not None:
            statement = statement.where(model.warehouse_id == warehouse_id)
        if inventory_item_id is not None:
            statement = statement.where(model.inventory_item_id == inventory_item_id)
        rows = await self.session.execute(
            statement.group_by(model.inventory_item_id).order_by(sums[1].desc())
        )
        return tuple(
            ConsumptionAggregate(row[0], row[1], row[2], *(Decimal(value) for value in row[3:]))
            for row in rows
        )

    async def locations(
        self,
        organization_id: UUID,
        date_from: date,
        date_to: date,
        location_ids: set[UUID] | None,
    ) -> tuple[LocationAggregate, ...]:
        model = AnalyticsLocationMetricsDailyModel
        statement = (
            select(
                model.location_id,
                LocationModel.name,
                func.sum(model.revenue_amount),
                func.sum(model.paid_orders),
                func.sum(model.items_sold),
                func.sum(model.cogs_amount),
                func.sum(model.operating_expenses),
                func.sum(model.inventory_losses),
                func.sum(model.inventory_gains),
                func.sum(model.refund_amount),
            )
            .join(LocationModel, LocationModel.id == model.location_id)
            .where(
                model.organization_id == organization_id,
                model.local_date.between(date_from, date_to),
            )
        )
        statement = _locations(statement, model.location_id, location_ids)
        rows = await self.session.execute(statement.group_by(model.location_id, LocationModel.name))
        return tuple(
            LocationAggregate(
                row[0],
                row[1],
                Decimal(row[2]),
                int(row[3]),
                int(row[4]),
                Decimal(row[5]),
                Decimal(row[6]),
                Decimal(row[7]),
                Decimal(row[8]),
                Decimal(row[9]),
            )
            for row in rows
        )

    async def data_as_of(self, organization_id: UUID) -> datetime | None:
        return await self.session.scalar(
            select(func.max(AnalyticsProjectionReceiptModel.source_occurred_at)).where(
                AnalyticsProjectionReceiptModel.organization_id == organization_id
            )
        )

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()


def _values(value) -> dict[str, object]:
    return {field: getattr(value, field) for field in value.__dataclass_fields__} | {
        "updated_at": datetime.now(UTC)
    }


def _locations(statement: Select, column, location_ids: set[UUID] | None) -> Select:
    if location_ids is None:
        return statement
    if not location_ids:
        return statement.where(column.in_(()))
    return statement.where(column.in_(location_ids))
