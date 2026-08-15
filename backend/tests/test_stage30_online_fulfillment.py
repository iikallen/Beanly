import asyncio
from datetime import UTC, datetime, time, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, update
from test_offline_pos import _workspace
from test_offline_pos import postgres_offline_app as _postgres_offline_app
from test_stage29_online_ordering import _promotion_payload, _setup

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
from beanly.modules.online_ordering.infrastructure.db.models import (
    OnlineFulfillmentReservationModel,
    OnlineOrderFulfillmentModel,
    OnlineOrderModel,
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
from beanly.modules.refunds.infrastructure.db.models import RefundModel
from beanly.modules.sales.infrastructure.db.models import SalesOrderModel

postgres_stage30_app = _postgres_offline_app


def _cart(variant_id: UUID, **fulfillment) -> dict[str, object]:
    return {
        "client_order_id": str(uuid4()),
        "items": [
            {
                "client_item_id": str(uuid4()),
                "variant_id": str(variant_id),
                "quantity": 1,
                "modifier_option_ids": [],
            }
        ],
        **fulfillment,
    }


async def _stage30_setup(app_client):
    client, sessions, *_ = app_client
    (
        client,
        sessions,
        headers,
        organization_id,
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
    promotion = await client.post(
        "/api/v1/promotions",
        headers=headers,
        json=_promotion_payload("ONLINE 10%", ["ONLINE"], "10.0000"),
    )
    assert promotion.status_code == 201, promotion.text
    activated = await client.post(
        f"/api/v1/promotions/{promotion.json()['id']}/activate", headers=headers
    )
    assert activated.status_code == 200, activated.text
    settings = await client.put(
        "/api/v1/online-ordering/settings",
        headers=headers,
        json={
            "location_id": str(location_id),
            "public_slug": "stage-30-cafe",
            "enabled": True,
            "pickup_enabled": True,
            "delivery_enabled": True,
            "qr_dine_in_enabled": True,
            "register_id": register["id"],
            "preparation_minutes": 0,
            "slot_interval_minutes": 5,
            "slot_capacity": 1,
            "max_advance_minutes": 60,
            "cancellation_cutoff_minutes": 0,
            "delivery_minimum_order_minor": "0",
            "default_fulfillment_type": "PICKUP",
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
    zone = await client.post(
        "/api/v1/online-ordering/zones",
        headers=headers,
        json={
            "location_id": str(location_id),
            "name": "Center",
            "enabled": True,
            "delivery_fee_minor": "12000",
            "minimum_order_minor": "100000",
        },
    )
    assert zone.status_code == 201, zone.text
    return (
        client,
        sessions,
        headers,
        organization_id,
        location_id,
        variant_id,
        station,
        register,
        shift,
        zone.json(),
    )


def _code(response) -> str:
    return response.json()["detail"]["code"]


async def _submit(client, variant_id: UUID, **fulfillment):
    cart = _cart(variant_id, **fulfillment)
    quote = await client.post(
        "/api/v1/public/ordering/stage-30-cafe/quote", json=cart
    )
    assert quote.status_code == 200, quote.text
    submitted = await client.post(
        "/api/v1/public/ordering/stage-30-cafe/orders",
        json={
            **cart,
            "quote_revision": quote.json()["quote_revision"],
            "guest_name": "Stage 30 Guest",
            "guest_phone": "+77710000000",
        },
    )
    assert submitted.status_code == 201, submitted.text
    return submitted.json()


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
        dispatcher = OutboxDispatcher(
            OutboxRepository(session), handlers, "stage30-test", batch_size=100
        )
        while await dispatcher.run_once():
            pass


@pytest.mark.anyio
async def test_postgres_pricing_delivery_options_capacity_tenant_and_token(
    postgres_stage30_app,
) -> None:
    (
        client,
        sessions,
        headers,
        _,
        location_id,
        variant_id,
        _,
        _,
        _,
        zone,
    ) = await _stage30_setup(postgres_stage30_app)

    pickup = _cart(variant_id)
    pickup_quote = await client.post(
        "/api/v1/public/ordering/stage-30-cafe/quote", json=pickup
    )
    assert pickup_quote.status_code == 200, pickup_quote.text
    assert (
        pickup_quote.json()["subtotal_minor"],
        pickup_quote.json()["discount_minor"],
        pickup_quote.json()["fulfillment_fee_minor"],
        pickup_quote.json()["total_minor"],
    ) == ("90000", "9000", "0", "81000")

    delivery = _cart(
        variant_id,
        fulfillment_type="DELIVERY",
        delivery_zone_id=zone["id"],
        delivery_address="10 Abai Avenue, apartment 7",
        guest_instructions="Call on arrival",
    )
    below_minimum = await client.post(
        "/api/v1/public/ordering/stage-30-cafe/quote", json=delivery
    )
    assert below_minimum.status_code == 422
    assert _code(below_minimum) == "ONLINE_ORDER_CART_INVALID"
    lowered = await client.patch(
        f"/api/v1/online-ordering/zones/{zone['id']}",
        headers=headers,
        json={"minimum_order_minor": "80000"},
    )
    assert lowered.status_code == 200, lowered.text
    delivery_quote = await client.post(
        "/api/v1/public/ordering/stage-30-cafe/quote", json=delivery
    )
    assert delivery_quote.status_code == 200, delivery_quote.text
    assert (
        delivery_quote.json()["subtotal_minor"],
        delivery_quote.json()["discount_minor"],
        delivery_quote.json()["fulfillment_fee_minor"],
        delivery_quote.json()["total_minor"],
    ) == ("90000", "9000", "12000", "93000")
    assert delivery_quote.json()["delivery_zone"]["id"] == zone["id"]

    disabled = await client.patch(
        f"/api/v1/online-ordering/zones/{zone['id']}",
        headers=headers,
        json={"enabled": False},
    )
    assert disabled.status_code == 200, disabled.text
    disabled_zone = await client.post(
        "/api/v1/public/ordering/stage-30-cafe/quote", json=delivery
    )
    assert disabled_zone.status_code == 409
    assert _code(disabled_zone) == "ONLINE_FULFILLMENT_UNAVAILABLE"
    assert (
        await client.patch(
            f"/api/v1/online-ordering/zones/{zone['id']}",
            headers=headers,
            json={"enabled": True},
        )
    ).status_code == 200

    other_headers, _, other_location, _ = await _workspace(
        client, "stage30-other@example.com", "Stage 30 Other"
    )
    foreign_zone = await client.post(
        "/api/v1/online-ordering/zones",
        headers=other_headers,
        json={
            "location_id": str(other_location),
            "name": "Foreign",
            "delivery_fee_minor": "1",
            "minimum_order_minor": "0",
        },
    )
    assert foreign_zone.status_code == 201, foreign_zone.text
    foreign_delivery = {
        **delivery,
        "client_order_id": str(uuid4()),
        "delivery_zone_id": foreign_zone.json()["id"],
    }
    foreign = await client.post(
        "/api/v1/public/ordering/stage-30-cafe/quote", json=foreign_delivery
    )
    assert foreign.status_code == 409
    assert _code(foreign) == "ONLINE_FULFILLMENT_UNAVAILABLE"

    options = await client.get(
        "/api/v1/public/ordering/stage-30-cafe/fulfillment-options"
    )
    assert options.status_code == 200, options.text
    assert options.json()["pickup_enabled"] and options.json()["delivery_enabled"]
    assert [value["id"] for value in options.json()["delivery_zones"]] == [zone["id"]]
    assert options.json()["slots"]
    slot = options.json()["slots"][0]["starts_at"]
    assert options.json()["slots"][0]["remaining_capacity"] == 1

    too_late = _cart(
        variant_id,
        fulfillment_timing="SCHEDULED",
        requested_at=(
            datetime.now(UTC).replace(second=0, microsecond=0) + timedelta(hours=2)
        ).isoformat(),
    )
    rejected_horizon = await client.post(
        "/api/v1/public/ordering/stage-30-cafe/quote", json=too_late
    )
    assert rejected_horizon.status_code == 409
    assert _code(rejected_horizon) == "ONLINE_FULFILLMENT_UNAVAILABLE"

    carts = [
        _cart(
            variant_id,
            fulfillment_timing="SCHEDULED",
            requested_at=slot,
        )
        for _ in range(2)
    ]
    quotes = await asyncio.gather(*(
        client.post("/api/v1/public/ordering/stage-30-cafe/quote", json=cart)
        for cart in carts
    ))
    assert [response.status_code for response in quotes] == [200, 200]
    payloads = [
        {
            **cart,
            "quote_revision": quote.json()["quote_revision"],
            "guest_name": f"Guest {index}",
            "guest_phone": f"+7771000000{index}",
        }
        for index, (cart, quote) in enumerate(zip(carts, quotes, strict=True))
    ]
    submitted = await asyncio.gather(*(
        client.post("/api/v1/public/ordering/stage-30-cafe/orders", json=payload)
        for payload in payloads
    ))
    assert sorted(response.status_code for response in submitted) == [201, 409]
    loser = next(response for response in submitted if response.status_code == 409)
    assert _code(loser) == "ONLINE_FULFILLMENT_SLOT_UNAVAILABLE"
    winner = next(response for response in submitted if response.status_code == 201).json()
    assert winner["fulfillment_type"] == "PICKUP"
    assert winner["fulfillment_timing"] == "SCHEDULED"
    assert winner["requested_at"] == slot
    assert winner["promised_at"] == slot

    tampered_token = winner["status_token"][:-1] + (
        "A" if winner["status_token"][-1] != "A" else "B"
    )
    assert (
        await client.get(f"/api/v1/public/ordering/orders/{tampered_token}")
    ).status_code == 404
    staff_order = (await client.get("/api/v1/online-orders", headers=headers)).json()[0]
    assert (
        await client.get(
            f"/api/v1/online-orders/{staff_order['id']}", headers=other_headers
        )
    ).status_code == 404

    async with sessions() as session:
        assert await session.scalar(select(func.count(OnlineOrderModel.id))) == 1
        assert await session.scalar(select(func.count(SalesOrderModel.id))) == 1
        assert await session.scalar(select(func.count(OnlineOrderFulfillmentModel.id))) == 1
        assert (
            await session.scalar(select(func.count(OnlineFulfillmentReservationModel.id)))
            == 1
        )
        assert await session.scalar(select(func.count(PaymentModel.id))) == 0
        assert await session.scalar(select(func.count(InventoryTransactionModel.id))) == 0
        assert await session.scalar(select(func.count(KitchenTicketModel.id))) == 0
        assert await session.scalar(select(func.count(FinanceEntryModel.id))) == 0
        assert await session.scalar(select(func.count(RefundModel.id))) == 0


@pytest.mark.anyio
async def test_postgres_lifecycle_retries_rejection_guest_and_staff_cancel(
    postgres_stage30_app,
) -> None:
    (
        client,
        sessions,
        headers,
        _,
        location_id,
        variant_id,
        _,
        _,
        _,
        _,
    ) = await _stage30_setup(postgres_stage30_app)
    settings = await client.get(
        f"/api/v1/online-ordering/settings/{location_id}", headers=headers
    )
    assert settings.status_code == 200, settings.text
    settings_payload = {
        **settings.json(),
        "slot_capacity": 10,
        "schedules": settings.json()["schedules"],
    }
    updated = await client.put(
        "/api/v1/online-ordering/settings", headers=headers, json=settings_payload
    )
    assert updated.status_code == 200, updated.text
    disabled = {**updated.json(), "enabled": False, "schedules": updated.json()["schedules"]}
    assert (
        await client.put(
            "/api/v1/online-ordering/settings", headers=headers, json=disabled
        )
    ).status_code == 200
    assert (
        await client.get(
            "/api/v1/public/ordering/stage-30-cafe/fulfillment-options"
        )
    ).json()["slots"] == []
    assert (
        await client.put(
            "/api/v1/online-ordering/settings", headers=headers, json=settings_payload
        )
    ).status_code == 200
    assert (
        await client.post(
            "/api/v1/online-ordering/pause",
            headers=headers,
            json={
                "location_id": str(location_id),
                "minutes": 15,
                "reason": "Capacity test",
            },
        )
    ).status_code == 200
    assert (
        await client.get(
            "/api/v1/public/ordering/stage-30-cafe/fulfillment-options"
        )
    ).json()["slots"] == []
    assert (
        await client.post(
            "/api/v1/online-ordering/resume",
            headers=headers,
            json={"location_id": str(location_id)},
        )
    ).status_code == 200
    delivery_only = {
        **updated.json(),
        "pickup_enabled": False,
        "delivery_enabled": True,
        "default_fulfillment_type": "DELIVERY",
        "schedules": updated.json()["schedules"],
    }
    assert (
        await client.put(
            "/api/v1/online-ordering/settings", headers=headers, json=delivery_only
        )
    ).status_code == 200
    assert (
        await client.get(
            "/api/v1/public/ordering/stage-30-cafe/fulfillment-options"
        )
    ).json()["slots"]
    assert (
        await client.put(
            "/api/v1/online-ordering/settings", headers=headers, json=settings_payload
        )
    ).status_code == 200
    options = await client.get(
        "/api/v1/public/ordering/stage-30-cafe/fulfillment-options"
    )
    assert options.status_code == 200, options.text
    scheduled = {
        "fulfillment_timing": "SCHEDULED",
        "requested_at": options.json()["slots"][0]["starts_at"],
    }

    await _submit(client, variant_id, **scheduled)
    accepted = (await client.get("/api/v1/online-orders", headers=headers)).json()[0]
    invalid_ready = await client.post(
        f"/api/v1/online-orders/{accepted['id']}/ready",
        headers=headers,
        json={"client_action_id": str(uuid4())},
    )
    assert invalid_ready.status_code == 422
    assert _code(invalid_ready) == "ONLINE_ORDER_INVALID_STATE"
    accept_action = str(uuid4())
    accept_payload = {"client_action_id": accept_action}
    first_accept = await client.post(
        f"/api/v1/online-orders/{accepted['id']}/accept",
        headers=headers,
        json=accept_payload,
    )
    retry_accept = await client.post(
        f"/api/v1/online-orders/{accepted['id']}/accept",
        headers=headers,
        json=accept_payload,
    )
    assert first_accept.status_code == retry_accept.status_code == 200
    assert first_accept.json()["status"] == retry_accept.json()["status"] == "AWAITING_PAYMENT"
    conflicting_action = await client.post(
        f"/api/v1/online-orders/{accepted['id']}/reject",
        headers=headers,
        json={"client_action_id": accept_action, "reason": "No stock"},
    )
    assert conflicting_action.status_code == 409
    assert _code(conflicting_action) == "ONLINE_ORDER_IDEMPOTENCY_CONFLICT"

    await _submit(client, variant_id, **scheduled)
    rejected = (await client.get("/api/v1/online-orders", headers=headers)).json()[0]
    reject_payload = {"client_action_id": str(uuid4()), "reason": "Closing early"}
    first_reject = await client.post(
        f"/api/v1/online-orders/{rejected['id']}/reject",
        headers=headers,
        json=reject_payload,
    )
    retry_reject = await client.post(
        f"/api/v1/online-orders/{rejected['id']}/reject",
        headers=headers,
        json=reject_payload,
    )
    assert first_reject.status_code == retry_reject.status_code == 200
    assert first_reject.json()["status"] == retry_reject.json()["status"] == "REJECTED"

    guest = await _submit(client, variant_id, **scheduled)
    guest_url = f"/api/v1/public/ordering/orders/{guest['status_token']}/cancel"
    first_guest_cancel = await client.post(guest_url)
    retry_guest_cancel = await client.post(guest_url)
    assert first_guest_cancel.status_code == retry_guest_cancel.status_code == 200
    assert first_guest_cancel.json()["status"] == retry_guest_cancel.json()["status"] == "CANCELLED"

    await _submit(client, variant_id, **scheduled)
    staff = (await client.get("/api/v1/online-orders", headers=headers)).json()[0]
    assert (
        await client.post(
            f"/api/v1/online-orders/{staff['id']}/accept",
            headers=headers,
            json={"client_action_id": str(uuid4())},
        )
    ).status_code == 200
    cancel_payload = {
        "client_action_id": str(uuid4()),
        "reason": "Guest called the cafe",
    }
    first_staff_cancel = await client.post(
        f"/api/v1/online-orders/{staff['id']}/cancel",
        headers=headers,
        json=cancel_payload,
    )
    retry_staff_cancel = await client.post(
        f"/api/v1/online-orders/{staff['id']}/cancel",
        headers=headers,
        json=cancel_payload,
    )
    assert first_staff_cancel.status_code == retry_staff_cancel.status_code == 200
    assert first_staff_cancel.json()["status"] == retry_staff_cancel.json()["status"] == "CANCELLED"

    cutoff_settings = {
        **updated.json(),
        "cancellation_cutoff_minutes": 60,
        "schedules": updated.json()["schedules"],
    }
    assert (
        await client.put(
            "/api/v1/online-ordering/settings",
            headers=headers,
            json=cutoff_settings,
        )
    ).status_code == 200
    cutoff_order = await _submit(client, variant_id, **scheduled)
    cutoff_cancel = await client.post(
        f"/api/v1/public/ordering/orders/{cutoff_order['status_token']}/cancel"
    )
    assert cutoff_cancel.status_code == 409
    assert _code(cutoff_cancel) == "ONLINE_ORDER_CANCELLATION_FORBIDDEN"
    no_channels = {
        **cutoff_settings,
        "pickup_enabled": False,
        "delivery_enabled": False,
        "qr_dine_in_enabled": False,
    }
    assert (
        await client.put(
            "/api/v1/online-ordering/settings", headers=headers, json=no_channels
        )
    ).status_code == 200
    no_channel_options = await client.get(
        "/api/v1/public/ordering/stage-30-cafe/fulfillment-options"
    )
    assert no_channel_options.status_code == 200
    assert no_channel_options.json()["slots"] == []

    async with sessions() as session:
        reservation_statuses = list(
            await session.scalars(
                select(OnlineFulfillmentReservationModel.status).order_by(
                    OnlineFulfillmentReservationModel.created_at
                )
            )
        )
        assert reservation_statuses == [
            "ACTIVE",
            "RELEASED",
            "RELEASED",
            "RELEASED",
            "ACTIVE",
        ]
        assert await session.scalar(select(func.count(RefundModel.id))) == 0
        assert await session.scalar(select(func.count(PaymentModel.id))) == 0


@pytest.mark.anyio
async def test_postgres_delivery_payment_cancel_reconciles_all_projections_once(
    postgres_stage30_app,
) -> None:
    (
        client,
        sessions,
        headers,
        _,
        _,
        variant_id,
        _,
        _,
        _,
        zone,
    ) = await _stage30_setup(postgres_stage30_app)
    lowered = await client.patch(
        f"/api/v1/online-ordering/zones/{zone['id']}",
        headers=headers,
        json={"minimum_order_minor": "80000"},
    )
    assert lowered.status_code == 200, lowered.text
    await _submit(
        client,
        variant_id,
        fulfillment_type="DELIVERY",
        delivery_zone_id=zone["id"],
        delivery_address="10 Abai Avenue, apartment 7",
    )
    staff = (await client.get("/api/v1/online-orders", headers=headers)).json()[0]
    assert (
        staff["subtotal_minor"],
        staff["discount_minor"],
        staff["fulfillment_fee_minor"],
        staff["total_minor"],
    ) == ("90000", "9000", "12000", "93000")
    accepted = await client.post(
        f"/api/v1/online-orders/{staff['id']}/accept",
        headers=headers,
        json={"client_action_id": str(uuid4())},
    )
    assert accepted.status_code == 200, accepted.text
    payment = await client.post(
        f"/api/v1/payments/orders/{staff['sales_order_id']}/complete",
        headers=headers,
        json={
            "client_payment_id": str(uuid4()),
            "lines": [
                {
                    "method": "CASH",
                    "amount_minor": "93000",
                    "cash_received_minor": "93000",
                }
            ],
        },
    )
    assert payment.status_code == 201, payment.text
    assert payment.json()["amount_minor"] == "93000"
    await _dispatch_all(sessions)
    paid = await client.get(f"/api/v1/online-orders/{staff['id']}", headers=headers)
    assert paid.status_code == 200 and paid.json()["status"] == "PAID"

    cancel_payload = {
        "client_action_id": str(uuid4()),
        "reason": "Delivery cancelled after capture",
    }
    cancelled, replay = await asyncio.gather(*(
        client.post(
            f"/api/v1/online-orders/{staff['id']}/cancel",
            headers=headers,
            json=cancel_payload,
        )
        for _ in range(2)
    ))
    assert cancelled.status_code == replay.status_code == 200
    assert cancelled.json()["status"] == replay.json()["status"] == "CANCELLED"
    await _dispatch_all(sessions)

    async with sessions() as session:
        refund_event = await session.scalar(
            select(OutboxEventModel).where(
                OutboxEventModel.event_name == "refund.completed"
            )
        )
        assert refund_event is not None
        await session.execute(
            update(OutboxEventModel)
            .where(OutboxEventModel.id == refund_event.id)
            .values(processed_at=None, available_at=datetime.now(UTC))
        )
        await session.commit()
    await _dispatch_all(sessions)

    async with sessions() as session:
        refund = await session.scalar(select(RefundModel))
        assert refund is not None
        assert refund.total_amount_minor == 93000
        assert refund.fulfillment_fee_minor == 12000
        assert await session.scalar(select(func.count(RefundModel.id))) == 1
        assert await session.scalar(
            select(func.count(OutboxEventModel.id)).where(
                OutboxEventModel.event_name == "online.order_cancelled"
            )
        ) == 1
        inventory = list(
            await session.scalars(
                select(InventoryTransactionModel).order_by(
                    InventoryTransactionModel.created_at
                )
            )
        )
        assert [row.type for row in inventory] == ["SALE", "RETURN_IN"]
        tickets = list(await session.scalars(select(KitchenTicketModel)))
        assert len(tickets) == 1 and tickets[0].status == "CANCELLED"
        assert tickets[0].order_source == "ONLINE"
        finance = list(await session.scalars(select(FinanceEntryModel)))
        assert [(row.entry_role, row.amount) for row in finance].count(
            ("REVENUE_REFUND", -930)
        ) == 1
        sale_finance = {
            row.entry_role: row.amount
            for row in finance
            if row.source_type == "PAYMENT"
        }
        assert sale_finance["REVENUE_GROSS"] == 1020
        assert sale_finance["SALES_DISCOUNT"] == -90
        assert (
            sale_finance["REVENUE_GROSS"] + sale_finance["SALES_DISCOUNT"]
        ) == 930
        analytics = await session.scalar(select(AnalyticsSalesDailyModel))
        assert analytics is not None
        assert analytics.gross_revenue_amount == 1020
        assert analytics.discount_amount == 90
        assert analytics.revenue_amount == analytics.refund_amount == 930
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


@pytest.mark.anyio
async def test_postgres_paid_ready_complete_retries_consume_reservation(
    postgres_stage30_app,
) -> None:
    (
        client,
        sessions,
        headers,
        _,
        _,
        variant_id,
        _,
        _,
        _,
        _,
    ) = await _stage30_setup(postgres_stage30_app)
    options = await client.get(
        "/api/v1/public/ordering/stage-30-cafe/fulfillment-options"
    )
    assert options.status_code == 200, options.text
    public = await _submit(
        client,
        variant_id,
        fulfillment_timing="SCHEDULED",
        requested_at=options.json()["slots"][0]["starts_at"],
    )
    staff = (await client.get("/api/v1/online-orders", headers=headers)).json()[0]
    assert (
        await client.post(
            f"/api/v1/online-orders/{staff['id']}/accept",
            headers=headers,
            json={"client_action_id": str(uuid4())},
        )
    ).status_code == 200
    payment = await client.post(
        f"/api/v1/payments/orders/{staff['sales_order_id']}/complete",
        headers=headers,
        json={
            "client_payment_id": str(uuid4()),
            "lines": [
                {
                    "method": "CASH",
                    "amount_minor": "81000",
                    "cash_received_minor": "81000",
                }
            ],
        },
    )
    assert payment.status_code == 201, payment.text
    await _dispatch_all(sessions)

    ready_payload = {"client_action_id": str(uuid4())}
    ready, ready_retry = await asyncio.gather(*(
        client.post(
            f"/api/v1/online-orders/{staff['id']}/ready",
            headers=headers,
            json=ready_payload,
        )
        for _ in range(2)
    ))
    assert ready.status_code == ready_retry.status_code == 200
    assert ready.json()["status"] == ready_retry.json()["status"] == "READY"
    complete_payload = {"client_action_id": str(uuid4())}
    completed = await client.post(
        f"/api/v1/online-orders/{staff['id']}/complete",
        headers=headers,
        json=complete_payload,
    )
    completed_retry = await client.post(
        f"/api/v1/online-orders/{staff['id']}/complete",
        headers=headers,
        json=complete_payload,
    )
    assert completed.status_code == completed_retry.status_code == 200
    assert completed.json()["status"] == completed_retry.json()["status"] == "COMPLETED"
    forbidden_cancel = await client.post(
        f"/api/v1/online-orders/{staff['id']}/cancel",
        headers=headers,
        json={"client_action_id": str(uuid4()), "reason": "Too late"},
    )
    assert forbidden_cancel.status_code == 422
    assert _code(forbidden_cancel) == "ONLINE_ORDER_INVALID_STATE"
    public_status = await client.get(
        f"/api/v1/public/ordering/orders/{public['status_token']}"
    )
    assert public_status.status_code == 200
    assert public_status.json()["status"] == "COMPLETED"

    async with sessions() as session:
        reservation = await session.scalar(select(OnlineFulfillmentReservationModel))
        assert reservation is not None and reservation.status == "CONSUMED"
        assert await session.scalar(select(func.count(PaymentModel.id))) == 1
        assert await session.scalar(select(func.count(KitchenTicketModel.id))) == 1
