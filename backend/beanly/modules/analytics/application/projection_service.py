from dataclasses import replace
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from beanly.core.money import MAX_NUMERIC_20_6
from beanly.modules.analytics.application.dto import (
    HourlySalesDelta,
    InventoryConsumptionDailyDelta,
    LocationMetricsDailyDelta,
    ProductSalesDailyDelta,
    SalesDailyDelta,
)
from beanly.modules.analytics.application.ports import AnalyticsRepository
from beanly.modules.analytics.application.source_ports import AnalyticsSourceReader
from beanly.modules.analytics.domain.exceptions import AnalyticsProjectionError

_SIX = Decimal("0.000001")


class AnalyticsProjectionService:
    """Receipt-first, additive projections; the dispatcher owns transactions."""

    def __init__(
        self, repository: AnalyticsRepository, sources: AnalyticsSourceReader
    ) -> None:
        self.repository = repository
        self.sources = sources

    async def apply_payment_completed(
        self,
        event_id: UUID | None,
        organization_id: UUID,
        payment_id: UUID,
        order_id: UUID,
        occurred_at: datetime,
    ) -> bool:
        if not await self.repository.add_receipt(
            "SALE_ANALYTICS",
            "PAYMENT",
            payment_id,
            organization_id,
            event_id,
            occurred_at,
        ):
            return False
        sale = await self.sources.sale(organization_id, payment_id)
        if sale.order_id != order_id or sale.organization_id != organization_id:
            raise AnalyticsProjectionError("Payment event and source snapshot do not match")
        local = _local(sale.paid_at, sale.timezone)
        items_sold = sum(item.quantity for item in sale.items)
        if (
            sale.actual_inventory_cogs is not None
            and abs(sale.actual_inventory_cogs - sale.order_cogs) > _SIX
        ):
            raise AnalyticsProjectionError(
                "Inventory SALE COGS does not reconcile with SalesOrder.cogs_amount"
            )
        product_deltas = _product_deltas(sale, local.date())
        allocated_cogs = sum(
            (delta.cogs_amount for delta in product_deltas), Decimal(0)
        )
        if abs(allocated_cogs - sale.order_cogs) > _SIX:
            raise AnalyticsProjectionError(
                "Product COGS does not reconcile with SalesOrder.cogs_amount"
            )
        order_type = sale.order_type
        incomplete = int(sale.cogs_status == "INCOMPLETE")
        await self.repository.upsert_sales(
            SalesDailyDelta(
                organization_id,
                sale.location_id,
                local.date(),
                sale.timezone,
                sale.currency_code,
                _amount(sale.order_total),
                1,
                items_sold,
                _amount(sale.order_cogs),
                incomplete,
                int(order_type == "DINE_IN"),
                int(order_type == "TAKEAWAY"),
                int(order_type == "DELIVERY"),
            )
        )
        for delta in product_deltas:
            await self.repository.upsert_product(delta)
        await self.repository.upsert_hour(
            HourlySalesDelta(
                organization_id,
                sale.location_id,
                local.date(),
                local.hour,
                _amount(sale.order_total),
                1,
                items_sold,
                _amount(sale.order_cogs),
            )
        )
        await self.repository.upsert_location(
            LocationMetricsDailyDelta(
                organization_id,
                sale.location_id,
                local.date(),
                revenue_amount=_amount(sale.order_total),
                paid_orders=1,
                items_sold=items_sold,
                cogs_amount=_amount(sale.order_cogs),
                incomplete_cogs_orders=incomplete,
            )
        )
        return True

    async def apply_inventory_transaction_posted(
        self,
        event_id: UUID | None,
        organization_id: UUID,
        transaction_id: UUID,
        occurred_at: datetime,
    ) -> bool:
        if not await self.repository.add_receipt(
            "INVENTORY_ANALYTICS",
            "INVENTORY_TRANSACTION",
            transaction_id,
            organization_id,
            event_id,
            occurred_at,
        ):
            return False
        source = await self.sources.inventory_transaction(
            organization_id, transaction_id
        )
        if source.transaction_type not in {"SALE", "WRITE_OFF", "ADJUSTMENT"}:
            return True
        local_date = _local(source.posted_at, source.timezone).date()
        loss = Decimal(0)
        gain = Decimal(0)
        for line in source.lines:
            delta = InventoryConsumptionDailyDelta(
                organization_id,
                source.location_id,
                source.warehouse_id,
                local_date,
                line.inventory_item_id,
                line.inventory_item_name,
                line.base_unit,
                sale_quantity=(
                    _amount(-line.quantity_delta)
                    if source.transaction_type == "SALE"
                    else Decimal(0)
                ),
                sale_cost_amount=(
                    _amount(-line.total_cost_amount)
                    if source.transaction_type == "SALE"
                    else Decimal(0)
                ),
                writeoff_quantity=(
                    _amount(-line.quantity_delta)
                    if source.transaction_type == "WRITE_OFF"
                    else Decimal(0)
                ),
                writeoff_cost_amount=(
                    _amount(-line.total_cost_amount)
                    if source.transaction_type == "WRITE_OFF"
                    else Decimal(0)
                ),
                adjustment_quantity=(
                    _amount(-line.quantity_delta)
                    if source.transaction_type == "ADJUSTMENT"
                    else Decimal(0)
                ),
            )
            await self.repository.upsert_consumption(delta)
            if source.transaction_type == "WRITE_OFF":
                loss += -line.total_cost_amount
            elif source.transaction_type == "ADJUSTMENT":
                if line.total_cost_amount < 0:
                    loss += -line.total_cost_amount
                else:
                    gain += line.total_cost_amount
        if loss or gain:
            await self.repository.upsert_location(
                LocationMetricsDailyDelta(
                    organization_id,
                    source.location_id,
                    local_date,
                    inventory_losses=_amount(loss),
                    inventory_gains=_amount(gain),
                )
            )
        return True

    async def apply_expense_posted(
        self,
        event_id: UUID | None,
        organization_id: UUID,
        expense_id: UUID,
        occurred_at: datetime,
    ) -> bool:
        return await self._apply_expense(
            event_id,
            organization_id,
            expense_id,
            occurred_at,
            source_type="EXPENSE_POSTED",
            reversal=False,
        )

    async def apply_expense_reversed(
        self,
        event_id: UUID | None,
        organization_id: UUID,
        expense_id: UUID,
        occurred_at: datetime,
    ) -> bool:
        return await self._apply_expense(
            event_id,
            organization_id,
            expense_id,
            occurred_at,
            source_type="EXPENSE_REVERSED",
            reversal=True,
        )

    async def _apply_expense(
        self,
        event_id: UUID | None,
        organization_id: UUID,
        expense_id: UUID,
        occurred_at: datetime,
        *,
        source_type: str,
        reversal: bool,
    ) -> bool:
        if not await self.repository.add_receipt(
            "EXPENSE_ANALYTICS",
            source_type,
            expense_id,
            organization_id,
            event_id,
            occurred_at,
        ):
            return False
        source = await self.sources.expense(organization_id, expense_id)
        if source.location_id is None:
            return True
        if source.timezone is None:
            raise AnalyticsProjectionError("Location expense has no timezone")
        effective_at = source.reversed_at if reversal else source.occurred_at
        if effective_at is None:
            raise AnalyticsProjectionError("Reversed expense has no reversed_at")
        await self.repository.upsert_location(
            LocationMetricsDailyDelta(
                organization_id,
                source.location_id,
                _local(effective_at, source.timezone).date(),
                operating_expenses=_amount(-source.amount if reversal else source.amount),
            )
        )
        return True


def _product_deltas(sale, local_date) -> tuple[ProductSalesDailyDelta, ...]:
    grouped: dict[UUID, dict[str, object]] = {}
    for item in sale.items:
        cogs = sum(
            (
                component.quantity_per_unit
                * item.quantity
                * (component.actual_unit_cost or Decimal(0))
                for component in item.components
            ),
            Decimal(0),
        )
        current = grouped.setdefault(
            item.product_variant_id,
            {
                "product_id": item.product_id,
                "product_name": item.product_name,
                "variant_name": item.variant_name,
                "quantity": 0,
                "revenue": Decimal(0),
                "cogs": Decimal(0),
            },
        )
        if current["product_id"] != item.product_id:
            raise AnalyticsProjectionError("Variant belongs to multiple products")
        current["quantity"] = int(current["quantity"]) + item.quantity
        current["revenue"] = Decimal(current["revenue"]) + item.revenue_amount
        current["cogs"] = Decimal(current["cogs"]) + cogs
    raw_total = sum(
        (Decimal(values["cogs"]) for values in grouped.values()), Decimal(0)
    )
    inventory_items = {
        component.inventory_item_id
        for item in sale.items
        for component in item.components
    }
    rounding_tolerance = max(
        _SIX, Decimal(len(inventory_items)) * _SIX / Decimal(2)
    )
    canonical_cogs = (
        sale.actual_inventory_cogs
        if sale.actual_inventory_cogs is not None
        else sale.order_cogs
    )
    if abs(raw_total - canonical_cogs) > rounding_tolerance:
        raise AnalyticsProjectionError(
            "Product COGS does not reconcile with SalesOrder.cogs_amount"
        )
    incomplete = int(sale.cogs_status == "INCOMPLETE")
    deltas = tuple(
        ProductSalesDailyDelta(
            sale.organization_id,
            sale.location_id,
            local_date,
            values["product_id"],
            variant_id,
            str(values["product_name"]),
            str(values["variant_name"]),
            int(values["quantity"]),
            1,
            _amount(Decimal(values["revenue"])),
            _amount(Decimal(values["cogs"])),
            incomplete,
        )
        for variant_id, values in sorted(grouped.items(), key=lambda pair: str(pair[0]))
    )
    if not deltas:
        return deltas
    residual = _amount(sale.order_cogs) - sum(
        (delta.cogs_amount for delta in deltas), Decimal(0)
    )
    if residual:
        deltas = (
            replace(deltas[0], cogs_amount=_amount(deltas[0].cogs_amount + residual)),
            *deltas[1:],
        )
    return deltas


def _local(value: datetime, timezone: str) -> datetime:
    if value.utcoffset() is None:
        raise AnalyticsProjectionError("Analytics source timestamp must be timezone-aware")
    try:
        return value.astimezone(ZoneInfo(timezone))
    except ZoneInfoNotFoundError as exc:
        raise AnalyticsProjectionError("Analytics source timezone is invalid") from exc


def _amount(value: Decimal) -> Decimal:
    result = value.quantize(_SIX, rounding=ROUND_HALF_UP)
    if not result.is_finite() or abs(result) > MAX_NUMERIC_20_6:
        raise AnalyticsProjectionError("Analytics amount exceeds NUMERIC(20,6)")
    return result
