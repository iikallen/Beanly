from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from beanly.modules.analytics.application.analytics_query_service import (
    AnalyticsQueryService,
)
from beanly.modules.analytics.application.backfill_service import (
    AnalyticsBackfillService,
)
from beanly.modules.analytics.application.ports import (
    LocationAggregate,
    OverviewAggregate,
    ProductAggregate,
)
from beanly.modules.analytics.application.projection_service import (
    AnalyticsProjectionService,
)
from beanly.modules.analytics.application.source_ports import (
    AnalyticsBackfillSource,
    AnalyticsExpenseSnapshot,
    AnalyticsInventoryLineSnapshot,
    AnalyticsInventorySnapshot,
    AnalyticsSaleComponentSnapshot,
    AnalyticsSaleItemSnapshot,
    AnalyticsSaleSnapshot,
)
from beanly.modules.analytics.domain.enums import (
    ABCClass,
    MenuEngineeringClass,
    ProductSort,
)
from beanly.modules.analytics.domain.exceptions import (
    AnalyticsFinancialAccessDenied,
    AnalyticsProjectionError,
)
from beanly.modules.analytics.infrastructure.db.models import (
    AnalyticsLocationMetricsDailyModel,
    AnalyticsProductSalesDailyModel,
    AnalyticsProjectionReceiptModel,
    AnalyticsSalesDailyModel,
)
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.organizations.domain.enums import LocationAccess, MembershipRole
from beanly.modules.organizations.domain.permissions import permissions_for


class MemoryAnalyticsRepository:
    def __init__(self) -> None:
        self.receipts: set[tuple[str, str, UUID]] = set()
        self.sales = []
        self.products = []
        self.hours = []
        self.locations = []
        self.consumption_rows = []
        self.commits = 0
        self.rollbacks = 0

    async def add_receipt(
        self,
        projection_name,
        source_type,
        source_id,
        organization_id,
        source_event_id,
        source_occurred_at,
    ) -> bool:
        key = projection_name, source_type, source_id
        if key in self.receipts:
            return False
        self.receipts.add(key)
        return True

    async def upsert_sales(self, delta) -> None:
        self.sales.append(delta)

    async def upsert_product(self, delta) -> None:
        self.products.append(delta)

    async def upsert_hour(self, delta) -> None:
        self.hours.append(delta)

    async def upsert_location(self, delta) -> None:
        self.locations.append(delta)

    async def upsert_consumption(self, delta) -> None:
        self.consumption_rows.append(delta)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class MemoryAnalyticsSources:
    def __init__(self) -> None:
        self.sales: dict[UUID, AnalyticsSaleSnapshot] = {}
        self.inventory: dict[UUID, AnalyticsInventorySnapshot] = {}
        self.expenses: dict[UUID, AnalyticsExpenseSnapshot] = {}
        self.payment_sources: tuple[AnalyticsBackfillSource, ...] = ()
        self.inventory_sources: tuple[AnalyticsBackfillSource, ...] = ()
        self.expense_sources: tuple[AnalyticsBackfillSource, ...] = ()

    async def sale(self, organization_id, payment_id):
        value = self.sales[payment_id]
        assert value.organization_id == organization_id
        return value

    async def inventory_transaction(self, organization_id, transaction_id):
        value = self.inventory[transaction_id]
        assert value.organization_id == organization_id
        return value

    async def expense(self, organization_id, expense_id):
        value = self.expenses[expense_id]
        assert value.organization_id == organization_id
        return value

    async def paid_payments(
        self,
        organization_id=None,
        date_from=None,
        date_to=None,
        *,
        limit=None,
        after=None,
    ):
        return _page(self.payment_sources, limit, after)

    async def posted_inventory_transactions(
        self,
        organization_id=None,
        date_from=None,
        date_to=None,
        *,
        limit=None,
        after=None,
    ):
        return _page(self.inventory_sources, limit, after)

    async def posted_expenses(
        self,
        organization_id=None,
        date_from=None,
        date_to=None,
        *,
        limit=None,
        after=None,
    ):
        return _page(self.expense_sources, limit, after)


def _page(values, limit, after):
    ordered = sorted(values, key=lambda value: (value.occurred_at, value.source_id))
    if after is not None:
        ordered = [
            value
            for value in ordered
            if (value.occurred_at, value.source_id) > after
        ]
    return tuple(ordered[:limit] if limit is not None else ordered)


class QueryAnalyticsRepository:
    def __init__(self) -> None:
        self.product_rows: tuple[ProductAggregate, ...] = ()
        self.location_rows: tuple[LocationAggregate, ...] = ()
        self.overview_row = OverviewAggregate(
            Decimal("1000"), 2, 3, Decimal("250"), Decimal("20"), 1
        )
        self.last_location_scope = None

    async def organization_currency(self, organization_id):
        return "KZT"

    async def overview(self, organization_id, date_from, date_to, location_ids):
        self.last_location_scope = location_ids
        return self.overview_row

    async def products(
        self,
        organization_id,
        date_from,
        date_to,
        location_ids,
        group_by,
        sort_by,
        limit,
    ):
        self.last_location_scope = location_ids
        return self.product_rows[:limit] if limit is not None else self.product_rows

    async def locations(self, organization_id, date_from, date_to, location_ids):
        self.last_location_scope = location_ids
        return self.location_rows

    async def data_as_of(self, organization_id):
        return datetime(2026, 8, 10, 9, 18, 32, tzinfo=UTC)


class QueryOrganizations:
    def __init__(self, accessible: tuple[UUID, ...] = ()) -> None:
        self.accessible = accessible

    async def ensure_location_access(self, context, location_id):
        if location_id not in self.accessible:
            from beanly.modules.organizations.domain.exceptions import (
                OrganizationAccessDenied,
            )

            raise OrganizationAccessDenied

    async def list_locations(self, query):
        return [SimpleNamespace(id=value) for value in self.accessible]


def _context(role: MembershipRole) -> TenantContext:
    return TenantContext(
        user_id=uuid4(),
        organization_id=uuid4(),
        membership_id=uuid4(),
        role=role,
        permissions=permissions_for(role),
        location_access=(
            LocationAccess.ALL
            if role in {MembershipRole.OWNER, MembershipRole.ADMIN}
            else LocationAccess.SELECTED
        ),
    )


def _sale(
    *,
    paid_at: datetime = datetime(2026, 8, 10, 20, 30, tzinfo=UTC),
    timezone: str = "Asia/Almaty",
    order_total: Decimal = Decimal("6500"),
    order_cogs: Decimal = Decimal(0),
    cogs_status: str = "COMPLETE",
    items: tuple[AnalyticsSaleItemSnapshot, ...] = (),
    actual_inventory_cogs: Decimal | None = None,
) -> AnalyticsSaleSnapshot:
    return AnalyticsSaleSnapshot(
        payment_id=uuid4(),
        order_id=uuid4(),
        organization_id=uuid4(),
        location_id=uuid4(),
        paid_at=paid_at,
        timezone=timezone,
        currency_code="KZT",
        order_type="DINE_IN",
        order_total=order_total,
        order_cogs=order_cogs,
        cogs_status=cogs_status,
        items=items,
        actual_inventory_cogs=actual_inventory_cogs,
    )


def _item(
    product_id: UUID,
    variant_id: UUID,
    name: str,
    quantity: int,
    revenue: str,
    components: tuple[AnalyticsSaleComponentSnapshot, ...] = (),
) -> AnalyticsSaleItemSnapshot:
    return AnalyticsSaleItemSnapshot(
        order_item_id=uuid4(),
        product_id=product_id,
        product_variant_id=variant_id,
        product_name=name,
        variant_name="Regular",
        quantity=quantity,
        revenue_amount=Decimal(revenue),
        components=components,
    )


@pytest.mark.anyio
async def test_payment_projection_updates_all_read_models_once_and_groups_order_count() -> None:
    repository = MemoryAnalyticsRepository()
    sources = MemoryAnalyticsSources()
    cappuccino = uuid4()
    cappuccino_variant = uuid4()
    latte = uuid4()
    sale = _sale(
        items=(
            _item(cappuccino, cappuccino_variant, "Cappuccino", 1, "2000"),
            _item(cappuccino, cappuccino_variant, "Cappuccino", 1, "2000"),
            _item(latte, uuid4(), "Latte", 1, "2500"),
        )
    )
    sources.sales[sale.payment_id] = sale
    service = AnalyticsProjectionService(repository, sources)

    assert await service.apply_payment_completed(
        uuid4(), sale.organization_id, sale.payment_id, sale.order_id, sale.paid_at
    )
    assert not await service.apply_payment_completed(
        uuid4(), sale.organization_id, sale.payment_id, sale.order_id, sale.paid_at
    )

    assert len(repository.receipts) == 1
    assert len(repository.sales) == len(repository.hours) == len(repository.locations) == 1
    daily = repository.sales[0]
    assert (daily.local_date, daily.revenue_amount, daily.paid_orders, daily.items_sold) == (
        date(2026, 8, 11),
        Decimal("6500.000000"),
        1,
        3,
    )
    assert (daily.dine_in_orders, daily.takeaway_orders, daily.delivery_orders) == (
        1,
        0,
        0,
    )
    assert repository.hours[0].local_hour == 1
    cappuccino_row = next(
        row for row in repository.products if row.product_id == cappuccino
    )
    assert cappuccino_row.quantity_sold == 2
    assert cappuccino_row.orders_count == 1
    assert cappuccino_row.revenue_amount == Decimal("4000.000000")


@pytest.mark.anyio
async def test_actual_product_cogs_reconciles_and_incomplete_flag_is_not_hidden() -> None:
    repository = MemoryAnalyticsRepository()
    sources = MemoryAnalyticsSources()
    coffee_id = uuid4()
    milk_id = uuid4()
    complete = _sale(
        order_cogs=Decimal("628"),
        items=(
            _item(
                uuid4(),
                uuid4(),
                "Cappuccino",
                2,
                "3000",
                (
                    AnalyticsSaleComponentSnapshot(
                        coffee_id, Decimal("18"), Decimal("8.5")
                    ),
                    AnalyticsSaleComponentSnapshot(
                        milk_id, Decimal("230"), Decimal("0.7")
                    ),
                ),
            ),
        ),
    )
    sources.sales[complete.payment_id] = complete
    service = AnalyticsProjectionService(repository, sources)
    await service.apply_payment_completed(
        uuid4(),
        complete.organization_id,
        complete.payment_id,
        complete.order_id,
        complete.paid_at,
    )
    assert repository.products[0].cogs_amount == Decimal("628.000000")
    assert repository.sales[0].cogs_amount == Decimal("628.000000")

    incomplete = _sale(
        order_cogs=Decimal(0),
        cogs_status="INCOMPLETE",
        items=(
            _item(
                uuid4(),
                uuid4(),
                "Unknown WAC",
                1,
                "1000",
                (AnalyticsSaleComponentSnapshot(uuid4(), Decimal(1), None),),
            ),
        ),
    )
    sources.sales[incomplete.payment_id] = incomplete
    await service.apply_payment_completed(
        uuid4(),
        incomplete.organization_id,
        incomplete.payment_id,
        incomplete.order_id,
        incomplete.paid_at,
    )
    assert repository.products[-1].incomplete_cogs_orders == 1
    assert repository.sales[-1].incomplete_cogs_orders == 1
    assert repository.locations[-1].incomplete_cogs_orders == 1


@pytest.mark.anyio
async def test_multi_product_cogs_reconciles_at_six_decimal_precision() -> None:
    repository = MemoryAnalyticsRepository()
    sources = MemoryAnalyticsSources()
    sale = _sale(
        order_cogs=Decimal("0.999999"),
        actual_inventory_cogs=Decimal("0.999999"),
        items=tuple(
            _item(
                uuid4(),
                uuid4(),
                name,
                1,
                "10",
                (
                    AnalyticsSaleComponentSnapshot(
                        uuid4(), Decimal(1), Decimal("0.3333334")
                    ),
                ),
            )
            for name in ("A", "B", "C")
        ),
    )
    sources.sales[sale.payment_id] = sale
    await AnalyticsProjectionService(repository, sources).apply_payment_completed(
        uuid4(), sale.organization_id, sale.payment_id, sale.order_id, sale.paid_at
    )
    product_total = sum(
        (row.cogs_amount for row in repository.products), Decimal(0)
    )
    assert abs(product_total - sale.order_cogs) <= Decimal("0.000001")


@pytest.mark.anyio
async def test_cogs_mismatch_is_not_silently_projected() -> None:
    repository = MemoryAnalyticsRepository()
    sources = MemoryAnalyticsSources()
    sale = _sale(
        order_cogs=Decimal("2"),
        actual_inventory_cogs=Decimal("1"),
        items=(
            _item(
                uuid4(),
                uuid4(),
                "Mismatch",
                1,
                "10",
                (
                    AnalyticsSaleComponentSnapshot(
                        uuid4(), Decimal(1), Decimal(1)
                    ),
                ),
            ),
        ),
    )
    sources.sales[sale.payment_id] = sale
    with pytest.raises(AnalyticsProjectionError, match="does not reconcile"):
        await AnalyticsProjectionService(repository, sources).apply_payment_completed(
            uuid4(), sale.organization_id, sale.payment_id, sale.order_id, sale.paid_at
        )
    assert repository.sales == []
    assert repository.products == []


@pytest.mark.anyio
async def test_material_product_allocation_mismatch_is_not_absorbed_as_rounding() -> None:
    repository = MemoryAnalyticsRepository()
    sources = MemoryAnalyticsSources()
    sale = _sale(
        order_cogs=Decimal("2"),
        actual_inventory_cogs=Decimal("2"),
        items=(
            _item(
                uuid4(),
                uuid4(),
                "Material mismatch",
                1,
                "10",
                (
                    AnalyticsSaleComponentSnapshot(
                        uuid4(), Decimal(1), Decimal(1)
                    ),
                ),
            ),
        ),
    )
    sources.sales[sale.payment_id] = sale
    with pytest.raises(AnalyticsProjectionError, match="does not reconcile"):
        await AnalyticsProjectionService(repository, sources).apply_payment_completed(
            uuid4(), sale.organization_id, sale.payment_id, sale.order_id, sale.paid_at
        )
    assert repository.sales == []
    assert repository.products == []


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("paid_at", "timezone", "expected_date", "expected_hour"),
    [
        (
            datetime(2026, 8, 10, 20, 30, tzinfo=UTC),
            "Asia/Almaty",
            date(2026, 8, 11),
            1,
        ),
        (
            datetime(2026, 11, 1, 5, 30, tzinfo=UTC),
            "America/New_York",
            date(2026, 11, 1),
            1,
        ),
        (
            datetime(2026, 11, 1, 6, 30, tzinfo=UTC),
            "America/New_York",
            date(2026, 11, 1),
            1,
        ),
    ],
)
async def test_projection_buckets_by_location_timezone_and_dst(
    paid_at, timezone, expected_date, expected_hour
) -> None:
    repository = MemoryAnalyticsRepository()
    sources = MemoryAnalyticsSources()
    sale = _sale(paid_at=paid_at, timezone=timezone)
    sources.sales[sale.payment_id] = sale
    await AnalyticsProjectionService(repository, sources).apply_payment_completed(
        uuid4(), sale.organization_id, sale.payment_id, sale.order_id, paid_at
    )
    assert repository.sales[0].local_date == expected_date
    assert repository.hours[0].local_hour == expected_hour


@pytest.mark.anyio
async def test_inventory_reversal_cancels_consumption_and_ignored_types_do_not_write() -> None:
    repository = MemoryAnalyticsRepository()
    sources = MemoryAnalyticsSources()
    organization_id = uuid4()
    location_id = uuid4()
    warehouse_id = uuid4()
    item_id = uuid4()
    posted_at = datetime(2026, 8, 10, 20, 30, tzinfo=UTC)

    def inventory_snapshot(transaction_type: str, quantity: str, cost: str):
        return AnalyticsInventorySnapshot(
            uuid4(),
            organization_id,
            location_id,
            warehouse_id,
            transaction_type,
            posted_at,
            "Asia/Almaty",
            (
                AnalyticsInventoryLineSnapshot(
                    item_id,
                    "Milk",
                    "ML",
                    Decimal(quantity),
                    Decimal(cost),
                ),
            ),
        )

    original = inventory_snapshot("WRITE_OFF", "-2000", "-1520")
    reversal = inventory_snapshot("WRITE_OFF", "2000", "1520")
    sources.inventory[original.transaction_id] = original
    sources.inventory[reversal.transaction_id] = reversal
    service = AnalyticsProjectionService(repository, sources)
    for value in (original, reversal):
        assert await service.apply_inventory_transaction_posted(
            uuid4(), organization_id, value.transaction_id, posted_at
        )
    assert sum(
        (row.writeoff_quantity for row in repository.consumption_rows), Decimal(0)
    ) == Decimal(0)
    assert sum(
        (row.writeoff_cost_amount for row in repository.consumption_rows), Decimal(0)
    ) == Decimal(0)
    assert sum(
        (row.inventory_losses for row in repository.locations), Decimal(0)
    ) == Decimal(0)

    before = len(repository.consumption_rows)
    for transaction_type in (
        "PURCHASE",
        "TRANSFER_IN",
        "TRANSFER_OUT",
        "OPENING_BALANCE",
    ):
        ignored = inventory_snapshot(transaction_type, "20", "100")
        sources.inventory[ignored.transaction_id] = ignored
        assert await service.apply_inventory_transaction_posted(
            uuid4(), organization_id, ignored.transaction_id, posted_at
        )
    assert len(repository.consumption_rows) == before

    adjustment = inventory_snapshot("ADJUSTMENT", "-5", "-25")
    adjustment_reversal = inventory_snapshot("ADJUSTMENT", "5", "25")
    sources.inventory[adjustment.transaction_id] = adjustment
    sources.inventory[adjustment_reversal.transaction_id] = adjustment_reversal
    for value in (adjustment, adjustment_reversal):
        await service.apply_inventory_transaction_posted(
            uuid4(), organization_id, value.transaction_id, posted_at
        )
    assert repository.consumption_rows[-2].adjustment_quantity == Decimal("5.000000")
    assert repository.consumption_rows[-1].adjustment_quantity == Decimal("-5.000000")


@pytest.mark.anyio
async def test_location_expense_post_and_reversal_net_to_zero_and_central_is_excluded() -> None:
    repository = MemoryAnalyticsRepository()
    sources = MemoryAnalyticsSources()
    expense = AnalyticsExpenseSnapshot(
        expense_id=uuid4(),
        organization_id=uuid4(),
        location_id=uuid4(),
        amount=Decimal("500"),
        occurred_at=datetime(2026, 8, 10, 10, tzinfo=UTC),
        reversed_at=datetime(2026, 8, 10, 11, tzinfo=UTC),
        timezone="Asia/Almaty",
        status="REVERSED",
    )
    sources.expenses[expense.expense_id] = expense
    service = AnalyticsProjectionService(repository, sources)
    assert await service.apply_expense_posted(
        uuid4(), expense.organization_id, expense.expense_id, expense.occurred_at
    )
    assert await service.apply_expense_reversed(
        uuid4(), expense.organization_id, expense.expense_id, expense.reversed_at
    )
    assert sum(
        (row.operating_expenses for row in repository.locations), Decimal(0)
    ) == Decimal(0)

    central = replace(expense, expense_id=uuid4(), location_id=None, timezone=None)
    sources.expenses[central.expense_id] = central
    before = len(repository.locations)
    assert await service.apply_expense_posted(
        uuid4(), central.organization_id, central.expense_id, central.occurred_at
    )
    assert len(repository.locations) == before


@pytest.mark.anyio
async def test_backfill_uses_canonical_sources_and_repeated_run_is_safe() -> None:
    repository = MemoryAnalyticsRepository()
    sources = MemoryAnalyticsSources()
    sale = _sale(items=(_item(uuid4(), uuid4(), "Tea", 1, "6500"),))
    sources.sales[sale.payment_id] = sale
    sources.payment_sources = (
        AnalyticsBackfillSource(
            sale.organization_id, sale.payment_id, sale.paid_at
        ),
    )
    inventory = AnalyticsInventorySnapshot(
        uuid4(),
        sale.organization_id,
        sale.location_id,
        uuid4(),
        "SALE",
        sale.paid_at,
        sale.timezone,
        (
            AnalyticsInventoryLineSnapshot(
                uuid4(), "Tea leaves", "G", Decimal("-5"), Decimal("-20")
            ),
        ),
    )
    sources.inventory[inventory.transaction_id] = inventory
    sources.inventory_sources = (
        AnalyticsBackfillSource(
            inventory.organization_id, inventory.transaction_id, inventory.posted_at
        ),
    )
    expense = AnalyticsExpenseSnapshot(
        uuid4(),
        sale.organization_id,
        sale.location_id,
        Decimal("100"),
        sale.paid_at,
        None,
        sale.timezone,
        "POSTED",
    )
    sources.expenses[expense.expense_id] = expense
    sources.expense_sources = (
        AnalyticsBackfillSource(
            expense.organization_id, expense.expense_id, expense.occurred_at
        ),
    )
    projections = AnalyticsProjectionService(repository, sources)
    backfill = AnalyticsBackfillService(projections, sources, repository)

    first = await backfill.run(batch_size=2)
    state = (
        len(repository.sales),
        len(repository.products),
        len(repository.hours),
        len(repository.locations),
        len(repository.consumption_rows),
    )
    second = await backfill.run(batch_size=2)
    assert first.payments == 1
    assert first.inventory_transactions == 1
    assert first.expenses_posted == 1
    assert second.payments == 0
    assert second.inventory_transactions == 0
    assert second.expenses_posted == 0
    assert state == (
        len(repository.sales),
        len(repository.products),
        len(repository.hours),
        len(repository.locations),
        len(repository.consumption_rows),
    )
    assert repository.commits >= 2
    assert repository.rollbacks == 0


@pytest.mark.anyio
async def test_backfill_keyset_paginates_sources_by_batch_size() -> None:
    repository = MemoryAnalyticsRepository()
    sources = MemoryAnalyticsSources()
    values = []
    for index in range(5):
        sale = _sale(
            paid_at=datetime(2026, 8, 10, index, tzinfo=UTC),
            items=(_item(uuid4(), uuid4(), f"Product {index}", 1, "6500"),),
        )
        sources.sales[sale.payment_id] = sale
        values.append(
            AnalyticsBackfillSource(
                sale.organization_id, sale.payment_id, sale.paid_at
            )
        )
    sources.payment_sources = tuple(values)
    backfill = AnalyticsBackfillService(
        AnalyticsProjectionService(repository, sources), sources, repository
    )

    first = await backfill.run(batch_size=2)
    assert first.payments == 5
    assert len(repository.sales) == 5
    assert repository.commits == 3
    second = await backfill.run(batch_size=2)
    assert second.payments == 0
    assert len(repository.sales) == 5


@pytest.mark.anyio
async def test_abc_boundaries_are_transparent_and_match_50_30_10_7_3() -> None:
    repository = QueryAnalyticsRepository()
    repository.product_rows = tuple(
        ProductAggregate(
            uuid4(),
            None,
            name,
            None,
            1,
            Decimal(revenue),
            1,
            Decimal(0),
            0,
        )
        for name, revenue in (("A", 50), ("B", 30), ("C", 10), ("D", 7), ("E", 3))
    )
    result = await AnalyticsQueryService(repository, QueryOrganizations()).abc(
        _context(MembershipRole.OWNER), date(2026, 8, 1), date(2026, 8, 10)
    )
    assert result.thresholds.a_max_cumulative_share == Decimal(80)
    assert result.thresholds.b_max_cumulative_share == Decimal(95)
    assert [(row.name, row.abc_class) for row in result.rows] == [
        ("A", ABCClass.A),
        ("B", ABCClass.A),
        ("C", ABCClass.B),
        ("D", ABCClass.C),
        ("E", ABCClass.C),
    ]
    assert [row.cumulative_share_percent for row in result.rows] == [
        Decimal("50.000000"),
        Decimal("80.000000"),
        Decimal("90.000000"),
        Decimal("97.000000"),
        Decimal("100.000000"),
    ]


@pytest.mark.anyio
async def test_menu_engineering_has_all_quadrants_and_excludes_zero_sales() -> None:
    repository = QueryAnalyticsRepository()
    values = (
        ("Hero", 40, 20),
        ("Workhorse", 30, 5),
        ("Puzzle", 15, 20),
        ("Low", 15, 5),
        ("Zero", 0, 100),
    )
    repository.product_rows = tuple(
        ProductAggregate(
            uuid4(),
            None,
            name,
            None,
            quantity,
            Decimal(100 * quantity),
            1,
            Decimal((100 - margin) * quantity),
            0,
        )
        for name, quantity, margin in values
    )
    result = await AnalyticsQueryService(
        repository, QueryOrganizations()
    ).menu_engineering(
        _context(MembershipRole.OWNER), date(2026, 8, 1), date(2026, 8, 10)
    )
    assert result.thresholds.expected_popularity_share_percent == Decimal("25.000000")
    assert result.thresholds.high_popularity_share_percent == Decimal("17.500000")
    assert result.thresholds.average_contribution_margin_per_item == Decimal(
        "13.250000"
    )
    assert {row.name: row.classification for row in result.rows} == {
        "Hero": MenuEngineeringClass.HERO,
        "Workhorse": MenuEngineeringClass.WORKHORSE,
        "Puzzle": MenuEngineeringClass.PUZZLE,
        "Low": MenuEngineeringClass.LOW_PERFORMER,
    }


@pytest.mark.anyio
async def test_manager_financial_redaction_and_financial_analytics_denial() -> None:
    repository = QueryAnalyticsRepository()
    repository.product_rows = (
        ProductAggregate(
            uuid4(),
            None,
            "Cappuccino",
            None,
            2,
            Decimal("1000"),
            1,
            Decimal("250"),
            1,
        ),
    )
    allowed_location = uuid4()
    manager = _context(MembershipRole.MANAGER)
    service = AnalyticsQueryService(
        repository, QueryOrganizations((allowed_location,))
    )
    overview = await service.overview(
        manager,
        date(2026, 8, 1),
        date(2026, 8, 10),
        allowed_location,
    )
    assert overview.revenue == Decimal("1000.000000")
    assert overview.cogs is None
    assert overview.gross_profit is None
    assert overview.gross_margin_percent is None
    assert overview.inventory_losses is None
    assert overview.incomplete_cogs_orders is None
    assert repository.last_location_scope == {allowed_location}

    products = await service.products(
        manager, date(2026, 8, 1), date(2026, 8, 10), allowed_location
    )
    assert products.rows[0].revenue == Decimal("1000.000000")
    assert products.rows[0].cogs is None
    assert products.rows[0].gross_profit is None
    assert products.rows[0].gross_margin_percent is None
    with pytest.raises(AnalyticsFinancialAccessDenied):
        await service.products(
            manager,
            date(2026, 8, 1),
            date(2026, 8, 10),
            allowed_location,
            sort_by=ProductSort.GROSS_PROFIT,
        )
    with pytest.raises(AnalyticsFinancialAccessDenied):
        await service.menu_engineering(
            manager,
            date(2026, 8, 1),
            date(2026, 8, 10),
            allowed_location,
        )


@pytest.mark.anyio
async def test_location_operating_profit_includes_losses_and_gains() -> None:
    repository = QueryAnalyticsRepository()
    location_id = uuid4()
    repository.location_rows = (
        LocationAggregate(
            location_id=location_id,
            location_name="Dostyk",
            revenue=Decimal("1000"),
            paid_orders=2,
            items_sold=3,
            cogs=Decimal("200"),
            operating_expenses=Decimal("100"),
            inventory_losses=Decimal("50"),
            inventory_gains=Decimal("10"),
        ),
    )
    result = await AnalyticsQueryService(repository, QueryOrganizations()).locations(
        _context(MembershipRole.OWNER), date(2026, 8, 1), date(2026, 8, 10)
    )
    assert result.rows[0].operating_profit == Decimal("660.000000")


@pytest.mark.anyio
async def test_analytics_api_openapi_rbac_redaction_and_tenant_location_isolation(
    app_client, monkeypatch
) -> None:
    from beanly.main import app

    paths = app.openapi()["paths"]
    assert {
        "/api/v1/analytics/overview",
        "/api/v1/analytics/products",
        "/api/v1/analytics/products/abc",
        "/api/v1/analytics/menu-engineering",
        "/api/v1/analytics/hours",
        "/api/v1/analytics/inventory-consumption",
        "/api/v1/analytics/locations",
    } <= paths.keys()

    client, sessions = app_client
    password = "correct-horse-battery-staple"
    owner = await _analytics_auth(client, "analytics-owner@example.com", password)
    workspace = await client.post(
        "/api/v1/organizations",
        headers=owner,
        json={
            "name": "Analytics Coffee",
            "country_code": "KZ",
            "currency_code": "KZT",
            "first_location": {"name": "Dostyk", "timezone": "Asia/Almaty"},
        },
    )
    assert workspace.status_code == 201, workspace.text
    organization_id = workspace.json()["organization"]["id"]
    allowed_location_id = workspace.json()["location"]["id"]
    owner_headers = {**owner, "X-Organization-ID": organization_id}
    second = await client.post(
        f"/api/v1/organizations/{organization_id}/locations",
        headers=owner_headers,
        json={"name": "Airport", "timezone": "Asia/Almaty"},
    )
    assert second.status_code == 201, second.text
    restricted_location_id = second.json()["id"]

    other_owner = await _analytics_auth(
        client, "analytics-other-owner@example.com", password
    )
    other_workspace = await client.post(
        "/api/v1/organizations",
        headers=other_owner,
        json={
            "name": "Other Analytics",
            "country_code": "KZ",
            "currency_code": "KZT",
            "first_location": {"name": "Other", "timezone": "UTC"},
        },
    )
    assert other_workspace.status_code == 201, other_workspace.text
    foreign_location_id = other_workspace.json()["location"]["id"]

    tokens = iter(
        (
            "analytics-manager-token-with-more-than-thirty-two-characters",
            "analytics-cashier-token-with-more-than-thirty-two-characters",
            "analytics-barista-token-with-more-than-thirty-two-characters",
        )
    )

    def token_pair() -> tuple[str, str]:
        token = next(tokens)
        return token, sha256(token.encode()).hexdigest()

    monkeypatch.setattr(
        "beanly.modules.organizations.application.services.invitation_service."
        "create_invitation_token",
        token_pair,
    )
    member_headers = {}
    for role in ("MANAGER", "CASHIER", "BARISTA"):
        email = f"analytics-{role.lower()}@example.com"
        auth = await _analytics_auth(client, email, password)
        token = f"analytics-{role.lower()}-token-with-more-than-thirty-two-characters"
        await _analytics_invite(
            client,
            owner_headers,
            auth,
            email,
            role,
            allowed_location_id,
            token,
        )
        member_headers[role] = {**auth, "X-Organization-ID": organization_id}

    local_date = date(2026, 8, 11)
    now = datetime(2026, 8, 11, 2, tzinfo=UTC)
    allowed_product_id = uuid4()
    async with sessions() as session:
        for location_id, revenue in (
            (UUID(allowed_location_id), Decimal("100")),
            (UUID(restricted_location_id), Decimal("900")),
        ):
            session.add(
                AnalyticsSalesDailyModel(
                    organization_id=UUID(organization_id),
                    location_id=location_id,
                    local_date=local_date,
                    timezone="Asia/Almaty",
                    currency_code="KZT",
                    revenue_amount=revenue,
                    paid_orders=1,
                    items_sold=2,
                    cogs_amount=Decimal("20"),
                    incomplete_cogs_orders=1,
                    dine_in_orders=1,
                    takeaway_orders=0,
                    delivery_orders=0,
                    updated_at=now,
                )
            )
            session.add(
                AnalyticsLocationMetricsDailyModel(
                    organization_id=UUID(organization_id),
                    location_id=location_id,
                    local_date=local_date,
                    revenue_amount=revenue,
                    paid_orders=1,
                    items_sold=2,
                    cogs_amount=Decimal("20"),
                    operating_expenses=Decimal("5"),
                    inventory_losses=Decimal("3"),
                    inventory_gains=Decimal("1"),
                    incomplete_cogs_orders=1,
                    updated_at=now,
                )
            )
            session.add(
                AnalyticsProductSalesDailyModel(
                    organization_id=UUID(organization_id),
                    location_id=location_id,
                    local_date=local_date,
                    product_id=(
                        allowed_product_id
                        if location_id == UUID(allowed_location_id)
                        else uuid4()
                    ),
                    product_variant_id=uuid4(),
                    product_name=f"Product {revenue}",
                    variant_name="Regular",
                    quantity_sold=2,
                    orders_count=1,
                    revenue_amount=revenue,
                    cogs_amount=Decimal("20"),
                    incomplete_cogs_orders=1,
                    updated_at=now,
                )
            )
        session.add(
            AnalyticsProductSalesDailyModel(
                organization_id=UUID(organization_id),
                location_id=UUID(allowed_location_id),
                local_date=local_date,
                product_id=allowed_product_id,
                product_variant_id=uuid4(),
                product_name="Product 100",
                variant_name="Large",
                quantity_sold=1,
                orders_count=1,
                revenue_amount=Decimal("50"),
                cogs_amount=Decimal("10"),
                incomplete_cogs_orders=0,
                updated_at=now,
            )
        )
        session.add(
            AnalyticsProjectionReceiptModel(
                projection_name="SALE_ANALYTICS",
                source_type="PAYMENT",
                source_id=uuid4(),
                organization_id=UUID(organization_id),
                source_event_id=uuid4(),
                source_occurred_at=now,
                projected_at=now,
            )
        )
        await session.commit()

    query = {"date_from": "2026-08-11", "date_to": "2026-08-11"}
    owner_overview = await client.get(
        "/api/v1/analytics/overview", headers=owner_headers, params=query
    )
    assert owner_overview.status_code == 200, owner_overview.text
    assert owner_overview.json()["revenue"] == "1000.000000"
    assert owner_overview.json()["cogs"] == "40.000000"
    assert owner_overview.json()["data_as_of"] is not None

    manager_overview = await client.get(
        "/api/v1/analytics/overview",
        headers=member_headers["MANAGER"],
        params=query,
    )
    assert manager_overview.status_code == 200, manager_overview.text
    manager_json = manager_overview.json()
    assert manager_json["revenue"] == "100.000000"
    for field in (
        "cogs",
        "gross_profit",
        "gross_margin_percent",
        "inventory_losses",
        "incomplete_cogs_orders",
    ):
        assert manager_json[field] is None

    manager_products = await client.get(
        "/api/v1/analytics/products",
        headers=member_headers["MANAGER"],
        params=query,
    )
    assert manager_products.status_code == 200, manager_products.text
    assert len(manager_products.json()["rows"]) == 1
    assert manager_products.json()["rows"][0]["quantity_sold"] == 3
    assert manager_products.json()["rows"][0]["revenue"] == "150.000000"
    assert manager_products.json()["rows"][0]["cogs"] is None
    assert manager_products.json()["rows"][0]["gross_profit"] is None
    manager_variants = await client.get(
        "/api/v1/analytics/products",
        headers=member_headers["MANAGER"],
        params={**query, "group_by": "VARIANT"},
    )
    assert manager_variants.status_code == 200, manager_variants.text
    assert len(manager_variants.json()["rows"]) == 2
    assert all(
        row["product_variant_id"] is not None
        for row in manager_variants.json()["rows"]
    )

    gross_profit_sort = await client.get(
        "/api/v1/analytics/products",
        headers=member_headers["MANAGER"],
        params={**query, "sort_by": "GROSS_PROFIT"},
    )
    assert gross_profit_sort.status_code == 403
    menu = await client.get(
        "/api/v1/analytics/menu-engineering",
        headers=member_headers["MANAGER"],
        params=query,
    )
    assert menu.status_code == 403

    locations = await client.get(
        "/api/v1/analytics/locations",
        headers=member_headers["MANAGER"],
        params=query,
    )
    assert locations.status_code == 200, locations.text
    assert {row["location_id"] for row in locations.json()["rows"]} == {
        allowed_location_id
    }
    assert locations.json()["rows"][0]["operating_profit"] is None

    inaccessible = await client.get(
        "/api/v1/analytics/overview",
        headers=member_headers["MANAGER"],
        params={**query, "location_id": restricted_location_id},
    )
    assert inaccessible.status_code == 404
    foreign = await client.get(
        "/api/v1/analytics/overview",
        headers=owner_headers,
        params={**query, "location_id": foreign_location_id},
    )
    assert foreign.status_code == 404

    for role in ("CASHIER", "BARISTA"):
        denied = await client.get(
            "/api/v1/analytics/overview",
            headers=member_headers[role],
            params=query,
        )
        assert denied.status_code == 403


async def _analytics_auth(client, email: str, password: str) -> dict[str, str]:
    created = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": password,
            "first_name": "Analytics",
            "last_name": "Tester",
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200, login.text
    return {"authorization": f"Bearer {login.json()['access_token']}"}


async def _analytics_invite(
    client,
    owner_headers,
    member_headers,
    email,
    role,
    location_id,
    token,
) -> None:
    invited = await client.post(
        "/api/v1/team/invitations",
        headers=owner_headers,
        json={"email": email, "role": role, "location_ids": [location_id]},
    )
    assert invited.status_code == 201, invited.text
    accepted = await client.post(
        f"/api/v1/invitations/{token}/accept", headers=member_headers
    )
    assert accepted.status_code == 204, accepted.text


def test_analytics_query_repository_does_not_import_operational_fact_models() -> None:
    root = Path("beanly/modules/analytics")
    assert {
        "api/router.py",
        "api/schemas.py",
        "api/dependencies.py",
        "application/analytics_query_service.py",
        "application/projection_service.py",
        "application/backfill_service.py",
        "application/source_ports.py",
        "application/dto.py",
        "infrastructure/db/models.py",
        "infrastructure/db/repositories.py",
        "infrastructure/source_reader.py",
        "infrastructure/handlers.py",
    } <= {str(path.relative_to(root)).replace("\\", "/") for path in root.rglob("*.py")}
    for path in root.rglob("*.py"):
        source_text = path.read_text(encoding="utf-8")
        assert "MATERIALIZED VIEW" not in source_text.upper(), path
        assert "asyncio.gather" not in source_text, path
    for path in (root / "application").glob("*.py"):
        assert ".infrastructure.db.models" not in path.read_text(encoding="utf-8"), path

    source = Path(
        "beanly/modules/analytics/infrastructure/db/repositories.py"
    ).read_text(encoding="utf-8")
    forbidden = (
        "modules.sales.infrastructure.db.models",
        "modules.payments.infrastructure.db.models",
        "modules.inventory.infrastructure.db.models",
        "modules.finance.infrastructure.db.models",
    )
    assert all(value not in source for value in forbidden)
    assert "core.events.outbox" not in Path(
        "beanly/modules/analytics/infrastructure/source_reader.py"
    ).read_text(encoding="utf-8")
    assert "core.events.outbox" not in Path(
        "beanly/modules/analytics/application/backfill_service.py"
    ).read_text(encoding="utf-8")
    worker = Path("beanly/core/events/worker.py").read_text(encoding="utf-8")
    assert worker.index("register_finance_handlers(") < worker.index(
        "register_analytics_handlers("
    )
