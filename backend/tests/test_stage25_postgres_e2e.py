import asyncio
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from test_payments import _order, _register_shift, _variant, _workspace
from test_refunds_fiscal import postgres_stage21_app  # noqa: F401

from beanly.core.events.envelope import EventEnvelope
from beanly.core.events.handlers.registry import EventHandlerRegistry
from beanly.core.events.outbox.dispatcher import OutboxDispatcher
from beanly.core.events.outbox.models import OutboxEventModel
from beanly.core.events.outbox.repositories import OutboxRepository
from beanly.modules.analytics.application.projection_service import AnalyticsProjectionService
from beanly.modules.analytics.infrastructure.db.models import AnalyticsSalesDailyModel
from beanly.modules.analytics.infrastructure.db.repositories import (
    SqlAlchemyAnalyticsRepository,
)
from beanly.modules.analytics.infrastructure.handlers import register_analytics_handlers
from beanly.modules.analytics.infrastructure.source_reader import (
    SqlAlchemyAnalyticsSourceReader,
)
from beanly.modules.customers.infrastructure.db.models import LoyaltyLedgerEntryModel
from beanly.modules.customers.infrastructure.handlers import register_customer_handlers
from beanly.modules.customers.infrastructure.service import CustomerProjectionService
from beanly.modules.finance.application.projection_service import FinanceProjectionService
from beanly.modules.finance.infrastructure.db.models import FinanceEntryModel
from beanly.modules.finance.infrastructure.db.repositories import SqlAlchemyFinanceRepository
from beanly.modules.finance.infrastructure.handlers import register_finance_handlers
from beanly.modules.finance.infrastructure.source_reader import SqlAlchemyFinanceSourceReader


def _coded(response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.json()["detail"]["code"] == code


async def _pay(client, headers, order: dict[str, object]) -> dict[str, object]:
    amount = int(order["total_minor"])
    response = await client.post(
        f"/api/v1/payments/orders/{order['id']}/complete",
        headers=headers,
        json={
            "client_payment_id": str(uuid4()),
            "lines": [
                {
                    "method": "CASH",
                    "amount_minor": amount,
                    "cash_received_minor": amount,
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _refund(
    client,
    headers,
    order: dict[str, object],
    payment: dict[str, object],
    amount_minor: int | None = None,
):
    amount = amount_minor if amount_minor is not None else int(payment["amount_minor"])
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
                    "original_payment_line_id": payment["lines"][0]["id"],
                    "amount_minor": amount,
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.anyio
async def test_loyalty_reservation_payment_and_refund_ledger_are_exact_once_per_payment(
    postgres_stage21_app,  # noqa: F811
) -> None:
    client, sessions, _, _ = postgres_stage21_app
    headers, organization_id, location_id, warehouse_id = await _workspace(
        client, "stage25-ledger@example.com", "Stage 25 ledger"
    )
    configured = await client.patch(
        "/api/v1/loyalty/program",
        headers=headers,
        json={
            "earn_rate_bps": 10000,
            "point_value_minor": "100",
            "birthday_reward_points": "0",
            "is_active": True,
        },
    )
    assert configured.status_code == 200, configured.text
    customer = await client.post(
        "/api/v1/customers",
        headers=headers,
        json={"phone": "+77015550125", "first_name": "Ledger"},
    )
    assert customer.status_code == 201, customer.text
    customer_id = customer.json()["id"]
    shift = await _register_shift(client, headers, location_id, warehouse_id)

    first_variant = await _variant(client, headers, "Stage 25 earn", 50000)
    first_order = await _order(client, headers, shift["id"], first_variant)
    quantity = await client.patch(
        f"/api/v1/sales/orders/{first_order['id']}/items/{first_order['items'][0]['id']}",
        headers=headers,
        json={"quantity": 2},
    )
    assert quantity.status_code == 200, quantity.text
    first_order = quantity.json()
    attached = await client.put(
        f"/api/v1/sales/orders/{first_order['id']}/customer",
        headers=headers,
        json={"customer_id": customer_id},
    )
    assert attached.status_code == 200, attached.text
    first_order = attached.json()
    first_payment = await _pay(client, headers, first_order)
    paid_first = await client.get(
        f"/api/v1/sales/orders/{first_order['id']}", headers=headers
    )
    assert paid_first.status_code == 200, paid_first.text
    assert (
        paid_first.json()["customer_id"],
        paid_first.json()["customer_name_snapshot"],
        paid_first.json()["customer_phone_snapshot"],
    ) == (customer_id, "Ledger", "+77015550125")
    _coded(
        await client.put(
            f"/api/v1/sales/orders/{first_order['id']}/customer",
            headers=headers,
            json={"customer_id": None},
        ),
        409,
        "ORDER_IMMUTABLE",
    )
    loyalty = await client.get(f"/api/v1/customers/{customer_id}/loyalty", headers=headers)
    assert loyalty.status_code == 200, loyalty.text
    assert loyalty.json()["points_balance"] == "1000"

    second_variant = await _variant(client, headers, "Stage 25 redeem", 100100)
    second_order = await _order(client, headers, shift["id"], second_variant)
    attached = await client.put(
        f"/api/v1/sales/orders/{second_order['id']}/customer",
        headers=headers,
        json={"customer_id": customer_id},
    )
    assert attached.status_code == 200, attached.text
    second_order = attached.json()
    quote = await client.post(
        f"/api/v1/sales/orders/{second_order['id']}/loyalty/quote",
        headers=headers,
        json={"points": "1001"},
    )
    assert quote.status_code == 200, quote.text
    assert quote.json() == {
        "points": "1000",
        "discount_minor": "100000",
        "balance_points": "1000",
    }
    redemption_id = str(uuid4())

    async def redeem():
        return await client.post(
            f"/api/v1/sales/orders/{second_order['id']}/loyalty/redeem",
            headers=headers,
            json={"client_redemption_id": redemption_id, "points": "1001"},
        )

    replays = await asyncio.gather(redeem(), redeem())
    assert [response.status_code for response in replays] == [200, 200]
    assert replays[0].json() == replays[1].json()
    redeemed = replays[0]
    assert redeemed.json()["total_minor"] == "100"
    _coded(
        await client.post(
            f"/api/v1/sales/orders/{second_order['id']}/loyalty/redeem",
            headers=headers,
            json={"client_redemption_id": redemption_id, "points": "999"},
        ),
        409,
        "LOYALTY_IDEMPOTENCY_CONFLICT",
    )
    _coded(
        await client.patch(
            f"/api/v1/sales/orders/{second_order['id']}/items/"
            f"{second_order['items'][0]['id']}",
            headers=headers,
            json={"quantity": 2},
        ),
        409,
        "ORDER_IMMUTABLE",
    )
    _coded(
        await client.put(
            f"/api/v1/sales/orders/{second_order['id']}/customer",
            headers=headers,
            json={"customer_id": None},
        ),
        409,
        "ORDER_IMMUTABLE",
    )
    _coded(
        await client.post(
            f"/api/v1/sales/orders/{second_order['id']}/cancel",
            headers=headers,
            json={"reason": "Reservation lifecycle test"},
        ),
        409,
        "ORDER_IMMUTABLE",
    )
    released = await client.delete(
        f"/api/v1/sales/orders/{second_order['id']}/loyalty/redemption",
        headers=headers,
    )
    assert released.status_code == 200, released.text
    assert released.json()["total_minor"] == "100100"
    loyalty = await client.get(f"/api/v1/customers/{customer_id}/loyalty", headers=headers)
    assert loyalty.json()["available_points"] == "1000"

    redeemed = await client.post(
        f"/api/v1/sales/orders/{second_order['id']}/loyalty/redeem",
        headers=headers,
        json={"client_redemption_id": str(uuid4()), "points": "1000"},
    )
    assert redeemed.status_code == 200, redeemed.text
    second_order = redeemed.json()
    disabled = await client.patch(
        "/api/v1/loyalty/program",
        headers=headers,
        json={
            "earn_rate_bps": 10000,
            "point_value_minor": "100",
            "birthday_reward_points": "0",
            "is_active": False,
        },
    )
    assert disabled.status_code == 200, disabled.text
    blocked_payment = await client.post(
        f"/api/v1/payments/orders/{second_order['id']}/complete",
        headers=headers,
        json={
            "client_payment_id": str(uuid4()),
            "lines": [
                {"method": "CASH", "amount_minor": 100, "cash_received_minor": 100}
            ],
        },
    )
    _coded(blocked_payment, 409, "LOYALTY_RESERVATION_INVALID")
    assert (
        await client.patch(
            "/api/v1/loyalty/program",
            headers=headers,
            json={
                "earn_rate_bps": 10000,
                "point_value_minor": "100",
                "birthday_reward_points": "0",
                "is_active": True,
            },
        )
    ).status_code == 200
    second_payment = await _pay(client, headers, second_order)
    loyalty = await client.get(f"/api/v1/customers/{customer_id}/loyalty", headers=headers)
    assert loyalty.json()["points_balance"] == "1"

    first_refund = await _refund(client, headers, first_order, first_payment, 50000)
    first_refund_final = await _refund(client, headers, first_order, first_payment, 50000)
    second_refund = await _refund(client, headers, second_order, second_payment)

    async def project_refund(refund):
        async with sessions() as projection_session:
            await CustomerProjectionService(projection_session).apply_refund(
                UUID(refund["id"]),
                organization_id,
                datetime.fromisoformat(refund["completed_at"]),
            )
            await projection_session.commit()

    await asyncio.gather(
        project_refund(first_refund),
        project_refund(first_refund_final),
    )
    async with sessions() as session:
        projection = CustomerProjectionService(session)
        for refund in (
            first_refund,
            first_refund,
            first_refund_final,
            second_refund,
            second_refund,
        ):
            await projection.apply_refund(
                UUID(refund["id"]),
                organization_id,
                datetime.fromisoformat(refund["completed_at"]),
            )
            await session.commit()

    loyalty = await client.get(f"/api/v1/customers/{customer_id}/loyalty", headers=headers)
    assert loyalty.status_code == 200, loyalty.text
    assert loyalty.json()["points_balance"] == "0"
    assert loyalty.json()["available_points"] == "0"
    history = await client.get(
        f"/api/v1/customers/{customer_id}/orders",
        headers=headers,
    )
    assert history.status_code == 200, history.text
    assert all(item["refunded_minor"].lstrip("-").isdigit() for item in history.json())
    deltas = sorted(
        (entry["kind"], entry["points_delta"])
        for entry in loyalty.json()["entries"]
    )
    assert deltas == sorted(
        [
            ("EARN", "1000"),
            ("EARN", "1"),
            ("REDEEM", "-1000"),
            ("REFUND_REVERSAL", "-1000"),
            ("REFUND_REVERSAL", "-1"),
            ("REDEMPTION_REVERSAL", "1000"),
        ]
    )

    async with sessions() as session:
        assert await session.scalar(
            select(func.count()).select_from(LoyaltyLedgerEntryModel)
        ) == 6
        payloads = [
            str(value)
            for value in await session.scalars(select(OutboxEventModel.payload))
        ]
        assert not any(
            "+77015550125" in value or "ledger" in value.casefold()
            for value in payloads
        )

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
        dispatcher = OutboxDispatcher(OutboxRepository(session), handlers, "stage25-invariants")
        while await dispatcher.run_once():
            pass
        assert await session.scalar(
            select(func.coalesce(func.sum(FinanceEntryModel.amount), 0)).where(
                FinanceEntryModel.organization_id == organization_id
            )
        ) == Decimal(0)
        analytics = await session.scalar(
            select(AnalyticsSalesDailyModel).where(
                AnalyticsSalesDailyModel.organization_id == organization_id
            )
        )
        assert analytics is not None
        assert (
            analytics.gross_revenue_amount,
            analytics.discount_amount,
            analytics.revenue_amount,
            analytics.refund_amount,
        ) == (Decimal(2001), Decimal(1000), Decimal(1001), Decimal(1001))

    updated = await client.patch(
        f"/api/v1/customers/{customer_id}",
        headers=headers,
        json={"first_name": "Changed", "phone": "+77019999999"},
    )
    assert updated.status_code == 200, updated.text
    async with sessions() as session:
        customer_handlers = EventHandlerRegistry()
        register_customer_handlers(customer_handlers, CustomerProjectionService(session))
        await customer_handlers.dispatch(
            EventEnvelope(
                uuid4(),
                organization_id,
                "payment.completed",
                1,
                "payment",
                UUID(first_payment["id"]),
                {
                    "payment_id": first_payment["id"],
                    "order_id": first_order["id"],
                    "amount_minor": first_payment["amount_minor"],
                },
                datetime.fromisoformat(first_payment["completed_at"]),
            )
        )
        await session.commit()
    loyalty = await client.get(f"/api/v1/customers/{customer_id}/loyalty", headers=headers)
    assert loyalty.json()["points_balance"] == "0"
    for order in (first_order, second_order):
        persisted = await client.get(f"/api/v1/sales/orders/{order['id']}", headers=headers)
        assert persisted.status_code == 200, persisted.text
        assert (
            persisted.json()["customer_name_snapshot"],
            persisted.json()["customer_phone_snapshot"],
        ) == ("Ledger", "+77015550125")
    archived = await client.delete(f"/api/v1/customers/{customer_id}", headers=headers)
    assert archived.status_code == 204, archived.text
    _coded(
        await client.get(f"/api/v1/customers/{customer_id}", headers=headers),
        404,
        "CUSTOMER_NOT_FOUND",
    )
    persisted = await client.get(f"/api/v1/sales/orders/{first_order['id']}", headers=headers)
    assert persisted.status_code == 200, persisted.text
    assert persisted.json()["customer_name_snapshot"] == "Ledger"
    assert persisted.json()["customer_phone_snapshot"] == "+77015550125"
