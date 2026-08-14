import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, update
from test_payments import _order, _variant, _workspace
from test_refunds_fiscal import postgres_stage21_app  # noqa: F401

from beanly.core.config.settings import get_settings
from beanly.core.events.outbox.repositories import OutboxRepository
from beanly.core.events.outbox.writer import OutboxEventSink
from beanly.core.security.audit import SecurityAuditEventModel
from beanly.modules.cash_management.application.ports import FiscalShiftReconciliation
from beanly.modules.cash_management.infrastructure.db.models import (
    CashDrawerCloseSnapshotModel,
    CashDrawerMovementModel,
    CashDrawerSessionModel,
)
from beanly.modules.cash_management.infrastructure.service import CashDrawerService
from beanly.modules.finance.application.projection_service import FinanceProjectionService
from beanly.modules.finance.infrastructure.db.models import FinanceEntryModel
from beanly.modules.finance.infrastructure.db.repositories import SqlAlchemyFinanceRepository
from beanly.modules.finance.infrastructure.source_reader import SqlAlchemyFinanceSourceReader
from beanly.modules.integrations.application.job_service import IntegrationJobService
from beanly.modules.integrations.infrastructure.crypto import FernetSecretCipher
from beanly.modules.integrations.infrastructure.db.models import IntegrationJobModel
from beanly.modules.integrations.infrastructure.db.repositories import (
    SqlAlchemyIntegrationRepository,
)
from beanly.modules.integrations.infrastructure.providers import build_provider_registry
from beanly.modules.integrations.infrastructure.source_reader import (
    SqlAlchemyIntegrationSourceReader,
)
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.organizations.domain.enums import LocationAccess, MembershipRole
from beanly.modules.organizations.domain.permissions import permissions_for
from beanly.modules.organizations.infrastructure.db.models import (
    LocationModel,
    OrganizationMembershipModel,
)
from beanly.modules.organizations.infrastructure.db.repositories import (
    SqlAlchemyOrganizationRepository,
)


def _promotion() -> dict[str, object]:
    return {
        "name": "Friends & Family",
        "pos_name": "Friends & Family",
        "application_mode": "AUTOMATIC",
        "discount_kind": "PERCENT",
        "scope": "ORDER",
        "percent_rate": "10.0000",
        "priority": 100,
        "stacking_policy": "EXCLUSIVE",
        "include_modifier_price": False,
        "all_locations": True,
        "targets": [
            {
                "role": "ELIGIBLE",
                "target_type": "ALL",
                "target_id": None,
                "quantity": 1,
                "sort_order": 0,
            }
        ],
    }


@pytest.mark.anyio
async def test_cash_close_day_exact_ledger_fiscal_finance_and_idempotency(
    postgres_stage21_app,  # noqa: F811
) -> None:
    client, sessions, _, _ = postgres_stage21_app
    headers, organization_id, location_id, warehouse_id = await _workspace(
        client, "stage26-close@example.com", "Stage 26 close"
    )
    register = await client.post(
        "/api/v1/sales/registers",
        headers=headers,
        json={"location_id": str(location_id), "name": "Front"},
    )
    assert register.status_code == 201, register.text
    register_id = register.json()["id"]
    client_open_id = str(uuid4())
    open_payload = {
        "register_id": register_id,
        "warehouse_id": str(warehouse_id),
        "starting_cash_minor": "2000000",
        "client_open_id": client_open_id,
    }
    opened = await client.post("/api/v1/sales/shifts/open", headers=headers, json=open_payload)
    replay = await client.post("/api/v1/sales/shifts/open", headers=headers, json=open_payload)
    assert opened.status_code == replay.status_code == 201
    assert opened.json() == replay.json()
    shift = opened.json()
    drawer_id = shift["drawer_session_id"]
    conflict = await client.post(
        "/api/v1/sales/shifts/open",
        headers=headers,
        json={**open_payload, "starting_cash_minor": "2000001"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "CASH_MOVEMENT_IDEMPOTENCY_CONFLICT"

    promotion = await client.post("/api/v1/promotions", headers=headers, json=_promotion())
    assert promotion.status_code == 201, promotion.text
    assert (
        await client.post(f"/api/v1/promotions/{promotion.json()['id']}/activate", headers=headers)
    ).status_code == 200
    variant_id = await _variant(client, headers, "Close coffee", 90000)
    order = await _order(client, headers, shift["id"], variant_id)
    assert (order["subtotal_minor"], order["discount_total_minor"], order["total_minor"]) == (
        "90000",
        "9000",
        "81000",
    )
    payment = await client.post(
        f"/api/v1/payments/orders/{order['id']}/complete",
        headers=headers,
        json={
            "client_payment_id": str(uuid4()),
            "lines": [{"method": "CASH", "amount_minor": 81000, "cash_received_minor": 81000}],
        },
    )
    assert payment.status_code == 201, payment.text
    payment = payment.json()
    refund = await client.post(
        "/api/v1/refunds",
        headers=headers,
        json={
            "client_refund_id": str(uuid4()),
            "payment_id": payment["id"],
            "reason": "CUSTOMER_RETURN",
            "lines": [
                {
                    "order_item_id": order["items"][0]["id"],
                    "quantity": 1,
                    "restock_quantity": 0,
                }
            ],
            "payment_lines": [
                {
                    "original_payment_line_id": payment["lines"][0]["id"],
                    "amount_minor": 81000,
                }
            ],
        },
    )
    assert refund.status_code == 201, refund.text

    async with sessions() as session:
        cash = CashDrawerService(
            session,
            OrganizationService(SqlAlchemyOrganizationRepository(session)),
        )
        await cash.project_payment(organization_id, UUID(payment["id"]))
        await cash.project_payment(organization_id, UUID(payment["id"]))
        await cash.project_refund(organization_id, UUID(refund.json()["id"]))
        await cash.project_refund(organization_id, UUID(refund.json()["id"]))
        await session.commit()

    for endpoint, amount, reason in (
        ("pay-in", "500000", "Float top-up"),
        ("pay-out", "200000", "Petty cash"),
    ):
        payload = {
            "client_movement_id": str(uuid4()),
            "amount_minor": amount,
            "reason": reason,
        }
        first = await client.post(
            f"/api/v1/cash/drawers/{drawer_id}/{endpoint}", headers=headers, json=payload
        )
        second = await client.post(
            f"/api/v1/cash/drawers/{drawer_id}/{endpoint}", headers=headers, json=payload
        )
        assert first.status_code == second.status_code == 200
        assert first.json() == second.json()

    connection = await client.post(
        "/api/v1/integrations/connections",
        headers=headers,
        json={
            "provider_code": "mock_fiscal",
            "display_name": "Close-day fiscal",
            "credentials": {"api_key": "stage26"},
        },
    )
    assert connection.status_code == 201, connection.text
    connection_id = connection.json()["id"]
    assert (
        await client.post(f"/api/v1/integrations/connections/{connection_id}/test", headers=headers)
    ).status_code == 200
    assert (
        await client.put(
            f"/api/v1/integrations/connections/{connection_id}/locations/{location_id}",
            headers=headers,
            json={"capability": "FISCAL", "settings": {}, "is_active": True},
        )
    ).status_code == 200
    route = await client.post(
        "/api/v1/fiscal/routes",
        headers=headers,
        json={
            "location_id": str(location_id),
            "register_id": register_id,
            "provider_connection_id": connection_id,
            "source_mode": "EXTERNAL_KKM",
        },
    )
    assert route.status_code == 201, route.text
    async with sessions() as session:
        await session.execute(
            update(LocationModel)
            .where(LocationModel.id == location_id)
            .values(fiscal_enforcement_mode="LIVE_REQUIRED")
        )
        await session.commit()

    x_report = await client.post(f"/api/v1/fiscal/shifts/{shift['id']}/x-report", headers=headers)
    assert x_report.status_code == 200, x_report.text
    assert x_report.json()["status"] == "PENDING"

    close_id = str(uuid4())
    close_payload = {
        "client_close_id": close_id,
        "actual_cash_minor": "2295000",
    }
    first_close = await client.post(
        f"/api/v1/cash/drawers/{drawer_id}/close", headers=headers, json=close_payload
    )
    replay_close = await client.post(
        f"/api/v1/cash/drawers/{drawer_id}/close", headers=headers, json=close_payload
    )
    assert first_close.status_code == replay_close.status_code == 409
    assert first_close.json()["detail"]["code"] == "CASH_VARIANCE_APPROVAL_REQUIRED"
    changed_close = await client.post(
        f"/api/v1/cash/drawers/{drawer_id}/close",
        headers=headers,
        json={**close_payload, "actual_cash_minor": "2295001"},
    )
    assert changed_close.status_code == 409
    assert changed_close.json()["detail"]["code"] == "CASH_CLOSE_IDEMPOTENCY_CONFLICT"
    approved = await client.post(
        f"/api/v1/cash/drawers/{drawer_id}/approve-variance",
        headers=headers,
        json={"reason": "Count verified"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["drawer"]["status"] == "CLOSING"

    async with sessions() as session:
        repository = SqlAlchemyIntegrationRepository(session)
        jobs = await repository.claim_jobs("stage26", 10, 120)
        await repository.commit()
        z_job = next(job for job in jobs if job.job_type == "FISCAL_SHIFT_Z_REPORT")
        settings = get_settings()
        worker = IntegrationJobService(
            repository,
            SqlAlchemyIntegrationSourceReader(session),
            build_provider_registry(settings),
            FernetSecretCipher(settings.integration_encryption_key_list),
            OutboxEventSink(OutboxRepository(session)),
            max_attempts=3,
        )
        for job in jobs:
            await worker.execute(job, "stage26")
        cash = CashDrawerService(
            session,
            OrganizationService(SqlAlchemyOrganizationRepository(session)),
        )
        await cash.on_integration_job(organization_id, z_job.id, dead=False)
        await session.commit()

        finance = FinanceProjectionService(
            SqlAlchemyFinanceRepository(session), SqlAlchemyFinanceSourceReader(session)
        )
        event_id = uuid4()
        await finance.apply_cash_drawer_closed(event_id, organization_id, UUID(drawer_id))
        await finance.apply_cash_drawer_closed(event_id, organization_id, UUID(drawer_id))
        await session.commit()

        drawer = await session.get(CashDrawerSessionModel, UUID(drawer_id))
        snapshot = await session.scalar(
            select(CashDrawerCloseSnapshotModel).where(
                CashDrawerCloseSnapshotModel.drawer_session_id == UUID(drawer_id)
            )
        )
        assert drawer is not None and snapshot is not None
        assert (drawer.status, snapshot.starting_cash_minor) == ("CLOSED", 2_000_000)
        assert (
            snapshot.cash_payments_minor,
            snapshot.cash_refunds_minor,
            snapshot.pay_in_minor,
            snapshot.pay_out_minor,
            snapshot.expected_cash_minor,
            snapshot.actual_cash_minor,
            snapshot.variance_minor,
        ) == (81_000, -81_000, 500_000, -200_000, 2_300_000, 2_295_000, -5_000)
        counts = dict(
            (
                await session.execute(
                    select(CashDrawerMovementModel.kind, func.count())
                    .where(CashDrawerMovementModel.drawer_session_id == UUID(drawer_id))
                    .group_by(CashDrawerMovementModel.kind)
                )
            ).all()
        )
        assert counts == {
            "OPENING_FLOAT": 1,
            "CASH_PAYMENT": 1,
            "CASH_REFUND": 1,
            "PAY_IN": 1,
            "PAY_OUT": 1,
        }
        assert (
            await session.scalar(
                select(func.count())
                .select_from(IntegrationJobModel)
                .where(
                    IntegrationJobModel.source_id == UUID(shift["id"]),
                    IntegrationJobModel.job_type == "FISCAL_SHIFT_Z_REPORT",
                    IntegrationJobModel.status == "SUCCESS",
                )
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(IntegrationJobModel)
                .where(
                    IntegrationJobModel.source_id == UUID(shift["id"]),
                    IntegrationJobModel.job_type == "FISCAL_SHIFT_X_REPORT",
                    IntegrationJobModel.status == "SUCCESS",
                )
            )
            == 1
        )
        entry = await session.scalar(
            select(FinanceEntryModel).where(
                FinanceEntryModel.source_id == UUID(drawer_id),
                FinanceEntryModel.entry_role == "CASH_OVER_SHORT",
            )
        )
        assert entry is not None and entry.amount == Decimal("-50")
        actions = set(
            await session.scalars(
                select(SecurityAuditEventModel.action).where(
                    SecurityAuditEventModel.resource_id == UUID(drawer_id)
                )
            )
        )
        assert {
            "CASH_PAY_IN",
            "CASH_PAY_OUT",
            "CASH_CLOSE_REQUESTED",
            "CASH_VARIANCE_APPROVED",
            "CASH_DRAWER_CLOSED",
        } <= actions

    report = await client.get(f"/api/v1/cash/reports/drawers/{drawer_id}", headers=headers)
    assert report.status_code == 200, report.text
    assert report.json()["summary"]["expected_cash_minor"] == "2300000"


@pytest.mark.anyio
async def test_cash_only_projection_sync_guards_and_blind_concurrent_close(
    postgres_stage21_app,  # noqa: F811
) -> None:
    client, sessions, _, _ = postgres_stage21_app
    headers, organization_id, location_id, warehouse_id = await _workspace(
        client, "stage26-blind-owner@example.com", "Stage 26 blind"
    )
    register = await client.post(
        "/api/v1/sales/registers",
        headers=headers,
        json={"location_id": str(location_id), "name": "Blind register"},
    )
    opened = await client.post(
        "/api/v1/sales/shifts/open",
        headers=headers,
        json={
            "register_id": register.json()["id"],
            "warehouse_id": str(warehouse_id),
            "starting_cash_minor": "0",
            "client_open_id": str(uuid4()),
        },
    )
    assert opened.status_code == 201, opened.text
    shift = opened.json()
    drawer_id = shift["drawer_session_id"]
    variant_id = await _variant(client, headers, "Split coffee", 100000)

    payments: list[dict[str, object]] = []
    orders: list[dict[str, object]] = []
    for lines in (
        [{"method": "CARD", "amount_minor": 100000, "reference": "card-only"}],
        [
            {"method": "CASH", "amount_minor": 40000, "cash_received_minor": 40000},
            {"method": "CARD", "amount_minor": 60000, "reference": "split-card"},
        ],
    ):
        order = await _order(client, headers, shift["id"], variant_id)
        response = await client.post(
            f"/api/v1/payments/orders/{order['id']}/complete",
            headers=headers,
            json={"client_payment_id": str(uuid4()), "lines": lines},
        )
        assert response.status_code == 201, response.text
        orders.append(order)
        payments.append(response.json())

    for order, payment in zip(orders, payments, strict=True):
        response = await client.post(
            "/api/v1/refunds",
            headers=headers,
            json={
                "client_refund_id": str(uuid4()),
                "payment_id": payment["id"],
                "reason": "CUSTOMER_RETURN",
                "lines": [
                    {
                        "order_item_id": order["items"][0]["id"],
                        "quantity": 1,
                        "restock_quantity": 0,
                    }
                ],
                "payment_lines": [
                    {
                        "original_payment_line_id": line["id"],
                        "amount_minor": line["amount_minor"],
                        "external_refund_confirmed": line["method"] == "CARD",
                    }
                    for line in payment["lines"]
                ],
            },
        )
        assert response.status_code == 201, response.text
        async with sessions() as session:
            cash = CashDrawerService(
                session,
                OrganizationService(SqlAlchemyOrganizationRepository(session)),
            )
            await cash.project_payment(organization_id, UUID(payment["id"]))
            await cash.project_refund(organization_id, UUID(response.json()["id"]))
            await session.commit()

    blocking_order = await _order(client, headers, shift["id"], variant_id)
    close_id = str(uuid4())
    blocked = await client.post(
        f"/api/v1/cash/drawers/{drawer_id}/close",
        headers=headers,
        json={"client_close_id": close_id, "actual_cash_minor": "0"},
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "SHIFT_CLOSE_SYNC_PENDING"
    assert (
        await client.post(
            f"/api/v1/sales/orders/{blocking_order['id']}/cancel",
            headers=headers,
            json={"reason": "Close day"},
        )
    ).status_code == 200
    blocked = await client.post(
        f"/api/v1/cash/drawers/{drawer_id}/close",
        headers=headers,
        json={
            "client_close_id": close_id,
            "actual_cash_minor": "0",
            "pending_offline_operations": 1,
        },
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "SHIFT_CLOSE_SYNC_PENDING"

    registered = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "stage26-cashier@example.com",
            "password": "correct-horse-battery-staple",
            "first_name": "Blind",
            "last_name": "Cashier",
        },
    )
    assert registered.status_code == 201, registered.text
    now = datetime.now(UTC)
    async with sessions() as session:
        session.add(
            OrganizationMembershipModel(
                id=uuid4(),
                organization_id=organization_id,
                user_id=UUID(registered.json()["id"]),
                role="CASHIER",
                status="ACTIVE",
                location_access="ALL",
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()
    login = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "stage26-cashier@example.com",
            "password": "correct-horse-battery-staple",
        },
    )
    cashier_headers = {
        "authorization": f"Bearer {login.json()['access_token']}",
        "X-Organization-ID": str(organization_id),
    }
    close_payload = {"client_close_id": close_id, "actual_cash_minor": "0"}

    async def close():
        return await client.post(
            f"/api/v1/cash/drawers/{drawer_id}/close",
            headers=cashier_headers,
            json=close_payload,
        )

    closed = await asyncio.gather(close(), close())
    assert [response.status_code for response in closed] == [200, 200]
    assert closed[0].json() == closed[1].json()
    for response in closed:
        value = response.json()
        assert value["expected_visible"] is False
        assert value["expected_cash_minor"] is None
        assert value["variance_minor"] is None
        assert value["drawer"]["expected_cash_minor_snapshot"] is None
        assert value["drawer"]["variance_minor"] is None
    detail = await client.get(f"/api/v1/cash/drawers/{drawer_id}", headers=cashier_headers)
    assert detail.status_code == 200
    assert detail.json()["expected_cash_minor_snapshot"] is None
    assert detail.json()["variance_minor"] is None
    other_headers, _, _, _ = await _workspace(
        client, "stage26-foreign@example.com", "Stage 26 foreign"
    )
    foreign = await client.get(f"/api/v1/cash/drawers/{drawer_id}", headers=other_headers)
    assert foreign.status_code == 404
    assert foreign.json()["detail"]["code"] == "CASH_DRAWER_NOT_FOUND"
    async with sessions() as session:
        membership = await session.scalar(
            select(OrganizationMembershipModel).where(
                OrganizationMembershipModel.organization_id == organization_id,
                OrganizationMembershipModel.user_id == UUID(registered.json()["id"]),
            )
        )
        assert membership is not None
        membership.location_access = "SELECTED"
        await session.commit()
    isolated = await client.get(f"/api/v1/cash/drawers/{drawer_id}", headers=cashier_headers)
    assert isolated.status_code == 404
    assert isolated.json()["detail"]["code"] == "CASH_DRAWER_NOT_FOUND"
    async with sessions() as session:
        movements = list(
            await session.scalars(
                select(CashDrawerMovementModel).where(
                    CashDrawerMovementModel.drawer_session_id == UUID(drawer_id)
                )
            )
        )
        assert [(row.kind, row.amount_minor) for row in movements] == [
            ("OPENING_FLOAT", 0),
            ("CASH_PAYMENT", 40000),
            ("CASH_REFUND", -40000),
        ]


class _ConfirmedReconciliation:
    async def reconcile(self, query: FiscalShiftReconciliation) -> bool | None:
        del query
        return True


@pytest.mark.anyio
async def test_unknown_z_report_requires_lookup_and_never_blindly_retries(
    postgres_stage21_app,  # noqa: F811
) -> None:
    client, sessions, _, _ = postgres_stage21_app
    headers, organization_id, location_id, warehouse_id = await _workspace(
        client, "stage26-unknown@example.com", "Stage 26 unknown"
    )
    register = await client.post(
        "/api/v1/sales/registers",
        headers=headers,
        json={"location_id": str(location_id), "name": "Unknown register"},
    )
    register_id = register.json()["id"]
    opened = await client.post(
        "/api/v1/sales/shifts/open",
        headers=headers,
        json={
            "register_id": register_id,
            "warehouse_id": str(warehouse_id),
            "starting_cash_minor": "0",
            "client_open_id": str(uuid4()),
        },
    )
    assert opened.status_code == 201, opened.text
    shift = opened.json()
    connection = await client.post(
        "/api/v1/integrations/connections",
        headers=headers,
        json={
            "provider_code": "mock_fiscal",
            "display_name": "Unknown fiscal",
            "credentials": {"api_key": "stage26", "simulate": "unknown"},
        },
    )
    connection_id = connection.json()["id"]
    assert (
        await client.post(f"/api/v1/integrations/connections/{connection_id}/test", headers=headers)
    ).status_code == 200
    assert (
        await client.put(
            f"/api/v1/integrations/connections/{connection_id}/locations/{location_id}",
            headers=headers,
            json={"capability": "FISCAL", "settings": {}, "is_active": True},
        )
    ).status_code == 200
    assert (
        await client.post(
            "/api/v1/fiscal/routes",
            headers=headers,
            json={
                "location_id": str(location_id),
                "register_id": register_id,
                "provider_connection_id": connection_id,
                "source_mode": "EXTERNAL_KKM",
            },
        )
    ).status_code == 201
    async with sessions() as session:
        await session.execute(
            update(LocationModel)
            .where(LocationModel.id == location_id)
            .values(fiscal_enforcement_mode="LIVE_REQUIRED")
        )
        await session.commit()
    closed = await client.post(
        f"/api/v1/cash/drawers/{shift['drawer_session_id']}/close",
        headers=headers,
        json={"client_close_id": str(uuid4()), "actual_cash_minor": "0"},
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["drawer"]["status"] == "CLOSING"

    async with sessions() as session:
        repository = SqlAlchemyIntegrationRepository(session)
        jobs = await repository.claim_jobs("stage26-unknown", 10, 120)
        await repository.commit()
        z_job = next(job for job in jobs if job.job_type == "FISCAL_SHIFT_Z_REPORT")
        settings = get_settings()
        worker = IntegrationJobService(
            repository,
            SqlAlchemyIntegrationSourceReader(session),
            build_provider_registry(settings),
            FernetSecretCipher(settings.integration_encryption_key_list),
            OutboxEventSink(OutboxRepository(session)),
            max_attempts=3,
        )
        await worker.execute(z_job, "stage26-unknown")
        cash = CashDrawerService(
            session,
            OrganizationService(SqlAlchemyOrganizationRepository(session)),
        )
        await cash.on_integration_job(organization_id, z_job.id, dead=True)
        await session.commit()

    status_response = await client.get(
        f"/api/v1/fiscal/shifts/{shift['id']}/status", headers=headers
    )
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "RECONCILIATION_REQUIRED"
    unresolved = await client.post(
        f"/api/v1/fiscal/shifts/{shift['id']}/reconcile", headers=headers
    )
    assert unresolved.status_code == 409
    assert unresolved.json()["detail"]["code"] == "FISCAL_SHIFT_RECONCILIATION_REQUIRED"

    async with sessions() as session:
        membership = await session.scalar(
            select(OrganizationMembershipModel).where(
                OrganizationMembershipModel.organization_id == organization_id,
                OrganizationMembershipModel.role == "OWNER",
            )
        )
        assert membership is not None
        context = TenantContext(
            membership.user_id,
            organization_id,
            membership.id,
            MembershipRole.OWNER,
            permissions_for(MembershipRole.OWNER),
            LocationAccess.ALL,
        )
        cash = CashDrawerService(
            session,
            OrganizationService(SqlAlchemyOrganizationRepository(session)),
            _ConfirmedReconciliation(),
        )
        reconciled = await cash.reconcile_fiscal(context, UUID(shift["id"]))
        assert reconciled["status"] == "COMPLETED"
        assert (
            await session.scalar(
                select(func.count())
                .select_from(IntegrationJobModel)
                .where(
                    IntegrationJobModel.source_id == UUID(shift["id"]),
                    IntegrationJobModel.job_type == "FISCAL_SHIFT_Z_REPORT",
                )
            )
            == 1
        )
        drawer = await session.get(CashDrawerSessionModel, UUID(shift["drawer_session_id"]))
        assert drawer is not None and drawer.status == "CLOSED"
