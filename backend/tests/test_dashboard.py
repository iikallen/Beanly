from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import event

from beanly.modules.dashboard.application.dashboard_query_service import (
    DashboardQueryService,
)
from beanly.modules.dashboard.application.dto import (
    ActiveInventoryCount,
    FinanceSnapshot,
    InventoryHealth,
    LocationFinanceRow,
    LocationSalesRow,
    NegativeStockItem,
    PaymentMixRow,
    SalesAggregate,
    ScopeLocation,
    TrendPoint,
)
from beanly.modules.dashboard.application.period_service import (
    InvalidDashboardPeriod,
    PeriodService,
)
from beanly.modules.dashboard.domain.enums import DashboardPeriod, TrendBucket
from beanly.modules.dashboard.infrastructure.payments_gateway import (
    PaymentsDashboardGateway,
)
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.organizations.domain.enums import LocationAccess, MembershipRole
from beanly.modules.organizations.domain.permissions import permissions_for
from beanly.modules.payments.application.reporting_service import (
    PaymentsReportingService,
)
from beanly.modules.payments.infrastructure.db.models import (
    PaymentLineModel,
    PaymentModel,
)
from beanly.modules.payments.infrastructure.db.repositories import (
    SqlAlchemyPaymentRepository,
)


def test_dashboard_contract_and_modular_boundaries() -> None:
    from beanly.main import app

    path = app.openapi()["paths"]["/api/v1/dashboard/overview"]
    assert "get" in path
    dashboard = Path("beanly/modules/dashboard")
    assert dashboard.is_dir()
    for source_path in dashboard.rglob("*.py"):
        source = source_path.read_text(encoding="utf-8")
        assert ".infrastructure.db.models" not in source, source_path
        assert "__tablename__" not in source, source_path
        assert "op.create_table" not in source, source_path
        assert "MATERIALIZED VIEW" not in source.upper(), source_path
        assert "asyncio.gather" not in source, source_path

    for module in ("sales", "payments", "inventory"):
        assert Path(
            f"beanly/modules/{module}/application/reporting_service.py"
        ).is_file()


@pytest.mark.parametrize(
    ("period", "current_from", "current_to", "previous_from", "previous_to", "bucket"),
    [
        (
            DashboardPeriod.TODAY,
            datetime(2026, 8, 9, 19, tzinfo=UTC),
            datetime(2026, 8, 10, 10, 15, tzinfo=UTC),
            datetime(2026, 8, 8, 19, tzinfo=UTC),
            datetime(2026, 8, 9, 10, 15, tzinfo=UTC),
            TrendBucket.HOUR,
        ),
        (
            DashboardPeriod.YESTERDAY,
            datetime(2026, 8, 8, 19, tzinfo=UTC),
            datetime(2026, 8, 9, 19, tzinfo=UTC),
            datetime(2026, 8, 7, 19, tzinfo=UTC),
            datetime(2026, 8, 8, 19, tzinfo=UTC),
            TrendBucket.HOUR,
        ),
        (
            DashboardPeriod.LAST_7_DAYS,
            datetime(2026, 8, 3, 19, tzinfo=UTC),
            datetime(2026, 8, 10, 10, 15, tzinfo=UTC),
            datetime(2026, 7, 28, 3, 45, tzinfo=UTC),
            datetime(2026, 8, 3, 19, tzinfo=UTC),
            TrendBucket.DAY,
        ),
        (
            DashboardPeriod.THIS_MONTH,
            datetime(2026, 7, 31, 19, tzinfo=UTC),
            datetime(2026, 8, 10, 10, 15, tzinfo=UTC),
            datetime(2026, 7, 22, 3, 45, tzinfo=UTC),
            datetime(2026, 7, 31, 19, tzinfo=UTC),
            TrendBucket.DAY,
        ),
    ],
)
def test_periods_resolve_in_location_timezone_with_equal_previous_duration(
    period,
    current_from,
    current_to,
    previous_from,
    previous_to,
    bucket,
) -> None:
    resolved = PeriodService().resolve(
        period,
        "Asia/Almaty",
        now=datetime(2026, 8, 10, 10, 15, tzinfo=UTC),
    )

    assert resolved.timezone == "Asia/Almaty"
    assert resolved.current.date_from == current_from
    assert resolved.current.date_to == current_to
    assert resolved.previous.date_from == previous_from
    assert resolved.previous.date_to == previous_to
    assert resolved.bucket is bucket
    if period not in {DashboardPeriod.TODAY, DashboardPeriod.YESTERDAY}:
        assert resolved.current.date_to - resolved.current.date_from == (
            resolved.previous.date_to - resolved.previous.date_from
        )


def test_custom_period_is_inclusive_and_limited_to_ninety_days() -> None:
    service = PeriodService()
    resolved = service.resolve(
        DashboardPeriod.CUSTOM,
        "Asia/Almaty",
        date_from=date(2026, 8, 1),
        date_to=date(2026, 8, 3),
        now=datetime(2026, 8, 10, tzinfo=UTC),
    )

    assert resolved.current.date_from == datetime(2026, 7, 31, 19, tzinfo=UTC)
    assert resolved.current.date_to == datetime(2026, 8, 3, 19, tzinfo=UTC)
    assert resolved.previous.date_to == resolved.current.date_from
    assert resolved.previous.date_to - resolved.previous.date_from == timedelta(days=3)
    assert resolved.bucket is TrendBucket.DAY

    service.resolve(
        DashboardPeriod.CUSTOM,
        "UTC",
        date_from=date(2026, 1, 1),
        date_to=date(2026, 3, 31),
    )
    with pytest.raises(InvalidDashboardPeriod, match="90 days"):
        service.resolve(
            DashboardPeriod.CUSTOM,
            "UTC",
            date_from=date(2026, 1, 1),
            date_to=date(2026, 4, 1),
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"date_from": date(2026, 8, 2), "date_to": date(2026, 8, 1)},
    ],
)
def test_custom_period_rejects_missing_or_reversed_dates(kwargs) -> None:
    with pytest.raises(InvalidDashboardPeriod):
        PeriodService().resolve(DashboardPeriod.CUSTOM, "UTC", **kwargs)


def test_non_custom_period_rejects_custom_dates_and_invalid_clock_inputs() -> None:
    service = PeriodService()
    with pytest.raises(InvalidDashboardPeriod, match="only valid for CUSTOM"):
        service.resolve(
            DashboardPeriod.TODAY,
            "UTC",
            date_from=date(2026, 8, 1),
        )
    with pytest.raises(InvalidDashboardPeriod, match="timezone"):
        service.resolve(DashboardPeriod.TODAY, "Mars/Olympus")
    with pytest.raises(InvalidDashboardPeriod, match="timezone"):
        service.resolve(
            DashboardPeriod.TODAY,
            "UTC",
            now=datetime(2026, 8, 10),
        )


@pytest.mark.parametrize(
    ("now", "expected_hours"),
    [
        (datetime(2026, 3, 9, 12, tzinfo=UTC), 23),
        (datetime(2026, 11, 2, 12, tzinfo=UTC), 25),
    ],
)
def test_dst_business_day_and_hourly_buckets_are_real_utc_hours(
    now: datetime, expected_hours: int
) -> None:
    service = PeriodService()
    resolved = service.resolve(
        DashboardPeriod.YESTERDAY,
        "America/New_York",
        now=now,
    )
    buckets = service.buckets(resolved)

    assert resolved.current.date_to - resolved.current.date_from == timedelta(
        hours=expected_hours
    )
    assert len(buckets) == expected_hours
    assert buckets[0][0] == resolved.current.date_from
    assert buckets[-1][1] == resolved.current.date_to
    assert all(end - start == timedelta(hours=1) for start, end in buckets)
    assert all(
        left[1] == right[0]
        for left, right in zip(buckets, buckets[1:], strict=False)
    )


@pytest.mark.anyio
async def test_dashboard_rbac_finance_redaction_and_selected_location_isolation(
    app_client, monkeypatch
) -> None:
    client, _ = app_client
    password = "correct-horse-battery-staple"
    owner = await _auth(client, "dashboard-owner@example.com", password)
    workspace = await client.post(
        "/api/v1/organizations",
        headers=owner,
        json={
            "name": "Dashboard Coffee",
            "country_code": "KZ",
            "currency_code": "KZT",
            "first_location": {"name": "Dostyk", "timezone": "Asia/Almaty"},
        },
    )
    assert workspace.status_code == 201, workspace.text
    organization_id = workspace.json()["organization"]["id"]
    allowed_location_id = workspace.json()["location"]["id"]
    owner_headers = {**owner, "X-Organization-ID": organization_id}
    forbidden = await client.post(
        f"/api/v1/organizations/{organization_id}/locations",
        headers=owner_headers,
        json={"name": "Airport", "timezone": "Asia/Almaty"},
    )
    assert forbidden.status_code == 201, forbidden.text
    forbidden_location_id = forbidden.json()["id"]

    tokens = iter(
        (
            "dashboard-manager-token-with-more-than-thirty-two-characters",
            "dashboard-cashier-token-with-more-than-thirty-two-characters",
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
    manager = await _auth(client, "dashboard-manager@example.com", password)
    cashier = await _auth(client, "dashboard-cashier@example.com", password)
    await _invite(
        client,
        owner_headers,
        manager,
        "dashboard-manager@example.com",
        "MANAGER",
        allowed_location_id,
        "dashboard-manager-token-with-more-than-thirty-two-characters",
    )
    await _invite(
        client,
        owner_headers,
        cashier,
        "dashboard-cashier@example.com",
        "CASHIER",
        allowed_location_id,
        "dashboard-cashier-token-with-more-than-thirty-two-characters",
    )
    manager_headers = {**manager, "X-Organization-ID": organization_id}
    cashier_headers = {**cashier, "X-Organization-ID": organization_id}

    owner_result = await client.get(
        "/api/v1/dashboard/overview",
        headers=owner_headers,
        params={"location_id": allowed_location_id},
    )
    assert owner_result.status_code == 200, owner_result.text
    assert owner_result.json()["finance"] is not None

    manager_result = await client.get(
        "/api/v1/dashboard/overview",
        headers=manager_headers,
        params={"location_id": allowed_location_id},
    )
    assert manager_result.status_code == 200, manager_result.text
    assert manager_result.json()["sales"] is not None
    assert manager_result.json()["inventory"] is not None
    assert manager_result.json()["finance"] is None
    assert all(
        alert["code"] != "INCOMPLETE_COGS"
        for alert in manager_result.json()["alerts"]
    )

    forbidden_result = await client.get(
        "/api/v1/dashboard/overview",
        headers=manager_headers,
        params={"location_id": forbidden_location_id},
    )
    assert forbidden_result.status_code == 404
    all_locations = await client.get(
        "/api/v1/dashboard/overview", headers=manager_headers
    )
    assert all_locations.status_code == 200, all_locations.text
    assert {row["location_id"] for row in all_locations.json()["locations"]} == {
        allowed_location_id
    }

    cashier_result = await client.get(
        "/api/v1/dashboard/overview", headers=cashier_headers
    )
    assert cashier_result.status_code == 403


async def _auth(client, email: str, password: str) -> dict[str, str]:
    created = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": password,
            "first_name": "Dashboard",
            "last_name": "Tester",
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200, login.text
    return {"authorization": f"Bearer {login.json()['access_token']}"}


async def _invite(
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


@pytest.mark.anyio
async def test_dashboard_composes_finance_snapshot_alerts_and_unallocated_expenses() -> None:
    dostyk = ScopeLocation(uuid4(), "Dostyk", "Asia/Almaty", True)
    airport = ScopeLocation(uuid4(), "Airport", "Asia/Almaty", False)
    current_sales = SalesAggregate(Decimal("120000"), 3)
    previous_sales = SalesAggregate(Decimal("100000"), 0)
    sales = _SalesPort((current_sales, previous_sales), (dostyk, airport))
    finance = _FinancePort(dostyk.id, airport.id)
    inventory = _InventoryPort(dostyk.id)
    service = DashboardQueryService(
        _OrganizationPort((dostyk, airport)),
        sales,
        _PaymentsPort(),
        inventory,
        finance,
    )

    result = await service.overview(
        _context(MembershipRole.OWNER),
        DashboardPeriod.TODAY,
        now=datetime(2026, 8, 10, 10, tzinfo=UTC),
    )

    assert result.sales.revenue.current == Decimal("120000")
    assert result.sales.revenue.previous == Decimal("100000")
    assert result.sales.revenue.percent_change == Decimal("20.00")
    assert result.sales.paid_orders.percent_change is None
    assert result.sales.average_check.current == Decimal("40000.000000")
    assert result.sales.average_check.percent_change is None
    assert result.finance is not None
    assert result.finance.cogs == Decimal("3000")
    assert result.finance.gross_profit == Decimal("7777")
    assert result.finance.operating_expenses == Decimal("2000")
    assert result.finance.operating_profit == Decimal("4500")
    assert result.finance.operating_profit_comparison.percent_change is None
    assert {alert.code for alert in result.alerts} == {
        "NEGATIVE_STOCK",
        "INCOMPLETE_COGS",
        "INVENTORY_COUNT_IN_PROGRESS",
    }
    assert [(row.method, row.amount, row.share_percent) for row in result.payment_mix] == [
        ("CARD", Decimal("7500"), Decimal("75.00")),
        ("CASH", Decimal("2500"), Decimal("25.00")),
    ]
    assert [row.revenue for row in result.trend] == [Decimal("120000"), Decimal(0)]
    assert {row.location_id for row in result.locations} == {dostyk.id, airport.id}
    assert sum(
        (row.operating_profit or Decimal(0) for row in result.locations), Decimal(0)
    ) == Decimal("5000")
    assert result.finance.operating_profit == Decimal("4500")
    assert all(row.location_id is not None for row in result.locations)


@pytest.mark.anyio
async def test_manager_finance_is_never_called_or_leaked_and_scope_stays_selected() -> None:
    allowed = ScopeLocation(uuid4(), "Dostyk", "Asia/Almaty", True)
    sales = _SalesPort(
        (SalesAggregate(Decimal(0), 0), SalesAggregate(Decimal(0), 0)),
        (allowed,),
    )
    finance = _ForbiddenFinancePort()
    service = DashboardQueryService(
        _OrganizationPort((allowed,)),
        sales,
        _PaymentsPort(),
        _InventoryPort(allowed.id, incomplete_finance_signal=True),
        finance,
    )

    result = await service.overview(
        _context(MembershipRole.MANAGER),
        DashboardPeriod.TODAY,
        now=datetime(2026, 8, 10, 10, tzinfo=UTC),
    )

    assert result.finance is None
    assert all(alert.code != "INCOMPLETE_COGS" for alert in result.alerts)
    assert sales.seen_location_ids and set(sales.seen_location_ids) == {(allowed.id,)}


def _context(role: MembershipRole) -> TenantContext:
    return TenantContext(
        uuid4(),
        uuid4(),
        uuid4(),
        role,
        permissions_for(role),
        LocationAccess.ALL if role is MembershipRole.OWNER else LocationAccess.SELECTED,
    )


class _OrganizationPort:
    def __init__(self, locations) -> None:
        self._locations = locations

    async def locations(self, _context):
        return self._locations

    async def reporting_timezone(self, _context):
        return next(value.timezone for value in self._locations if value.is_primary)


class _SalesPort:
    def __init__(self, summaries, locations) -> None:
        self._summaries = iter(summaries)
        self._locations = locations
        self.seen_location_ids = []

    async def summary(self, _organization_id, location_ids, _date_from, _date_to):
        self.seen_location_ids.append(location_ids)
        return next(self._summaries)

    async def operations(self, _organization_id, location_ids):
        self.seen_location_ids.append(location_ids)
        return 2, 1

    async def trend(self, _organization_id, location_ids, buckets):
        self.seen_location_ids.append(location_ids)
        return (
            TrendPoint(buckets[0][0], Decimal("120000"), 3),
            TrendPoint(buckets[1][0], Decimal(0), 0),
        )

    async def locations(
        self, _organization_id, location_ids, _date_from, _date_to
    ):
        self.seen_location_ids.append(location_ids)
        return tuple(
            LocationSalesRow(value.id, Decimal("60000"), 2)
            for value in self._locations
        )


class _PaymentsPort:
    async def mix(self, _organization_id, _location_ids, _date_from, _date_to):
        return (
            PaymentMixRow("CARD", Decimal("7500"), Decimal("75.00")),
            PaymentMixRow("CASH", Decimal("2500"), Decimal("25.00")),
        )


class _InventoryPort:
    def __init__(self, location_id, *, incomplete_finance_signal=False) -> None:
        self.location_id = location_id
        self.incomplete_finance_signal = incomplete_finance_signal

    async def health(self, _organization_id, _location_ids):
        return InventoryHealth(Decimal("1000"), 2, 1)

    async def negative_items(self, _organization_id, _location_ids, _limit):
        return (
            NegativeStockItem(
                uuid4(), self.location_id, "Coffee", Decimal("-1"), "g"
            ),
        )

    async def active_counts(self, _organization_id, _location_ids):
        return (ActiveInventoryCount(uuid4(), self.location_id, "IC-00042"),)


class _FinancePort:
    def __init__(self, first_location_id, second_location_id) -> None:
        self.first_location_id = first_location_id
        self.second_location_id = second_location_id

    async def snapshot(self, _context, _date_from, _date_to, _location_id):
        return FinanceSnapshot(
            "KZT",
            Decimal("3000"),
            Decimal("7777"),
            Decimal("70.00"),
            Decimal("2000"),
            Decimal("500"),
            Decimal(0),
            Decimal("4500"),
            3,
            12345,
            datetime(2026, 8, 10, 9, tzinfo=UTC),
        )

    async def operating_profit(self, _context, _date_from, _date_to, _location_id):
        return Decimal(0)

    async def locations(self, _context, _date_from, _date_to):
        return (
            LocationFinanceRow(self.first_location_id, Decimal("3000")),
            LocationFinanceRow(self.second_location_id, Decimal("2000")),
            LocationFinanceRow(None, Decimal("-500")),
        )


class _ForbiddenFinancePort:
    def __getattr__(self, name):
        async def forbidden(*_args, **_kwargs):
            raise AssertionError(f"Manager must not call finance.{name}")

        return forbidden


@pytest.mark.anyio
async def test_payment_reporting_kpis_trend_and_mix_use_exact_aggregates(
    app_client,
) -> None:
    _, sessions = app_client
    organization_id = uuid4()
    location_id = uuid4()
    shift_id = uuid4()
    user_id = uuid4()
    payments = [
        _payment(
            organization_id,
            location_id,
            shift_id,
            user_id,
            amount_minor=200_000,
            completed_at=datetime(2026, 8, 10, 9, 12, tzinfo=UTC),
            lines=(("CARD", 150_000), ("CASH", 50_000)),
        ),
        _payment(
            organization_id,
            location_id,
            shift_id,
            user_id,
            amount_minor=300_000,
            completed_at=datetime(2026, 8, 10, 9, 48, tzinfo=UTC),
            lines=(("CARD", 300_000),),
        ),
        _payment(
            organization_id,
            location_id,
            shift_id,
            user_id,
            amount_minor=500_000,
            completed_at=datetime(2026, 8, 10, 11, 3, tzinfo=UTC),
            lines=(("OTHER", 500_000),),
        ),
    ]
    buckets = tuple(
        (
            datetime(2026, 8, 10, hour, tzinfo=UTC),
            datetime(2026, 8, 10, hour + 1, tzinfo=UTC),
        )
        for hour in (9, 10, 11)
    )

    async with sessions() as session:
        session.add_all(payments)
        await session.commit()
        service = PaymentsReportingService(SqlAlchemyPaymentRepository(session))

        summary = await service.sales_summary(
            organization_id,
            (location_id,),
            buckets[0][0],
            buckets[-1][1],
        )
        trend = await service.sales_trend(organization_id, (location_id,), buckets)
        mix = await service.payment_mix(
            organization_id,
            (location_id,),
            buckets[0][0],
            buckets[-1][1],
        )
        dashboard_mix = await PaymentsDashboardGateway(service).mix(
            organization_id,
            (location_id,),
            buckets[0][0],
            buckets[-1][1],
        )

    assert summary.revenue == Decimal("10000")
    assert summary.paid_orders == 3
    assert (summary.revenue / summary.paid_orders).quantize(Decimal("0.000001")) == (
        Decimal("3333.333333")
    )
    assert [(row.revenue, row.orders) for row in trend] == [
        (Decimal("5000"), 2),
        (Decimal("0"), 0),
        (Decimal("5000"), 1),
    ]
    assert [(row.method, row.amount) for row in mix] == [
        ("CARD", Decimal("4500")),
        ("CASH", Decimal("500")),
        ("OTHER", Decimal("5000")),
    ]
    assert [(row.method, row.share_percent) for row in dashboard_mix] == [
        ("CARD", Decimal("45.00")),
        ("CASH", Decimal("5.00")),
        ("OTHER", Decimal("50.00")),
    ]


@pytest.mark.anyio
async def test_empty_payment_trend_zero_fills_every_bucket(app_client) -> None:
    _, sessions = app_client
    buckets = (
        (
            datetime(2026, 8, 10, 9, tzinfo=UTC),
            datetime(2026, 8, 10, 10, tzinfo=UTC),
        ),
        (
            datetime(2026, 8, 10, 10, tzinfo=UTC),
            datetime(2026, 8, 10, 11, tzinfo=UTC),
        ),
    )
    async with sessions() as session:
        rows = await PaymentsReportingService(
            SqlAlchemyPaymentRepository(session)
        ).sales_trend(uuid4(), (uuid4(),), buckets)

    assert [(row.revenue, row.orders) for row in rows] == [
        (Decimal(0), 0),
        (Decimal(0), 0),
    ]


@pytest.mark.anyio
async def test_dashboard_payment_aggregation_has_bounded_queries_and_loads_no_entities(
    app_client,
) -> None:
    _, sessions = app_client
    organization_id = uuid4()
    location_id = uuid4()
    shift_id = uuid4()
    user_id = uuid4()
    period = (
        datetime(2026, 8, 10, tzinfo=UTC),
        datetime(2026, 8, 11, tzinfo=UTC),
    )

    async with sessions() as session:
        session.add(
            _payment(
                organization_id,
                location_id,
                shift_id,
                user_id,
                amount_minor=100,
                completed_at=period[0],
                lines=(("CARD", 100),),
            )
        )
        await session.commit()
        repository = SqlAlchemyPaymentRepository(session)

        first_queries, first_entities = await _measure_summary(
            session, repository, organization_id, location_id, period
        )
        session.add_all(
            _payment(
                organization_id,
                location_id,
                shift_id,
                user_id,
                amount_minor=100,
                completed_at=period[0],
                lines=(("CARD", 100),),
            )
            for _ in range(99)
        )
        await session.commit()
        second_queries, second_entities = await _measure_summary(
            session, repository, organization_id, location_id, period
        )

    assert first_queries == second_queries == 1
    assert first_entities == second_entities == 0


async def _measure_summary(session, repository, organization_id, location_id, period):
    queries = 0
    entities = 0

    def count_query(*_args) -> None:
        nonlocal queries
        queries += 1

    def count_entity(*_args) -> None:
        nonlocal entities
        entities += 1

    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", count_query)
    event.listen(session.sync_session, "loaded_as_persistent", count_entity)
    try:
        await repository.dashboard_summary(
            organization_id, (location_id,), period[0], period[1]
        )
    finally:
        event.remove(engine, "before_cursor_execute", count_query)
        event.remove(session.sync_session, "loaded_as_persistent", count_entity)
    return queries, entities


def _payment(
    organization_id,
    location_id,
    shift_id,
    user_id,
    *,
    amount_minor,
    completed_at,
    lines,
) -> PaymentModel:
    payment_id = uuid4()
    return PaymentModel(
        id=payment_id,
        organization_id=organization_id,
        location_id=location_id,
        order_id=uuid4(),
        shift_id=shift_id,
        client_payment_id=uuid4(),
        currency_code="KZT",
        amount_minor=amount_minor,
        created_by_user_id=user_id,
        completed_at=completed_at,
        lines=[
            PaymentLineModel(
                id=uuid4(),
                payment_id=payment_id,
                method=method,
                amount_minor=line_amount,
                cash_received_minor=line_amount if method == "CASH" else None,
                change_minor=0,
                sort_order=index,
            )
            for index, (method, line_amount) in enumerate(lines)
        ],
    )
