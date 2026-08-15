import asyncio
from datetime import time
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from test_offline_pos import (
    _catalog,
    _cookie,
    _register_shift,
    _workspace,
)
from test_offline_pos import (
    postgres_offline_app as _postgres_offline_app,
)

from beanly.core.config.settings import get_settings
from beanly.core.events.handlers.registry import EventHandlerRegistry
from beanly.core.events.outbox.dispatcher import OutboxDispatcher
from beanly.core.events.outbox.models import OutboxEventModel
from beanly.core.events.outbox.repositories import OutboxRepository
from beanly.modules.finance.application.projection_service import FinanceProjectionService
from beanly.modules.finance.infrastructure.db.models import FinanceEntryModel
from beanly.modules.finance.infrastructure.db.repositories import (
    SqlAlchemyFinanceRepository,
)
from beanly.modules.finance.infrastructure.handlers import register_finance_handlers
from beanly.modules.finance.infrastructure.source_reader import (
    SqlAlchemyFinanceSourceReader,
)
from beanly.modules.inventory.infrastructure.db.models import InventoryTransactionModel
from beanly.modules.kitchen.infrastructure.db.models import KitchenTicketModel
from beanly.modules.kitchen.infrastructure.handlers import register_kitchen_handlers
from beanly.modules.kitchen.infrastructure.service import KitchenService
from beanly.modules.offline_pos.domain.exceptions import OrderChangedOnServer
from beanly.modules.offline_pos.infrastructure.sales_gateway import OfflineSalesGateway
from beanly.modules.online_ordering.infrastructure.db.models import (
    OnlineOrderActionModel,
    OnlineOrderModel,
    OrderingStationModel,
)
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
from beanly.modules.sales.domain.enums import OrderSource, OrderStatus
from beanly.modules.sales.infrastructure.db.models import SalesOrderModel

postgres_stage29_app = _postgres_offline_app


def _promotion_payload(
    name: str, channels: list[str], percent_rate: str
) -> dict[str, object]:
    return {
        "name": name,
        "pos_name": name,
        "application_mode": "AUTOMATIC",
        "discount_kind": "PERCENT",
        "scope": "ORDER",
        "percent_rate": percent_rate,
        "priority": 100,
        "stacking_policy": "EXCLUSIVE",
        "include_modifier_price": False,
        "all_locations": True,
        "channels": channels,
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


async def _setup(app_client):
    client, sessions = app_client
    headers, organization_id, location_id, warehouse_id = await _workspace(
        client, "stage29-owner@example.com", "Stage 29"
    )
    register, shift = await _register_shift(client, headers, location_id, warehouse_id)
    variant_id, _ = await _catalog(client, headers)
    settings = await client.put(
        "/api/v1/online-ordering/settings",
        headers=headers,
        json={
            "location_id": str(location_id),
            "public_slug": "stage-29-cafe",
            "enabled": True,
            "register_id": register["id"],
            "guest_phone_required_pickup": True,
            "schedules": [
                {
                    "weekday": weekday,
                    "opens_at_local": time(0, 0).isoformat(),
                    "closes_at_local": time(23, 59, 59).isoformat(),
                }
                for weekday in range(7)
            ],
        },
    )
    assert settings.status_code == 200, settings.text
    station = await client.post(
        "/api/v1/online-ordering/stations",
        headers=headers,
        json={"location_id": str(location_id), "kind": "TABLE", "label": "Table 7"},
    )
    assert station.status_code == 201, station.text
    return (
        client,
        sessions,
        headers,
        organization_id,
        location_id,
        variant_id,
        station.json(),
        register,
        shift,
    )


@pytest.mark.anyio
async def test_public_qr_quote_submit_replay_cancel_and_privacy(app_client) -> None:
    client, sessions, headers, _, location_id, variant_id, station, _, _ = (
        await _setup(app_client)
    )
    token = station["public_token"]
    page = await client.get(f"/api/v1/public/ordering/stage-29-cafe?station={token}")
    assert page.status_code == 200, page.text
    assert page.json()["station"] == {"kind": "TABLE", "label": "Table 7"}
    menu = await client.get("/api/v1/public/ordering/stage-29-cafe/menu")
    assert menu.status_code == 200, menu.text
    rendered = menu.text.lower()
    assert all(secret not in rendered for secret in ("recipe", "inventory", "cost", "sku"))

    client_order_id, client_item_id = uuid4(), uuid4()
    cart = {
        "client_order_id": str(client_order_id),
        "station_token": token,
        "items": [
            {
                "client_item_id": str(client_item_id),
                "variant_id": str(variant_id),
                "quantity": 2,
                "modifier_option_ids": [],
            }
        ],
    }
    omitted_query = await client.post(
        "/api/v1/public/ordering/stage-29-cafe/quote", json=cart
    )
    assert omitted_query.status_code == 422
    assert omitted_query.json()["detail"]["code"] == "ONLINE_ORDER_INVALID_STATION"
    mismatched_query = await client.post(
        "/api/v1/public/ordering/stage-29-cafe/quote?station=other-station-token-00000000",
        json=cart,
    )
    assert mismatched_query.status_code == 422
    assert mismatched_query.json()["detail"]["code"] == "ONLINE_ORDER_INVALID_STATION"
    quote = await client.post(
        f"/api/v1/public/ordering/stage-29-cafe/quote?station={token}", json=cart
    )
    assert quote.status_code == 200, quote.text
    assert quote.json()["total_minor"] == "360000"
    submit_payload = {
        **cart,
        "quote_revision": quote.json()["quote_revision"],
        "guest_name": "Berik",
    }
    omitted_submit_query = await client.post(
        "/api/v1/public/ordering/stage-29-cafe/orders", json=submit_payload
    )
    assert omitted_submit_query.status_code == 422
    assert omitted_submit_query.json()["detail"]["code"] == "ONLINE_ORDER_INVALID_STATION"
    mismatched_submit_query = await client.post(
        "/api/v1/public/ordering/stage-29-cafe/orders"
        "?station=other-station-token-00000000",
        json=submit_payload,
    )
    assert mismatched_submit_query.status_code == 422
    assert mismatched_submit_query.json()["detail"]["code"] == "ONLINE_ORDER_INVALID_STATION"
    changed_price = await client.put(
        f"/api/v1/menu/variants/{variant_id}/prices/{location_id}",
        headers=headers,
        json={"price_minor": 200000},
    )
    assert changed_price.status_code == 200, changed_price.text
    stale_quote = await client.post(
        f"/api/v1/public/ordering/stage-29-cafe/orders?station={token}",
        json=submit_payload,
    )
    assert stale_quote.status_code == 409
    assert stale_quote.json()["detail"]["code"] == "ONLINE_ORDER_QUOTE_CHANGED"
    assert stale_quote.json()["detail"]["quote"]["total_minor"] == "400000"
    submit_payload["quote_revision"] = stale_quote.json()["detail"]["quote"][
        "quote_revision"
    ]
    created = await client.post(
        f"/api/v1/public/ordering/stage-29-cafe/orders?station={token}",
        json=submit_payload,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "PENDING"
    assert body["source"] == "QR"
    assert body["status_token"] and body["station_label"] == "Table 7"
    assert body["order_number"] > 0
    assert not {
        "id",
        "organization_id",
        "location_id",
        "sales_order_id",
        "station_id",
        "client_order_id",
        "guest_name",
        "guest_phone",
    }.intersection(body)

    replay = await client.post(
        f"/api/v1/public/ordering/stage-29-cafe/orders?station={token}",
        json=submit_payload,
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["status_token"] == body["status_token"]
    changed = await client.post(
        f"/api/v1/public/ordering/stage-29-cafe/orders?station={token}",
        json={**submit_payload, "guest_name": "Someone else"},
    )
    assert changed.status_code == 409
    assert changed.json()["detail"]["code"] == "ONLINE_ORDER_IDEMPOTENCY_CONFLICT"

    status = await client.get(
        f"/api/v1/public/ordering/orders/{body['status_token']}"
    )
    assert status.status_code == 200 and status.json()["status"] == "PENDING"
    assert status.json()["order_number"] == body["order_number"]
    assert not {
        "id",
        "organization_id",
        "location_id",
        "sales_order_id",
        "station_id",
        "client_order_id",
        "guest_name",
        "guest_phone",
        "status_token",
    }.intersection(status.json())
    staff_orders = await client.get("/api/v1/online-orders", headers=headers)
    assert staff_orders.status_code == 200 and len(staff_orders.json()) == 1
    assert staff_orders.json()[0]["guest_name"] == "Berik"
    assert staff_orders.json()[0]["order_number"] > 0
    cancelled = await client.post(
        f"/api/v1/public/ordering/orders/{body['status_token']}/cancel"
    )
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "CANCELLED"
    assert (await client.get("/api/v1/public/ordering/orders/not-a-token")).status_code == 404
    closed = await client.post(
        "/api/v1/online-ordering/pause",
        headers=headers,
        json={
            "location_id": str(location_id),
            "closed_today": True,
            "reason": "Closed today",
        },
    )
    assert closed.status_code == 200, closed.text
    readiness = await client.get(
        "/api/v1/online-ordering/readiness",
        headers=headers,
        params={"location_id": str(location_id)},
    )
    assert readiness.status_code == 200
    assert not readiness.json()["ready"]
    assert "CLOSED_TODAY" in readiness.json()["reasons"]
    availability = await client.get(
        "/api/v1/public/ordering/stage-29-cafe/availability",
        params={"station": token},
    )
    assert availability.status_code == 200
    assert not availability.json()["available"]
    assert "CLOSED_TODAY" in availability.json()["reasons"]
    menu_while_closed = await client.get(
        "/api/v1/public/ordering/stage-29-cafe/menu"
    )
    assert menu_while_closed.status_code == 200, menu_while_closed.text
    resumed = await client.post(
        "/api/v1/online-ordering/resume",
        headers=headers,
        json={"location_id": str(location_id)},
    )
    assert resumed.status_code == 200, resumed.text
    resumed_availability = await client.get(
        "/api/v1/public/ordering/stage-29-cafe/availability",
        params={"station": token},
    )
    assert resumed_availability.status_code == 200
    assert resumed_availability.json()["available"]
    resumed_readiness = await client.get(
        "/api/v1/online-ordering/readiness",
        headers=headers,
        params={"location_id": str(location_id)},
    )
    assert resumed_readiness.status_code == 200
    assert resumed_readiness.json()["ready"]
    rotated = await client.post(
        f"/api/v1/online-ordering/stations/{station['id']}/rotate", headers=headers
    )
    assert rotated.status_code == 200, rotated.text
    revoked_token = await client.get(
        f"/api/v1/public/ordering/stage-29-cafe?station={token}"
    )
    assert revoked_token.status_code == 422
    new_token = rotated.json()["public_token"]
    assert new_token and new_token != token
    assert (
        await client.get(
            f"/api/v1/public/ordering/stage-29-cafe?station={new_token}"
        )
    ).status_code == 200

    async with sessions() as session:
        assert await session.scalar(select(func.count(OnlineOrderModel.id))) == 1
        sale = await session.scalar(select(SalesOrderModel))
        assert sale is not None
        assert sale.order_source == "QR" and sale.created_by_user_id is None
        assert sale.customer_name_snapshot == "Berik"
        assert sale.customer_phone_snapshot is None and sale.customer_id is None
        assert sale.status == "CANCELLED"
        station_row = await session.get(OrderingStationModel, UUID(station["id"]))
        assert station_row is not None and station_row.public_token_hash != token
        assert await session.scalar(select(func.count(OnlineOrderActionModel.id))) == 2
        assert await session.scalar(select(func.count(OutboxEventModel.id))) == 2


@pytest.mark.anyio
async def test_staff_accept_and_cancel_are_idempotent(app_client) -> None:
    client, sessions, headers, _, _, variant_id, station, _, _ = await _setup(app_client)
    cart = {
        "client_order_id": str(uuid4()),
        "station_token": station["public_token"],
        "items": [
            {
                "client_item_id": str(uuid4()),
                "variant_id": str(variant_id),
                "quantity": 1,
                "modifier_option_ids": [],
            }
        ],
    }
    token = station["public_token"]
    quote = await client.post(
        f"/api/v1/public/ordering/stage-29-cafe/quote?station={token}", json=cart
    )
    created = await client.post(
        f"/api/v1/public/ordering/stage-29-cafe/orders?station={token}",
        json={**cart, "quote_revision": quote.json()["quote_revision"]},
    )
    body = created.json()
    staff_orders = await client.get("/api/v1/online-orders", headers=headers)
    assert staff_orders.status_code == 200 and len(staff_orders.json()) == 1
    staff_order = staff_orders.json()[0]
    online_id = staff_order["id"]
    premature_payment = await client.post(
        f"/api/v1/payments/orders/{staff_order['sales_order_id']}/complete",
        headers=headers,
        json={
            "client_payment_id": str(uuid4()),
            "lines": [
                {
                    "method": "CASH",
                    "amount_minor": staff_order["total_minor"],
                    "cash_received_minor": staff_order["total_minor"],
                }
            ],
        },
    )
    assert premature_payment.status_code == 409
    assert premature_payment.json()["detail"]["code"] == "ORDER_NOT_PAYABLE"
    action_id = str(uuid4())
    accepted = await client.post(
        f"/api/v1/online-orders/{online_id}/accept",
        headers=headers,
        json={"client_action_id": action_id},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "AWAITING_PAYMENT"
    replay = await client.post(
        f"/api/v1/online-orders/{online_id}/accept",
        headers=headers,
        json={"client_action_id": action_id},
    )
    assert replay.status_code == 200 and replay.json()["id"] == online_id
    mismatched_replay = await client.post(
        f"/api/v1/online-orders/{online_id}/cancel",
        headers=headers,
        json={"client_action_id": action_id, "reason": "Different action"},
    )
    assert mismatched_replay.status_code == 409
    assert (
        mismatched_replay.json()["detail"]["code"]
        == "ONLINE_ORDER_IDEMPOTENCY_CONFLICT"
    )
    cancel_action_id = str(uuid4())
    cancel_payload = {
        "client_action_id": cancel_action_id,
        "reason": "  Closing soon  ",
    }
    staff_cancel = await client.post(
        f"/api/v1/online-orders/{online_id}/cancel",
        headers=headers,
        json=cancel_payload,
    )
    assert staff_cancel.status_code == 200
    assert staff_cancel.json()["status"] == "CANCELLED"
    cancel_replay = await client.post(
        f"/api/v1/online-orders/{online_id}/cancel",
        headers=headers,
        json=cancel_payload,
    )
    assert cancel_replay.status_code == 200
    assert cancel_replay.json()["status"] == "CANCELLED"
    guest_cancel = await client.post(
        f"/api/v1/public/ordering/orders/{body['status_token']}/cancel"
    )
    assert guest_cancel.status_code == 200
    assert guest_cancel.json()["status"] == "CANCELLED"

    pickup_cart = {
        "client_order_id": str(uuid4()),
        "items": [
            {
                "client_item_id": str(uuid4()),
                "variant_id": str(variant_id),
                "quantity": 1,
                "modifier_option_ids": [],
            }
        ],
    }
    pickup_quote = await client.post(
        "/api/v1/public/ordering/stage-29-cafe/quote", json=pickup_cart
    )
    assert pickup_quote.status_code == 200, pickup_quote.text
    pickup_payload = {
        **pickup_cart,
        "quote_revision": pickup_quote.json()["quote_revision"],
        "guest_name": "Pickup guest",
    }
    missing_phone = await client.post(
        "/api/v1/public/ordering/stage-29-cafe/orders", json=pickup_payload
    )
    assert missing_phone.status_code == 422
    assert missing_phone.json()["detail"]["code"] == "ONLINE_ORDER_CART_INVALID"
    pickup = await client.post(
        "/api/v1/public/ordering/stage-29-cafe/orders",
        json={**pickup_payload, "guest_phone": "+7 (771) 234-56-78"},
    )
    assert pickup.status_code == 201, pickup.text
    assert pickup.json()["source"] == "ONLINE" and "guest_phone" not in pickup.json()
    staff_pickup = next(
        value
        for value in (await client.get("/api/v1/online-orders", headers=headers)).json()
        if value["source"] == "ONLINE"
    )
    assert staff_pickup["guest_name"] == "Pickup guest"
    assert staff_pickup["guest_phone"] == "+77712345678"
    async with sessions() as session:
        sale = await session.get(SalesOrderModel, UUID(staff_pickup["sales_order_id"]))
        assert sale is not None
        assert sale.customer_name_snapshot == "Pickup guest"
        assert sale.customer_phone_snapshot == "+77712345678"
        assert sale.customer_id is None


class _ExistingOrderRepository:
    def __init__(self, order) -> None:
        self.order = order

    async def get_order_by_client_id(self, _organization_id, _client_order_id):
        return self.order

    async def get_order(self, _organization_id, _order_id, *, lock=False):
        assert lock
        return self.order


@pytest.mark.anyio
async def test_offline_claim_rejects_pos_cross_shift_and_cross_location_orders() -> None:
    organization_id = uuid4()
    location_id = uuid4()
    shift_id = uuid4()
    warehouse_id = uuid4()
    session = SimpleNamespace(
        id=uuid4(),
        location_id=location_id,
        shift_id=shift_id,
        warehouse_id=warehouse_id,
    )
    device = SimpleNamespace(id=uuid4())
    request = SimpleNamespace(client_order_id=uuid4(), base_server_version=1)
    common = {
        "id": uuid4(),
        "version": 1,
        "status": OrderStatus.OPEN,
        "offline_session_id": None,
        "pos_device_id": None,
        "location_id": location_id,
        "shift_id": shift_id,
        "warehouse_id": warehouse_id,
    }
    rejected = (
        SimpleNamespace(**common, order_source=OrderSource.POS),
        SimpleNamespace(
            **{**common, "id": uuid4(), "shift_id": uuid4()},
            order_source=OrderSource.QR,
        ),
        SimpleNamespace(
            **{**common, "id": uuid4(), "location_id": uuid4()},
            order_source=OrderSource.ONLINE,
        ),
    )
    for order in rejected:
        gateway = OfflineSalesGateway(_ExistingOrderRepository(order), object())
        with pytest.raises(OrderChangedOnServer, match="another POS session"):
            await gateway.reconcile_staged(
                SimpleNamespace(organization_id=organization_id),
                device,
                session,
                object(),
                request,
            )


@pytest.mark.anyio
async def test_postgres_public_qr_quote_submit_replay_cancel_and_privacy(
    postgres_stage29_app,
) -> None:
    client, sessions, _ = postgres_stage29_app
    await test_public_qr_quote_submit_replay_cancel_and_privacy((client, sessions))


@pytest.mark.anyio
async def test_postgres_staff_accept_pickup_and_cancel_policy(
    postgres_stage29_app,
) -> None:
    client, sessions, _ = postgres_stage29_app
    await test_staff_accept_and_cancel_are_idempotent((client, sessions))


@pytest.mark.anyio
async def test_postgres_tenant_menu_policy_failures_reject_and_online_promotion(
    postgres_stage29_app,
) -> None:
    client, sessions, _ = postgres_stage29_app
    (
        client,
        _,
        headers,
        _,
        location_id,
        variant_id,
        station,
        register,
        _,
    ) = await _setup((client, sessions))
    other_headers, _, other_location_id, other_warehouse_id = await _workspace(
        client, "stage29-other-owner@example.com", "Stage 29 Other"
    )
    other_register, _ = await _register_shift(
        client, other_headers, other_location_id, other_warehouse_id
    )
    other_variant_id, _ = await _catalog(client, other_headers)
    other_settings = await client.put(
        "/api/v1/online-ordering/settings",
        headers=other_headers,
        json={
            "location_id": str(other_location_id),
            "public_slug": "stage-29-other-cafe",
            "enabled": True,
            "register_id": other_register["id"],
            "schedules": [
                {
                    "weekday": weekday,
                    "opens_at_local": "00:00:00",
                    "closes_at_local": "23:59:59",
                }
                for weekday in range(7)
            ],
        },
    )
    assert other_settings.status_code == 200, other_settings.text
    own_menu = await client.get("/api/v1/public/ordering/stage-29-cafe/menu")
    other_menu = await client.get("/api/v1/public/ordering/stage-29-other-cafe/menu")
    assert own_menu.status_code == other_menu.status_code == 200
    assert str(other_variant_id) not in own_menu.text
    assert str(variant_id) not in other_menu.text

    product = own_menu.json()["categories"][0]["products"][0]
    modifier_group = await client.post(
        f"/api/v1/menu/variants/{variant_id}/modifier-groups",
        headers=headers,
        json={
            "name": "Milk",
            "selection_type": "SINGLE",
            "min_selections": 1,
            "max_selections": 1,
        },
    )
    assert modifier_group.status_code == 201, modifier_group.text
    modifier_option = await client.post(
        f"/api/v1/menu/modifier-groups/{modifier_group.json()['id']}/options",
        headers=headers,
        json={
            "name": "Regular",
            "base_price_delta_minor": 0,
            "is_default": False,
        },
    )
    assert modifier_option.status_code == 201, modifier_option.text
    token = station["public_token"]
    client_order_id = uuid4()
    cart = {
        "client_order_id": str(client_order_id),
        "station_token": token,
        "items": [
            {
                "client_item_id": str(uuid4()),
                "variant_id": str(variant_id),
                "quantity": 1,
                "modifier_option_ids": [],
            }
        ],
    }
    missing_modifier = await client.post(
        f"/api/v1/public/ordering/stage-29-cafe/quote?station={token}", json=cart
    )
    assert missing_modifier.status_code == 422
    cart["items"][0]["modifier_option_ids"] = [modifier_option.json()["id"]]
    quote = await client.post(
        f"/api/v1/public/ordering/stage-29-cafe/quote?station={token}", json=cart
    )
    assert quote.status_code == 200, quote.text
    created = await client.post(
        f"/api/v1/public/ordering/stage-29-cafe/orders?station={token}",
        json={**cart, "quote_revision": quote.json()["quote_revision"]},
    )
    assert created.status_code == 201, created.text
    staff_order = (await client.get("/api/v1/online-orders", headers=headers)).json()[0]
    assert staff_order["order_number"] > 0
    rejected = await client.post(
        f"/api/v1/online-orders/{staff_order['id']}/reject",
        headers=headers,
        json={"client_action_id": str(uuid4()), "reason": "Sold out"},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "REJECTED"
    public_rejected = await client.get(
        f"/api/v1/public/ordering/orders/{created.json()['status_token']}"
    )
    assert public_rejected.status_code == 200
    assert public_rejected.json()["status"] == "REJECTED"

    online_promotion = await client.post(
        "/api/v1/promotions",
        headers=headers,
        json=_promotion_payload("ONLINE 10%", ["ONLINE"], "10.0000"),
    )
    assert online_promotion.status_code == 201, online_promotion.text
    activated = await client.post(
        f"/api/v1/promotions/{online_promotion.json()['id']}/activate", headers=headers
    )
    assert activated.status_code == 200, activated.text
    pickup_cart = {
        **cart,
        "client_order_id": str(uuid4()),
        "station_token": None,
    }
    pickup_quote = await client.post(
        "/api/v1/public/ordering/stage-29-cafe/quote", json=pickup_cart
    )
    assert pickup_quote.status_code == 200, pickup_quote.text
    assert [value["name"] for value in pickup_quote.json()["applied_promotions"]] == [
        "ONLINE 10%"
    ]
    pickup_payload = {
        **pickup_cart,
        "quote_revision": pickup_quote.json()["quote_revision"],
    }
    missing_guest = await client.post(
        "/api/v1/public/ordering/stage-29-cafe/orders", json=pickup_payload
    )
    assert missing_guest.status_code == 422

    unavailable = await client.put(
        f"/api/v1/menu/products/{product['id']}/locations/{location_id}",
        headers=headers,
        json={"is_available": False, "is_visible": True},
    )
    assert unavailable.status_code == 200, unavailable.text
    unavailable_quote = await client.post(
        "/api/v1/public/ordering/stage-29-cafe/quote", json=pickup_cart
    )
    assert unavailable_quote.status_code == 422
    stale_product = await client.post(
        "/api/v1/public/ordering/stage-29-cafe/orders",
        json={
            **pickup_payload,
            "guest_name": "Pickup guest",
            "guest_phone": "+77712345678",
        },
    )
    assert stale_product.status_code == 409
    assert stale_product.json()["detail"]["code"] == "ONLINE_ORDER_QUOTE_CHANGED"
    restored = await client.put(
        f"/api/v1/menu/products/{product['id']}/locations/{location_id}",
        headers=headers,
        json={"is_available": True, "is_visible": True},
    )
    assert restored.status_code == 200, restored.text
    fresh_quote = await client.post(
        "/api/v1/public/ordering/stage-29-cafe/quote", json=pickup_cart
    )
    assert fresh_quote.status_code == 200, fresh_quote.text
    unavailable_modifier = await client.put(
        f"/api/v1/menu/modifier-options/{modifier_option.json()['id']}"
        f"/locations/{location_id}",
        headers=headers,
        json={"is_available": False},
    )
    assert unavailable_modifier.status_code == 200, unavailable_modifier.text
    stale_modifier = await client.post(
        "/api/v1/public/ordering/stage-29-cafe/orders",
        json={
            **pickup_cart,
            "quote_revision": fresh_quote.json()["quote_revision"],
            "guest_name": "Pickup guest",
            "guest_phone": "+77712345678",
        },
    )
    assert stale_modifier.status_code == 409
    assert stale_modifier.json()["detail"]["code"] == "ONLINE_ORDER_QUOTE_CHANGED"
    restored_modifier = await client.put(
        f"/api/v1/menu/modifier-options/{modifier_option.json()['id']}"
        f"/locations/{location_id}",
        headers=headers,
        json={"is_available": True},
    )
    assert restored_modifier.status_code == 200, restored_modifier.text
    final_quote = await client.post(
        "/api/v1/public/ordering/stage-29-cafe/quote", json=pickup_cart
    )
    assert final_quote.status_code == 200, final_quote.text
    pickup = await client.post(
        "/api/v1/public/ordering/stage-29-cafe/orders",
        json={
            **pickup_cart,
            "quote_revision": final_quote.json()["quote_revision"],
            "guest_name": "Pickup guest",
            "guest_phone": "+77712345678",
        },
    )
    assert pickup.status_code == 201, pickup.text
    assert pickup.json()["source"] == "ONLINE"

    paused = await client.post(
        "/api/v1/online-ordering/pause",
        headers=headers,
        json={"location_id": str(location_id), "minutes": 15, "reason": "Busy"},
    )
    assert paused.status_code == 200, paused.text
    availability = await client.get(
        "/api/v1/public/ordering/stage-29-cafe/availability"
    )
    assert availability.status_code == 200
    assert "TEMPORARILY_PAUSED" in availability.json()["reasons"]
    assert (
        await client.post(
            "/api/v1/online-ordering/resume",
            headers=headers,
            json={"location_id": str(location_id)},
        )
    ).status_code == 200

    closed_schedule = await client.put(
        "/api/v1/online-ordering/settings",
        headers=headers,
        json={
            "location_id": str(location_id),
            "public_slug": "stage-29-cafe",
            "enabled": True,
            "register_id": register["id"],
            "schedules": [],
        },
    )
    assert closed_schedule.status_code == 200, closed_schedule.text
    availability = await client.get(
        "/api/v1/public/ordering/stage-29-cafe/availability"
    )
    assert availability.status_code == 200
    assert "SCHEDULE_CLOSED" in availability.json()["reasons"]
    reopened_schedule = await client.put(
        "/api/v1/online-ordering/settings",
        headers=headers,
        json={
            "location_id": str(location_id),
            "public_slug": "stage-29-cafe",
            "enabled": True,
            "register_id": register["id"],
            "schedules": [
                {
                    "weekday": weekday,
                    "opens_at_local": "00:00:00",
                    "closes_at_local": "23:59:59",
                }
                for weekday in range(7)
            ],
        },
    )
    assert reopened_schedule.status_code == 200, reopened_schedule.text
    disabled_channels = await client.put(
        "/api/v1/online-ordering/settings",
        headers=headers,
        json={
            "location_id": str(location_id),
            "public_slug": "stage-29-cafe",
            "enabled": True,
            "pickup_enabled": False,
            "qr_dine_in_enabled": False,
            "register_id": register["id"],
            "schedules": [
                {
                    "weekday": weekday,
                    "opens_at_local": "00:00:00",
                    "closes_at_local": "23:59:59",
                }
                for weekday in range(7)
            ],
        },
    )
    assert disabled_channels.status_code == 200, disabled_channels.text
    readiness = await client.get(
        "/api/v1/online-ordering/readiness",
        headers=headers,
        params={"location_id": str(location_id)},
    )
    assert readiness.status_code == 200, readiness.text
    assert not readiness.json()["ready"]
    assert "NO_ORDERING_CHANNEL_ENABLED" in readiness.json()["reasons"]
    unopened_register = await client.post(
        "/api/v1/sales/registers",
        headers=headers,
        json={"location_id": str(location_id), "name": "Unopened counter"},
    )
    assert unopened_register.status_code == 201, unopened_register.text
    no_shift_settings = await client.put(
        "/api/v1/online-ordering/settings",
        headers=headers,
        json={
            "location_id": str(location_id),
            "public_slug": "stage-29-cafe",
            "enabled": True,
            "register_id": unopened_register.json()["id"],
            "schedules": [
                {
                    "weekday": weekday,
                    "opens_at_local": "00:00:00",
                    "closes_at_local": "23:59:59",
                }
                for weekday in range(7)
            ],
        },
    )
    assert no_shift_settings.status_code == 200, no_shift_settings.text
    availability = await client.get(
        "/api/v1/public/ordering/stage-29-cafe/availability"
    )
    assert availability.status_code == 200
    assert "SHIFT_NOT_OPEN" in availability.json()["reasons"]


@pytest.mark.anyio
async def test_postgres_concurrent_submit_payment_and_kitchen_lifecycle(
    postgres_stage29_app,
) -> None:
    client, sessions, _ = postgres_stage29_app
    (
        client,
        sessions,
        headers,
        _,
        location_id,
        variant_id,
        station,
        register,
        shift,
    ) = await _setup((client, sessions))
    price = await client.put(
        f"/api/v1/menu/variants/{variant_id}/prices/{location_id}",
        headers=headers,
        json={"price_minor": 90000},
    )
    assert price.status_code == 200, price.text
    for payload in (
        _promotion_payload("POS only 50%", ["POS"], "50.0000"),
        _promotion_payload("QR 10%", ["QR"], "10.0000"),
    ):
        promotion = await client.post("/api/v1/promotions", headers=headers, json=payload)
        assert promotion.status_code == 201, promotion.text
        activated = await client.post(
            f"/api/v1/promotions/{promotion.json()['id']}/activate", headers=headers
        )
        assert activated.status_code == 200, activated.text
    cart = {
        "client_order_id": str(uuid4()),
        "station_token": station["public_token"],
        "items": [
            {
                "client_item_id": str(uuid4()),
                "variant_id": str(variant_id),
                "quantity": 1,
                "modifier_option_ids": [],
            }
        ],
    }
    token = station["public_token"]
    quote = await client.post(
        f"/api/v1/public/ordering/stage-29-cafe/quote?station={token}", json=cart
    )
    assert quote.status_code == 200, quote.text
    assert quote.json()["subtotal_minor"] == "90000"
    assert quote.json()["discount_minor"] == "9000"
    assert quote.json()["total_minor"] == "81000"
    assert [value["name"] for value in quote.json()["applied_promotions"]] == [
        "QR 10%"
    ]
    payload = {
        **cart,
        "quote_revision": quote.json()["quote_revision"],
        "guest_name": "Berik",
    }
    first, second = await asyncio.gather(
        client.post(
            f"/api/v1/public/ordering/stage-29-cafe/orders?station={token}", json=payload
        ),
        client.post(
            f"/api/v1/public/ordering/stage-29-cafe/orders?station={token}", json=payload
        ),
    )
    assert [first.status_code, second.status_code] == [201, 201]
    assert first.json()["status_token"] == second.json()["status_token"]
    conflict = await client.post(
        f"/api/v1/public/ordering/stage-29-cafe/orders?station={token}",
        json={**payload, "guest_name": "Another guest"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "ONLINE_ORDER_IDEMPOTENCY_CONFLICT"
    public_order = first.json()
    staff_orders = await client.get("/api/v1/online-orders", headers=headers)
    assert staff_orders.status_code == 200 and len(staff_orders.json()) == 1
    online = staff_orders.json()[0]
    assert online["order_number"] > 0
    async with sessions() as session:
        assert await session.scalar(select(func.count(OnlineOrderModel.id))) == 1
        assert await session.scalar(select(func.count(SalesOrderModel.id))) == 1
        assert await session.scalar(select(func.count(PaymentModel.id))) == 0
        assert await session.scalar(select(func.count(InventoryTransactionModel.id))) == 0
        assert await session.scalar(select(func.count(KitchenTicketModel.id))) == 0
        assert await session.scalar(select(func.count(FinanceEntryModel.id))) == 0
        online_row = await session.scalar(select(OnlineOrderModel))
        sale_row = await session.scalar(select(SalesOrderModel))
        assert online_row is not None and sale_row is not None
        assert (
            online_row.subtotal_minor,
            online_row.discount_minor,
            online_row.total_minor,
        ) == (90000, 9000, 81000)
        assert (
            sale_row.subtotal_minor,
            sale_row.discount_total_minor,
            sale_row.total_minor,
        ) == (90000, 9000, 81000)
        assert online_row.guest_name_snapshot == "Berik"
        assert sale_row.customer_name_snapshot == "Berik"
        assert sale_row.customer_id is None

    sales = await client.get(
        f"/api/v1/sales/orders/{online['sales_order_id']}", headers=headers
    )
    assert sales.status_code == 200, sales.text
    paired = await client.post(
        "/api/v1/pos/offline/devices/pair",
        headers=headers,
        json={"register_id": register["id"], "name": "Stage 29 POS"},
    )
    assert paired.status_code == 201, paired.text
    _, cookie = _cookie(paired)
    offline = await client.post(
        "/api/v1/pos/offline/sessions/start",
        headers={**headers, "cookie": cookie},
        json={"shift_id": shift["id"]},
    )
    assert offline.status_code == 201, offline.text
    offline_session = offline.json()
    source = sales.json()
    completed_at = offline_session["server_time"]
    offline_order = {
        "client_order_id": source["client_order_id"],
        "revision": source["version"] + 1,
        "base_server_version": source["version"],
        "catalog_snapshot_id": offline_session["catalog_snapshot_id"],
        "offline_display_number": source["number"],
        "created_at": source["created_at"],
        "updated_at": completed_at,
        "order_type": source["order_type"],
        "status": "PAID",
        "items": [
            {
                "client_item_id": item["client_item_id"],
                "variant_id": item["product_variant_id"],
                "selected_option_ids": [
                    modifier["modifier_option_id"] for modifier in item["modifiers"]
                ],
                "quantity": item["quantity"],
                "note": item["note"],
            }
            for item in source["items"]
        ],
        "manual_promotion_ids": [],
        "payment": {
            "client_payment_id": str(uuid4()),
            "completed_at": completed_at,
            "lines": [
                {
                    "method": "CASH",
                    "amount_minor": source["total_minor"],
                    "cash_received_minor": source["total_minor"],
                }
            ],
        },
    }
    sync_payload = {"session_id": offline_session["id"], "orders": [offline_order]}
    pending_sync = await client.post(
        "/api/v1/pos/offline/sync", headers={"cookie": cookie}, json=sync_payload
    )
    assert pending_sync.status_code == 200, pending_sync.text
    assert pending_sync.json()["results"][0]["status"] == "CONFLICT"
    assert pending_sync.json()["results"][0]["code"] == "ORDER_CHANGED_ON_SERVER"
    accepted = await client.post(
        f"/api/v1/online-orders/{online['id']}/accept",
        headers=headers,
        json={"client_action_id": str(uuid4())},
    )
    assert accepted.status_code == 200, accepted.text
    async with sessions() as session:
        assert await session.scalar(select(func.count(PaymentModel.id))) == 0
        assert await session.scalar(select(func.count(InventoryTransactionModel.id))) == 0
        assert await session.scalar(select(func.count(KitchenTicketModel.id))) == 0
        assert await session.scalar(select(func.count(FinanceEntryModel.id))) == 0
    offline_order["revision"] += 1
    sync_payload = {"session_id": offline_session["id"], "orders": [offline_order]}
    synced = await client.post(
        "/api/v1/pos/offline/sync", headers={"cookie": cookie}, json=sync_payload
    )
    assert synced.status_code == 200, synced.text
    assert synced.json()["results"][0]["status"] == "SYNCED", synced.text
    exact_replay = await client.post(
        "/api/v1/pos/offline/sync", headers={"cookie": cookie}, json=sync_payload
    )
    assert exact_replay.status_code == 200
    assert exact_replay.json()["results"] == synced.json()["results"]
    async with sessions() as session:
        claimed = await session.get(SalesOrderModel, UUID(online["sales_order_id"]))
        assert claimed is not None
        assert claimed.offline_session_id == UUID(offline_session["id"])
        assert claimed.pos_device_id == UUID(paired.json()["id"])
        assert claimed.order_source == "QR"
    await _dispatch_all(sessions)

    async with sessions() as session:
        outbox = (
            await session.execute(
                select(
                    OutboxEventModel.event_name,
                    OutboxEventModel.attempts,
                    OutboxEventModel.last_error,
                    OutboxEventModel.processed_at,
                ).order_by(OutboxEventModel.occurred_at, OutboxEventModel.id)
            )
        ).all()
        assert not [row for row in outbox if row.last_error], outbox
        assert await session.scalar(select(func.count(KitchenTicketModel.id))) == 1
        online_row = await session.scalar(select(OnlineOrderModel))
        assert online_row is not None and online_row.status == "PAID"

    stations = await client.get(
        f"/api/v1/kitchen/stations?location_id={location_id}", headers=headers
    )
    assert stations.status_code == 200, stations.text
    default_station = next(value for value in stations.json() if value["is_default"])
    board = await client.get(
        f"/api/v1/kitchen/stations/{default_station['id']}/board", headers=headers
    )
    assert board.status_code == 200, board.text
    ticket = board.json()["tickets"][0]
    assert len(board.json()["tickets"]) == 1
    work = ticket["items"][0]["work_items"][0]
    started = await client.post(
        f"/api/v1/kitchen/work-items/{work['id']}/start",
        headers=headers,
        json={"client_action_id": str(uuid4())},
    )
    assert started.status_code == 200, started.text
    await _dispatch_all(sessions)
    ready = await client.post(
        f"/api/v1/kitchen/work-items/{work['id']}/ready",
        headers=headers,
        json={"client_action_id": str(uuid4())},
    )
    assert ready.status_code == 200, ready.text
    await _dispatch_all(sessions)
    completed = await client.post(
        f"/api/v1/kitchen/tickets/{ticket['id']}/complete",
        headers=headers,
        json={"client_action_id": str(uuid4())},
    )
    assert completed.status_code == 200, completed.text
    await _dispatch_all(sessions)
    status = await client.get(
        f"/api/v1/public/ordering/orders/{public_order['status_token']}"
    )
    assert status.status_code == 200 and status.json()["status"] == "COMPLETED"
    channel_report = await client.get(
        "/api/v1/online-ordering/reports/channels", headers=headers
    )
    assert channel_report.status_code == 200, channel_report.text
    qr_report = next(
        value for value in channel_report.json() if value["order_source"] == "QR"
    )
    assert qr_report["orders_count"] == 1
    assert qr_report["gross_sales_minor"] == "81000"
    assert qr_report["net_revenue_minor"] == "81000"
    assert qr_report["average_order_value_minor"] == "81000"
    assert qr_report["acceptance_rate_percent"] == "100.00"
    assert qr_report["reject_rate_percent"] == "0.00"
    async with sessions() as session:
        assert await session.scalar(select(func.count(PaymentModel.id))) == 1
        assert await session.scalar(select(func.count(KitchenTicketModel.id))) == 1
        assert await session.scalar(select(func.count(OnlineOrderModel.id))) == 1
        assert await session.scalar(select(func.count(SalesOrderModel.id))) == 1
        assert await session.scalar(select(func.count(InventoryTransactionModel.id))) == 1
        payment = await session.scalar(select(PaymentModel))
        inventory_sale = await session.scalar(select(InventoryTransactionModel))
        assert payment is not None and payment.amount_minor == 81000
        assert inventory_sale is not None
        assert inventory_sale.type == "SALE" and inventory_sale.status == "POSTED"
        finance = {
            row.entry_role: row.amount
            for row in await session.scalars(select(FinanceEntryModel))
        }
        assert finance["REVENUE_GROSS"] == 900
        assert finance["SALES_DISCOUNT"] == -90
        assert finance["REVENUE_GROSS"] + finance["SALES_DISCOUNT"] == 810
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
        register_kitchen_handlers(handlers, KitchenService(session, organizations))
        register_online_ordering_handlers(
            handlers, OnlineOrderingService(session, organizations, get_settings())
        )
        dispatcher = OutboxDispatcher(
            OutboxRepository(session), handlers, "stage29-test", batch_size=100
        )
        while await dispatcher.run_once():
            pass
