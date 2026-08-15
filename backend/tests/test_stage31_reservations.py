import asyncio
from datetime import UTC, datetime, time, timedelta
from hashlib import sha256
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select
from test_offline_pos import _workspace
from test_offline_pos import postgres_offline_app as _postgres_offline_app
from test_payments import _register_shift, _variant
from test_stage26_postgres_e2e import _promotion

from beanly.core.config.settings import get_settings
from beanly.core.events.handlers.registry import EventHandlerRegistry
from beanly.core.events.outbox.dispatcher import OutboxDispatcher
from beanly.core.events.outbox.models import OutboxEventModel
from beanly.core.events.outbox.repositories import OutboxRepository
from beanly.modules.analytics.application.projection_service import (
    AnalyticsProjectionService,
)
from beanly.modules.analytics.infrastructure.db.models import AnalyticsSalesDailyModel
from beanly.modules.analytics.infrastructure.db.repositories import (
    SqlAlchemyAnalyticsRepository,
)
from beanly.modules.analytics.infrastructure.handlers import register_analytics_handlers
from beanly.modules.analytics.infrastructure.source_reader import (
    SqlAlchemyAnalyticsSourceReader,
)
from beanly.modules.finance.application.projection_service import FinanceProjectionService
from beanly.modules.finance.infrastructure.db.models import FinanceEntryModel
from beanly.modules.finance.infrastructure.db.repositories import SqlAlchemyFinanceRepository
from beanly.modules.finance.infrastructure.handlers import register_finance_handlers
from beanly.modules.finance.infrastructure.source_reader import SqlAlchemyFinanceSourceReader
from beanly.modules.inventory.infrastructure.db.models import InventoryTransactionModel
from beanly.modules.kitchen.infrastructure.db.models import KitchenTicketModel
from beanly.modules.kitchen.infrastructure.handlers import register_kitchen_handlers
from beanly.modules.kitchen.infrastructure.service import KitchenService
from beanly.modules.online_ordering.infrastructure.handlers import (
    register_online_ordering_handlers,
)
from beanly.modules.online_ordering.infrastructure.service import OnlineOrderingService
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.infrastructure.db.repositories import (
    SqlAlchemyOrganizationRepository,
)
from beanly.modules.payments.infrastructure.db.models import PaymentModel
from beanly.modules.reservations.infrastructure.db.models import (
    DiningVisitModel,
    ReservationModel,
    WaitlistEntryModel,
)
from beanly.modules.reservations.infrastructure.handlers import register_reservation_handlers
from beanly.modules.reservations.infrastructure.service import ReservationService
from beanly.modules.sales.api.dependencies import order_service
from beanly.modules.sales.infrastructure.db.models import SalesOrderModel

postgres_stage31_app = _postgres_offline_app


def _code(response) -> str:
    return response.json()["detail"]["code"]


async def _foh_setup(
    app_fixture,
    *,
    email: str = "stage31-owner@example.com",
    slug: str = "stage-31-cafe",
    table_capacities: tuple[int, ...] = (2, 4),
):
    client, sessions, *_ = app_fixture
    headers, organization_id, location_id, _ = await _workspace(
        client, email, "Stage 31"
    )
    settings = await client.put(
        "/api/v1/reservation-settings",
        headers=headers,
        json={
            "location_id": str(location_id),
            "public_slug": slug,
            "reservations_enabled": True,
            "default_duration_minutes": 90,
            "cleanup_buffer_minutes": 15,
            "minimum_lead_minutes": 0,
            "maximum_advance_days": 30,
            "guest_cancellation_cutoff_minutes": 0,
            "maximum_party_size": 6,
            "slot_interval_minutes": 15,
            "schedules": [
                {
                    "weekday": weekday,
                    "opens_at_local": time(0, 0).isoformat(),
                    "closes_at_local": time(23, 59).isoformat(),
                }
                for weekday in range(7)
            ],
        },
    )
    assert settings.status_code == 200, settings.text
    section = await client.post(
        "/api/v1/dining-sections",
        headers=headers,
        json={"location_id": str(location_id), "name": "Main Hall", "sort_order": 1},
    )
    assert section.status_code == 201, section.text
    tables = []
    for index, capacity in enumerate(table_capacities, 1):
        table = await client.post(
            "/api/v1/dining-tables",
            headers=headers,
            json={
                "location_id": str(location_id),
                "section_id": section.json()["id"],
                "name": f"T{index}",
                "capacity": capacity,
                "sort_order": index,
            },
        )
        assert table.status_code == 201, table.text
        tables.append(table.json())
    return client, sessions, headers, organization_id, location_id, section.json(), tables


async def _slot(client, slug: str, party_size: int = 2) -> str:
    requested_date = (datetime.now(UTC) + timedelta(days=1)).date()
    response = await client.get(
        f"/api/v1/public/reservations/{slug}/availability",
        params={"date": requested_date.isoformat(), "party_size": party_size},
    )
    assert response.status_code == 200, response.text
    assert response.json()["slots"]
    return response.json()["slots"][0]["start_at"]


async def _dispatch_all(sessions) -> None:
    async with sessions() as session:
        organizations = OrganizationService(SqlAlchemyOrganizationRepository(session))
        handlers = EventHandlerRegistry()
        register_finance_handlers(
            handlers,
            FinanceProjectionService(
                SqlAlchemyFinanceRepository(session),
                SqlAlchemyFinanceSourceReader(session),
            ),
        )
        register_analytics_handlers(
            handlers,
            AnalyticsProjectionService(
                SqlAlchemyAnalyticsRepository(session),
                SqlAlchemyAnalyticsSourceReader(session),
            ),
        )
        register_kitchen_handlers(handlers, KitchenService(session, organizations))
        register_online_ordering_handlers(
            handlers, OnlineOrderingService(session, organizations, get_settings())
        )
        register_reservation_handlers(
            handlers,
            ReservationService(
                session, organizations, get_settings(), order_service(session)
            ),
        )
        dispatcher = OutboxDispatcher(
            OutboxRepository(session), handlers, "stage31-test", batch_size=100
        )
        while await dispatcher.run_once():
            pass


def _guest(start_at: str, **changes) -> dict[str, object]:
    return {
        "client_reservation_id": str(uuid4()),
        "start_at": start_at,
        "party_size": 2,
        "guest_name": "Stage 31 Guest",
        "guest_phone": "+77770000031",
        "guest_email": "guest31@example.com",
        "guest_notes": "Window if possible",
        **changes,
    }


@pytest.mark.anyio
async def test_guest_configuration_availability_privacy_tenancy_and_cancel(
    app_client, monkeypatch
) -> None:
    client, sessions, headers, organization_id, location_id, section, tables = (
        await _foh_setup(app_client, table_capacities=(2,))
    )
    assert (await client.get("/api/v1/public/reservations/stage-31-cafe")).json() == {
        "slug": "stage-31-cafe",
        "organization_name": "Stage 31",
        "location_name": "Dostyk",
        "timezone": "Asia/Almaty",
        "reservations_enabled": True,
        "minimum_lead_minutes": 0,
        "maximum_advance_days": 30,
        "maximum_party_size": 6,
        "slot_interval_minutes": 15,
    }
    listed_sections = await client.get(
        "/api/v1/dining-sections",
        headers=headers,
        params={"location_id": str(location_id)},
    )
    assert [item["id"] for item in listed_sections.json()] == [section["id"]]
    renamed_section = await client.patch(
        f"/api/v1/dining-sections/{section['id']}",
        headers=headers,
        json={"name": "Main Dining", "sort_order": 2, "is_active": False},
    )
    assert (
        renamed_section.status_code,
        renamed_section.json()["name"],
        renamed_section.json()["sort_order"],
        renamed_section.json()["is_active"],
    ) == (200, "Main Dining", 2, False)
    assert (
        await client.patch(
            f"/api/v1/dining-sections/{section['id']}",
            headers=headers,
            json={"is_active": True},
        )
    ).status_code == 200
    listed_tables = await client.get(
        "/api/v1/dining-tables",
        headers=headers,
        params={"location_id": str(location_id)},
    )
    assert [item["id"] for item in listed_tables.json()] == [tables[0]["id"]]
    updated_table = await client.patch(
        f"/api/v1/dining-tables/{tables[0]['id']}",
        headers=headers,
        json={"name": "T1A", "capacity": 2, "sort_order": 3},
    )
    assert (
        updated_table.status_code,
        updated_table.json()["name"],
        updated_table.json()["capacity"],
        updated_table.json()["sort_order"],
    ) == (200, "T1A", 2, 3)
    invalid_capacity = await client.post(
        "/api/v1/dining-tables",
        headers=headers,
        json={
            "location_id": str(location_id),
            "section_id": section["id"],
            "name": "Invalid",
            "capacity": 0,
        },
    )
    assert invalid_capacity.status_code == 422

    second_location = await client.post(
        f"/api/v1/organizations/{organization_id}/locations",
        headers=headers,
        json={"name": "Mega", "timezone": "Asia/Almaty"},
    )
    assert second_location.status_code == 201, second_location.text
    foreign_section = await client.post(
        "/api/v1/dining-sections",
        headers=headers,
        json={
            "location_id": second_location.json()["id"],
            "name": "Other Hall",
        },
    )
    assert foreign_section.status_code == 201
    cross_location = await client.post(
        "/api/v1/dining-tables",
        headers=headers,
        json={
            "location_id": str(location_id),
            "section_id": foreign_section.json()["id"],
            "name": "Wrong",
            "capacity": 2,
        },
    )
    assert cross_location.status_code == 404

    other_headers, _, other_location_id, _ = await _workspace(
        client, "stage31-other@example.com", "Other Stage 31"
    )
    assert (
        await client.get(
            "/api/v1/dining-sections",
            headers=other_headers,
            params={"location_id": str(location_id)},
        )
    ).status_code == 403
    assert (
        await client.patch(
            f"/api/v1/dining-tables/{tables[0]['id']}",
            headers=other_headers,
            json={"name": "Stolen"},
        )
    ).status_code == 404
    assert other_location_id != location_id

    token = "stage31-accountant-invite-token-more-than-thirty-two"
    monkeypatch.setattr(
        "beanly.modules.organizations.application.services.invitation_service."
        "create_invitation_token",
        lambda: (token, sha256(token.encode()).hexdigest()),
    )
    password = "correct-horse-battery-staple"
    assert (
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": "stage31-accountant@example.com",
                "password": password,
                "first_name": "No",
                "last_name": "Access",
            },
        )
    ).status_code == 201
    member_login = await client.post(
        "/api/v1/auth/login",
        json={"email": "stage31-accountant@example.com", "password": password},
    )
    member_auth = {"authorization": f"Bearer {member_login.json()['access_token']}"}
    assert (
        await client.post(
            "/api/v1/team/invitations",
            headers=headers,
            json={
                "email": "stage31-accountant@example.com",
                "role": "ACCOUNTANT",
                "location_ids": [str(location_id)],
            },
        )
    ).status_code == 201
    assert (
        await client.post(f"/api/v1/invitations/{token}/accept", headers=member_auth)
    ).status_code == 204
    accountant = {**member_auth, "X-Organization-ID": str(organization_id)}
    assert (
        await client.get(
            "/api/v1/dining-sections",
            headers=accountant,
            params={"location_id": str(location_id)},
        )
    ).status_code == 403

    start_at = await _slot(client, "stage-31-cafe")
    payload = _guest(start_at)
    created = await client.post(
        "/api/v1/public/reservations/stage-31-cafe", json=payload
    )
    assert created.status_code == 201, created.text
    public = created.json()
    assert public["status"] == "BOOKED"
    assert datetime.fromisoformat(public["start_at"].replace("Z", "+00:00")).tzinfo
    assert not {
        "id",
        "organization_id",
        "location_id",
        "dining_table_id",
        "table_name",
        "internal_notes",
    }.intersection(public)
    replay = await client.post(
        "/api/v1/public/reservations/stage-31-cafe", json=payload
    )
    assert replay.status_code == 201
    assert replay.json()["guest_access_token"] == public["guest_access_token"]
    changed = await client.post(
        "/api/v1/public/reservations/stage-31-cafe",
        json={**payload, "guest_notes": "Changed semantic request"},
    )
    assert changed.status_code == 409
    assert _code(changed) == "IDEMPOTENCY_CONFLICT"

    token_value = public["guest_access_token"]
    status_response = await client.get(
        f"/api/v1/public/reservations/status/{token_value}"
    )
    assert status_response.status_code == 200
    assert "guest_access_token" not in status_response.json()
    tampered = token_value[:-1] + ("0" if token_value[-1] != "0" else "1")
    invalid_token = await client.get(
        f"/api/v1/public/reservations/status/{tampered}"
    )
    assert invalid_token.status_code == 404
    assert _code(invalid_token) == "INVALID_GUEST_TOKEN"

    local_date = datetime.fromisoformat(
        public["start_at"].replace("Z", "+00:00")
    ).astimezone(ZoneInfo(public["timezone"])).date()
    unavailable = await client.get(
        "/api/v1/public/reservations/stage-31-cafe/availability",
        params={"date": local_date.isoformat(), "party_size": 2},
    )
    assert unavailable.status_code == 200
    remaining = {slot["start_at"] for slot in unavailable.json()["slots"]}
    assert start_at not in remaining
    busy_until = datetime.fromisoformat(start_at.replace("Z", "+00:00")) + timedelta(
        minutes=105
    )
    assert all(
        datetime.fromisoformat(slot.replace("Z", "+00:00")) >= busy_until
        for slot in remaining
    )
    cancel_url = f"/api/v1/public/reservations/status/{token_value}/cancel"
    cancelled = await client.post(cancel_url)
    cancel_replay = await client.post(cancel_url)
    assert cancelled.status_code == cancel_replay.status_code == 200
    assert cancelled.json()["status"] == cancel_replay.json()["status"] == "CANCELLED"
    released = await client.get(
        "/api/v1/public/reservations/stage-31-cafe/availability",
        params={"date": local_date.isoformat(), "party_size": 2},
    )
    assert start_at in {slot["start_at"] for slot in released.json()["slots"]}

    staff = (await client.get(
        "/api/v1/reservations",
        headers=headers,
        params={"location_id": str(location_id)},
    )).json()[0]
    invalid_transition = await client.post(
        f"/api/v1/reservations/{staff['id']}/no-show",
        headers=headers,
        json={"client_action_id": str(uuid4())},
    )
    assert invalid_transition.status_code == 409
    assert _code(invalid_transition) == "INVALID_RESERVATION_TRANSITION"
    assert (
        await client.get(
            f"/api/v1/reservations/{staff['id']}", headers=other_headers
        )
    ).status_code == 404
    async with sessions() as session:
        row = await session.scalar(select(ReservationModel))
        assert row is not None
        assert row.guest_access_token_hash != token_value
        assert len(row.guest_access_token_hash) == 64


@pytest.mark.anyio
async def test_availability_policy_errors_and_disabled_table(app_client) -> None:
    client, _, headers, _, location_id, _, tables = await _foh_setup(
        app_client,
        email="stage31-policy@example.com",
        slug="stage-31-policy",
        table_capacities=(2,),
    )
    valid = await _slot(client, "stage-31-policy")
    invalid_party = await client.get(
        "/api/v1/public/reservations/stage-31-policy/availability",
        params={"date": valid[:10], "party_size": 7},
    )
    assert invalid_party.status_code == 422
    assert _code(invalid_party) == "INVALID_PARTY_SIZE"

    no_table = await client.post(
        "/api/v1/public/reservations/stage-31-policy",
        json=_guest(valid, party_size=3),
    )
    assert no_table.status_code == 422
    assert _code(no_table) == "NO_MATCHING_TABLE"

    below_lead = datetime.now(UTC).replace(second=0, microsecond=0) - timedelta(minutes=1)
    below = await client.post(
        "/api/v1/public/reservations/stage-31-policy",
        json=_guest(below_lead.isoformat()),
    )
    assert below.status_code == 422
    assert _code(below) == "BELOW_LEAD_TIME"

    outside = datetime.now(UTC).replace(second=0, microsecond=0) + timedelta(days=31)
    horizon = await client.post(
        "/api/v1/public/reservations/stage-31-policy",
        json=_guest(outside.isoformat()),
    )
    assert horizon.status_code == 422
    assert _code(horizon) == "OUTSIDE_BOOKING_HORIZON"

    local_tomorrow = datetime.now(ZoneInfo("Asia/Almaty")).date() + timedelta(days=1)
    closing = datetime.combine(local_tomorrow, time(23, 30), ZoneInfo("Asia/Almaty"))
    closed = await client.post(
        "/api/v1/public/reservations/stage-31-policy",
        json=_guest(closing.isoformat()),
    )
    assert closed.status_code == 422
    assert _code(closed) == "LOCATION_CLOSED"

    booked = await client.post(
        "/api/v1/public/reservations/stage-31-policy", json=_guest(valid)
    )
    assert booked.status_code == 201
    booked_staff = (
        await client.get(
            "/api/v1/reservations",
            headers=headers,
            params={"location_id": str(location_id)},
        )
    ).json()[0]
    no_show_payload = {"client_action_id": str(uuid4())}
    no_show = await client.post(
        f"/api/v1/reservations/{booked_staff['id']}/no-show",
        headers=headers,
        json=no_show_payload,
    )
    no_show_replay = await client.post(
        f"/api/v1/reservations/{booked_staff['id']}/no-show",
        headers=headers,
        json=no_show_payload,
    )
    assert no_show.status_code == no_show_replay.status_code == 200
    assert no_show.json()["status"] == no_show_replay.json()["status"] == "NO_SHOW"

    staff_created = await client.post(
        "/api/v1/reservations",
        headers=headers,
        json={
            **_guest(valid),
            "location_id": str(location_id),
            "internal_notes": "Staff-only note",
        },
    )
    assert staff_created.status_code == 201
    staff_cancel_payload = {
        "client_action_id": str(uuid4()),
        "reason": "Guest called",
    }
    staff_cancel = await client.post(
        f"/api/v1/reservations/{staff_created.json()['id']}/cancel",
        headers=headers,
        json=staff_cancel_payload,
    )
    staff_cancel_replay = await client.post(
        f"/api/v1/reservations/{staff_created.json()['id']}/cancel",
        headers=headers,
        json=staff_cancel_payload,
    )
    assert staff_cancel.status_code == staff_cancel_replay.status_code == 200
    assert staff_cancel.json()["status"] == staff_cancel_replay.json()["status"] == (
        "CANCELLED"
    )

    assert (
        await client.patch(
            f"/api/v1/dining-tables/{tables[0]['id']}",
            headers=headers,
            json={"is_active": False},
        )
    ).status_code == 200
    unavailable = await client.get(
        "/api/v1/public/reservations/stage-31-policy/availability",
        params={"date": local_tomorrow.isoformat(), "party_size": 2},
    )
    assert unavailable.status_code == 200
    assert unavailable.json()["slots"] == []
    assert (
        await client.patch(
            f"/api/v1/dining-tables/{tables[0]['id']}",
            headers=headers,
            json={"is_active": True},
        )
    ).status_code == 200

    current = await client.get(
        f"/api/v1/reservation-settings/{location_id}", headers=headers
    )
    write_fields = {
        "location_id",
        "public_slug",
        "reservations_enabled",
        "default_duration_minutes",
        "cleanup_buffer_minutes",
        "minimum_lead_minutes",
        "maximum_advance_days",
        "guest_cancellation_cutoff_minutes",
        "maximum_party_size",
        "slot_interval_minutes",
        "schedules",
    }
    disabled_payload = {
        key: value for key, value in current.json().items() if key in write_fields
    }
    disabled_payload["reservations_enabled"] = False
    assert (
        await client.put(
            "/api/v1/reservation-settings", headers=headers, json=disabled_payload
        )
    ).status_code == 200
    disabled = await client.get(
        "/api/v1/public/reservations/stage-31-policy/availability",
        params={"date": local_tomorrow.isoformat(), "party_size": 2},
    )
    assert disabled.status_code == 422
    assert _code(disabled) == "RESERVATIONS_DISABLED"


@pytest.mark.anyio
async def test_waitlist_seating_replays_and_no_premature_sale_side_effects(
    app_client,
) -> None:
    client, sessions, headers, _, location_id, _, tables = await _foh_setup(
        app_client, email="stage31-seating@example.com", slug="stage-31-seating"
    )
    entries = []
    for index in range(2):
        client_entry_id = str(uuid4())
        response = await client.post(
            "/api/v1/waitlist",
            headers=headers,
            json={
                "client_entry_id": client_entry_id,
                "location_id": str(location_id),
                "guest_name": f"Walk-in {index}",
                "guest_phone": f"+7777000010{index}",
                "party_size": 2,
                "quoted_wait_minutes": 10 + index,
                "guest_notes": f"Queue note {index}",
            },
        )
        assert response.status_code == 201, response.text
        entries.append({**response.json(), "_client_entry_id": client_entry_id})
    changed_entry = await client.post(
        "/api/v1/waitlist",
        headers=headers,
        json={
            "client_entry_id": entries[0]["_client_entry_id"],
            "location_id": str(location_id),
            "guest_name": entries[0]["guest_name"],
            "guest_phone": entries[0]["guest_phone"],
            "party_size": entries[0]["party_size"],
            "quoted_wait_minutes": entries[0]["quoted_wait_minutes"],
            "guest_notes": "Changed queue request",
        },
    )
    assert changed_entry.status_code == 409
    assert _code(changed_entry) == "IDEMPOTENCY_CONFLICT"
    queue = await client.get(
        "/api/v1/waitlist",
        headers=headers,
        params={"location_id": str(location_id)},
    )
    assert [item["id"] for item in queue.json()] == [item["id"] for item in entries]

    action_id = str(uuid4())
    seat_url = f"/api/v1/waitlist/{entries[0]['id']}/seat"
    first = await client.post(
        seat_url,
        headers=headers,
        json={"client_action_id": action_id, "dining_table_id": tables[0]["id"]},
    )
    replay = await client.post(
        seat_url,
        headers=headers,
        json={"client_action_id": action_id, "dining_table_id": tables[0]["id"]},
    )
    assert first.status_code == replay.status_code == 200
    assert first.json()["id"] == replay.json()["id"]

    cross_origin = await client.post(
        f"/api/v1/waitlist/{entries[1]['id']}/seat",
        headers=headers,
        json={"client_action_id": action_id, "dining_table_id": tables[0]["id"]},
    )
    assert cross_origin.status_code == 409
    assert _code(cross_origin) == "IDEMPOTENCY_CONFLICT"
    cancel_payload = {"client_action_id": str(uuid4())}
    cancelled = await client.post(
        f"/api/v1/waitlist/{entries[1]['id']}/cancel",
        headers=headers,
        json=cancel_payload,
    )
    cancel_replay = await client.post(
        f"/api/v1/waitlist/{entries[1]['id']}/cancel",
        headers=headers,
        json=cancel_payload,
    )
    assert cancelled.status_code == cancel_replay.status_code == 200
    assert cancelled.json()["status"] == cancel_replay.json()["status"] == "CANCELLED"

    direct_action = str(uuid4())
    direct_payload = {
        "client_action_id": direct_action,
        "location_id": str(location_id),
        "dining_table_id": tables[1]["id"],
        "party_size": 3,
    }
    direct = await client.post(
        "/api/v1/dining-visits", headers=headers, json=direct_payload
    )
    direct_replay = await client.post(
        "/api/v1/dining-visits", headers=headers, json=direct_payload
    )
    assert direct.status_code == direct_replay.status_code == 201
    assert direct.json()["id"] == direct_replay.json()["id"]

    floor = await client.get(
        "/api/v1/dining-floor",
        headers=headers,
        params={"location_id": str(location_id)},
    )
    assert floor.status_code == 200
    assert [table["state"] for table in floor.json()["sections"][0]["tables"]] == [
        "OCCUPIED",
        "OCCUPIED",
    ]
    async with sessions() as session:
        assert await session.scalar(select(func.count(WaitlistEntryModel.id))) == 2
        assert await session.scalar(select(func.count(DiningVisitModel.id))) == 2
        assert await session.scalar(select(func.count(SalesOrderModel.id))) == 0
        assert await session.scalar(select(func.count(PaymentModel.id))) == 0
        assert await session.scalar(select(func.count(InventoryTransactionModel.id))) == 0
        assert await session.scalar(select(func.count(FinanceEntryModel.id))) == 0
        assert await session.scalar(
            select(func.count()).select_from(AnalyticsSalesDailyModel)
        ) == 0
        opened = await session.scalar(
            select(func.count(OutboxEventModel.id)).where(
                OutboxEventModel.event_name == "dining_visit.opened"
            )
        )
        assert opened == 2


@pytest.mark.anyio
async def test_postgres_seated_visit_reuses_canonical_pos_sale_once(
    postgres_stage31_app,
) -> None:
    client, sessions, headers, _, location_id, _, _ = await _foh_setup(
        postgres_stage31_app,
        email="stage31-pos@example.com",
        slug="stage-31-pos",
        table_capacities=(2,),
    )
    warehouse = (
        await client.get("/api/v1/inventory/warehouses", headers=headers)
    ).json()[0]
    shift = await _register_shift(
        client, headers, location_id, UUID(warehouse["id"]), "Stage 31 POS"
    )
    start_at = await _slot(client, "stage-31-pos")
    created = await client.post(
        "/api/v1/public/reservations/stage-31-pos", json=_guest(start_at)
    )
    assert created.status_code == 201, created.text
    reservation = (
        await client.get(
            "/api/v1/reservations",
            headers=headers,
            params={"location_id": str(location_id)},
        )
    ).json()[0]
    seated = await client.post(
        f"/api/v1/reservations/{reservation['id']}/seat",
        headers=headers,
        json={"client_action_id": str(uuid4())},
    )
    assert seated.status_code == 200, seated.text
    async with sessions() as session:
        assert await session.scalar(select(func.count(SalesOrderModel.id))) == 0
        assert await session.scalar(select(func.count(PaymentModel.id))) == 0
        assert await session.scalar(select(func.count(InventoryTransactionModel.id))) == 0
        assert await session.scalar(select(func.count(FinanceEntryModel.id))) == 0
        assert await session.scalar(
            select(func.count()).select_from(AnalyticsSalesDailyModel)
        ) == 0

    client_order_id = str(uuid4())
    open_payload = {"client_order_id": client_order_id, "shift_id": shift["id"]}
    opened = await client.post(
        f"/api/v1/dining-visits/{seated.json()['id']}/open-check",
        headers=headers,
        json=open_payload,
    )
    replay = await client.post(
        f"/api/v1/dining-visits/{seated.json()['id']}/open-check",
        headers=headers,
        json=open_payload,
    )
    assert opened.status_code == replay.status_code == 200
    assert opened.json()["sales_order_id"] == replay.json()["sales_order_id"]
    async with sessions() as session:
        assert await session.scalar(select(func.count(SalesOrderModel.id))) == 1

    promotion = await client.post("/api/v1/promotions", headers=headers, json=_promotion())
    assert promotion.status_code == 201, promotion.text
    assert (
        await client.post(
            f"/api/v1/promotions/{promotion.json()['id']}/activate", headers=headers
        )
    ).status_code == 200
    variant_id = await _variant(client, headers, "Stage 31 coffee", 90000)
    order_id = opened.json()["sales_order_id"]
    order = await client.post(
        f"/api/v1/sales/orders/{order_id}/items",
        headers=headers,
        json={
            "client_item_id": str(uuid4()),
            "variant_id": str(variant_id),
            "selected_option_ids": [],
            "quantity": 1,
        },
    )
    assert order.status_code == 201, order.text
    assert (
        order.json()["subtotal_minor"],
        order.json()["discount_total_minor"],
        order.json()["total_minor"],
    ) == ("90000", "9000", "81000")
    payment_payload = {
        "client_payment_id": str(uuid4()),
        "lines": [
            {
                "method": "CASH",
                "amount_minor": "81000",
                "cash_received_minor": "81000",
            }
        ],
    }
    payment = await client.post(
        f"/api/v1/payments/orders/{order_id}/complete",
        headers=headers,
        json=payment_payload,
    )
    payment_replay = await client.post(
        f"/api/v1/payments/orders/{order_id}/complete",
        headers=headers,
        json=payment_payload,
    )
    assert payment.status_code == payment_replay.status_code == 201
    assert payment.json()["id"] == payment_replay.json()["id"]
    await _dispatch_all(sessions)

    async with sessions() as session:
        visit = await session.scalar(select(DiningVisitModel))
        completed = await session.scalar(select(ReservationModel))
        assert visit.closed_at is not None
        assert completed.status == "COMPLETED"
        assert await session.scalar(select(func.count(SalesOrderModel.id))) == 1
        assert await session.scalar(select(func.count(PaymentModel.id))) == 1
        assert await session.scalar(
            select(func.count(InventoryTransactionModel.id)).where(
                InventoryTransactionModel.type == "SALE"
            )
        ) == 1
        assert await session.scalar(select(func.count(KitchenTicketModel.id))) == 1
        finance = {
            row.entry_role: row.amount
            for row in await session.scalars(
                select(FinanceEntryModel).where(FinanceEntryModel.source_type == "PAYMENT")
            )
        }
        assert finance["REVENUE_GROSS"] == 900
        assert finance["SALES_DISCOUNT"] == -90
        analytics = await session.scalar(select(AnalyticsSalesDailyModel))
        assert analytics is not None
        assert (
            analytics.gross_revenue_amount,
            analytics.discount_amount,
            analytics.revenue_amount,
            analytics.paid_orders,
        ) == (900, 90, 810, 1)
        assert await session.scalar(
            select(func.count(OutboxEventModel.id)).where(
                OutboxEventModel.event_name == "dining_visit.closed"
            )
        ) == 1
        assert await session.scalar(
            select(func.count(OutboxEventModel.id)).where(
                OutboxEventModel.processed_at.is_(None)
            )
        ) == 0
        assert await session.scalar(
            select(func.count(OutboxEventModel.id)).where(
                OutboxEventModel.dead_lettered_at.is_not(None)
            )
        ) == 0
        assert await session.scalar(
            select(func.count(OutboxEventModel.id)).where(
                OutboxEventModel.last_error.is_not(None)
            )
        ) == 0
    floor = await client.get(
        "/api/v1/dining-floor",
        headers=headers,
        params={"location_id": str(location_id)},
    )
    assert floor.json()["sections"][0]["tables"][0]["state"] == "AVAILABLE"


@pytest.mark.anyio
async def test_postgres_reservation_seating_and_seat_cancel_races(
    postgres_stage31_app,
) -> None:
    client, sessions, headers, _, location_id, _, tables = await _foh_setup(
        postgres_stage31_app,
        email="stage31-races@example.com",
        slug="stage-31-races",
        table_capacities=(2,),
    )
    start_at = await _slot(client, "stage-31-races")
    payloads = [_guest(start_at, client_reservation_id=str(uuid4())) for _ in range(2)]
    created = await asyncio.gather(*(
        client.post("/api/v1/public/reservations/stage-31-races", json=payload)
        for payload in payloads
    ))
    assert sorted(response.status_code for response in created) == [201, 409]
    loser = next(response for response in created if response.status_code == 409)
    assert _code(loser) == "SLOT_UNAVAILABLE"
    async with sessions() as session:
        assert await session.scalar(select(func.count(ReservationModel.id))) == 1
        assert await session.scalar(select(func.count(DiningVisitModel.id))) == 0
        assert await session.scalar(select(func.count(PaymentModel.id))) == 0
        assert await session.scalar(select(func.count(InventoryTransactionModel.id))) == 0
        assert await session.scalar(
            select(func.count(OutboxEventModel.id)).where(
                OutboxEventModel.event_name == "reservation.created"
            )
        ) == 1

    reservation = (await client.get(
        "/api/v1/reservations",
        headers=headers,
        params={"location_id": str(location_id)},
    )).json()[0]
    seat_payload = {
        "client_action_id": str(uuid4()),
        "dining_table_id": tables[0]["id"],
    }
    seated, cancelled = await asyncio.gather(
        client.post(
            f"/api/v1/reservations/{reservation['id']}/seat",
            headers=headers,
            json=seat_payload,
        ),
        client.post(
            f"/api/v1/reservations/{reservation['id']}/cancel",
            headers=headers,
            json={"client_action_id": str(uuid4()), "reason": "Race"},
        ),
    )
    assert sorted((seated.status_code, cancelled.status_code)) == [200, 409]
    async with sessions() as session:
        current = await session.scalar(select(ReservationModel))
        visit_count = await session.scalar(select(func.count(DiningVisitModel.id)))
        assert (current.status, visit_count) in {("SEATED", 1), ("CANCELLED", 0)}
        assert not (current.status == "CANCELLED" and visit_count == 1)

    if current.status == "SEATED":
        visit_id = seated.json()["id"]
        assert (
            await client.post(
                f"/api/v1/dining-visits/{visit_id}/close",
                headers=headers,
                json={"client_action_id": str(uuid4())},
            )
        ).status_code == 200
    else:
        replacement = await client.post(
            "/api/v1/dining-visits",
            headers=headers,
            json={
                "client_action_id": str(uuid4()),
                "location_id": str(location_id),
                "dining_table_id": tables[0]["id"],
                "party_size": 2,
            },
        )
        assert replacement.status_code == 201
        assert (
            await client.post(
                f"/api/v1/dining-visits/{replacement.json()['id']}/close",
                headers=headers,
                json={"client_action_id": str(uuid4())},
            )
        ).status_code == 200

    visits = [
        {
            "client_action_id": str(uuid4()),
            "location_id": str(location_id),
            "dining_table_id": tables[0]["id"],
            "party_size": 2,
        }
        for _ in range(2)
    ]
    race = await asyncio.gather(*(
        client.post("/api/v1/dining-visits", headers=headers, json=payload)
        for payload in visits
    ))
    assert sorted(response.status_code for response in race) == [201, 409]
    assert _code(next(response for response in race if response.status_code == 409)) == (
        "TABLE_OCCUPIED"
    )
    async with sessions() as session:
        assert await session.scalar(
            select(func.count(DiningVisitModel.id)).where(
                DiningVisitModel.closed_at.is_(None)
            )
        ) == 1
        assert await session.scalar(select(func.count(SalesOrderModel.id))) == 0
        assert await session.scalar(select(func.count(PaymentModel.id))) == 0
        assert await session.scalar(select(func.count(InventoryTransactionModel.id))) == 0
