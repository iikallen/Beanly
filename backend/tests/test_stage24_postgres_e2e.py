import asyncio
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from test_payments import _order, _register_shift, _variant, _workspace
from test_refunds_fiscal import postgres_stage21_app  # noqa: F401

from beanly.core.events.handlers.registry import EventHandlerRegistry
from beanly.core.events.outbox.dispatcher import OutboxDispatcher
from beanly.core.events.outbox.repositories import OutboxRepository
from beanly.modules.analytics.application.projection_service import AnalyticsProjectionService
from beanly.modules.analytics.infrastructure.db.models import (
    AnalyticsPromotionsDailyModel,
    AnalyticsSalesDailyModel,
)
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
from beanly.modules.fiscal.infrastructure.db.models import (
    FiscalSaleSnapshotLineModel,
    FiscalSaleSnapshotModel,
)
from beanly.modules.inventory.infrastructure.db.models import InventoryTransactionModel
from beanly.modules.payments.infrastructure.db.models import PaymentModel
from beanly.modules.promotions.infrastructure.db.models import SalesOrderDiscountModel
from beanly.modules.refunds.infrastructure.db.models import RefundDiscountAllocationModel
from beanly.modules.sales.infrastructure.db.models import SalesOrderModel


def _promotion_payload() -> dict[str, object]:
    return {
        "name": "LAST10",
        "pos_name": "LAST10",
        "application_mode": "CODE",
        "discount_kind": "PERCENT",
        "scope": "ORDER",
        "percent_rate": "20.0000",
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
async def test_last_redemption_is_serialized_before_money_and_paid_snapshot_is_net(
    postgres_stage21_app,  # noqa: F811
) -> None:
    client, sessions, _, _ = postgres_stage21_app
    headers, organization_id, location_id, warehouse_id = await _workspace(
        client, "stage24-cap@example.com", "Stage 24 cap"
    )
    shift = await _register_shift(client, headers, location_id, warehouse_id)
    variant_id = await _variant(client, headers, "Cap coffee", 100000)

    created = await client.post("/api/v1/promotions", headers=headers, json=_promotion_payload())
    assert created.status_code == 201, created.text
    promotion_id = created.json()["id"]
    assert (
        await client.post(f"/api/v1/promotions/{promotion_id}/activate", headers=headers)
    ).status_code == 200
    code = await client.post(
        f"/api/v1/promotions/{promotion_id}/codes",
        headers=headers,
        json={"code": "LAST10", "max_redemptions": 1},
    )
    assert code.status_code == 201, code.text

    orders = [await _order(client, headers, shift["id"], variant_id) for _ in range(2)]
    for order in orders:
        applied = await client.post(
            f"/api/v1/sales/orders/{order['id']}/discounts/code",
            headers=headers,
            json={"client_discount_id": str(uuid4()), "code": " last 10 "},
        )
        assert applied.status_code == 200, applied.text
        assert applied.json()["subtotal_minor"] == "100000"
        assert applied.json()["discount_total_minor"] == "20000"
        assert applied.json()["total_minor"] == "80000"

    async def pay(order_id: str):
        return await client.post(
            f"/api/v1/payments/orders/{order_id}/complete",
            headers=headers,
            json={
                "client_payment_id": str(uuid4()),
                "lines": [
                    {
                        "method": "CASH",
                        "amount_minor": 80000,
                        "cash_received_minor": 80000,
                    }
                ],
            },
        )

    responses = await asyncio.gather(
        *(pay(order["id"]) for order in orders), return_exceptions=True
    )
    successful = [response for response in responses if getattr(response, "status_code", 0) == 201]
    assert len(successful) == 1
    payment_body = successful[0].json()
    paid_order_body = next(order for order in orders if order["id"] == payment_body["order_id"])

    async with sessions() as session:
        handlers = EventHandlerRegistry()
        register_finance_handlers(
            handlers,
            FinanceProjectionService(
                SqlAlchemyFinanceRepository(session), SqlAlchemyFinanceSourceReader(session)
            ),
        )
        register_analytics_handlers(
            handlers,
            AnalyticsProjectionService(
                SqlAlchemyAnalyticsRepository(session),
                SqlAlchemyAnalyticsSourceReader(session),
            ),
        )
        dispatcher = OutboxDispatcher(OutboxRepository(session), handlers, "stage24-payment")
        assert await dispatcher.run_once() > 0

        finance = {
            row.entry_role: row.amount
            for row in await session.scalars(
                select(FinanceEntryModel).where(
                    FinanceEntryModel.source_id == UUID(payment_body["id"])
                )
            )
        }
        assert finance["REVENUE_GROSS"] == 1000
        assert finance["SALES_DISCOUNT"] == -200
        assert finance["REVENUE_GROSS"] + finance["SALES_DISCOUNT"] == 800

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
        ) == (1000, 200, 800)
        promotion_analytics = await session.scalar(
            select(AnalyticsPromotionsDailyModel).where(
                AnalyticsPromotionsDailyModel.promotion_id == UUID(promotion_id)
            )
        )
        assert promotion_analytics is not None
        assert promotion_analytics.discount_amount == 200
        assert promotion_analytics.applications_count == 1
        assert promotion_analytics.items_count == 1
        assert promotion_analytics.gross_eligible_amount == 1000

    refund = await client.post(
        "/api/v1/refunds",
        headers=headers,
        json={
            "client_refund_id": str(uuid4()),
            "payment_id": payment_body["id"],
            "reason": "CUSTOMER_RETURN",
            "lines": [
                {
                    "order_item_id": paid_order_body["items"][0]["id"],
                    "quantity": 1,
                    "restock_quantity": 0,
                }
            ],
            "payment_lines": [
                {
                    "original_payment_line_id": payment_body["lines"][0]["id"],
                    "amount_minor": 80000,
                }
            ],
        },
    )
    assert refund.status_code == 201, refund.text
    refund_line = refund.json()["lines"][0]
    assert (
        refund_line["gross_refund_minor"],
        refund_line["discount_refund_minor"],
        refund_line["net_refund_minor"],
        refund_line["total_refund_minor"],
    ) == ("100000", "20000", "80000", "80000")

    async with sessions() as session:
        handlers = EventHandlerRegistry()
        register_finance_handlers(
            handlers,
            FinanceProjectionService(
                SqlAlchemyFinanceRepository(session), SqlAlchemyFinanceSourceReader(session)
            ),
        )
        register_analytics_handlers(
            handlers,
            AnalyticsProjectionService(
                SqlAlchemyAnalyticsRepository(session),
                SqlAlchemyAnalyticsSourceReader(session),
            ),
        )
        assert (
            await OutboxDispatcher(
                OutboxRepository(session), handlers, "stage24-refund"
            ).run_once()
            > 0
        )
        assert await session.scalar(select(func.count()).select_from(PaymentModel)) == 1
        assert (
            await session.scalar(
                select(func.count())
                .select_from(SalesOrderDiscountModel)
                .join(SalesOrderModel, SalesOrderModel.id == SalesOrderDiscountModel.order_id)
                .where(
                    SalesOrderDiscountModel.promo_code_snapshot == "LAST10",
                    SalesOrderModel.status == "PAID",
                )
            )
            == 1
        )
        paid_order = await session.scalar(
            select(SalesOrderModel).where(SalesOrderModel.status == "PAID")
        )
        assert paid_order is not None
        assert (
            paid_order.subtotal_minor,
            paid_order.discount_total_minor,
            paid_order.total_minor,
        ) == (100000, 20000, 80000)
        payment = await session.scalar(select(PaymentModel))
        assert payment is not None and payment.amount_minor == 80000
        assert paid_order.pricing_revision > 1
        assert paid_order.priced_at is not None
        assert await session.scalar(
            select(func.count()).select_from(InventoryTransactionModel)
        ) == 1

        fiscal = await session.scalar(
            select(FiscalSaleSnapshotModel).where(
                FiscalSaleSnapshotModel.order_id == paid_order.id
            )
        )
        assert fiscal is not None
        assert fiscal.discount_total_minor == 20000
        fiscal_lines = list(
            await session.scalars(
                select(FiscalSaleSnapshotLineModel).where(
                    FiscalSaleSnapshotLineModel.snapshot_id == fiscal.id
                )
            )
        )
        assert sum(line.gross_total_minor for line in fiscal_lines) == 100000
        assert sum(line.discount_minor for line in fiscal_lines) == 20000
        assert sum(line.total_minor for line in fiscal_lines) == payment.amount_minor
        assert await session.scalar(
            select(func.sum(RefundDiscountAllocationModel.discount_amount_minor))
        ) == 20000
        promotion_analytics = await session.scalar(
            select(AnalyticsPromotionsDailyModel).where(
                AnalyticsPromotionsDailyModel.promotion_id == UUID(promotion_id)
            )
        )
        assert promotion_analytics is not None
        assert promotion_analytics.refund_amount == 800

    assert sorted(getattr(response, "status_code", 500) for response in responses) == [201, 409]


@pytest.mark.anyio
async def test_three_partial_refunds_sum_exactly_to_discounted_payment(
    postgres_stage21_app,  # noqa: F811
) -> None:
    client, sessions, _, _ = postgres_stage21_app
    headers, _, location_id, warehouse_id = await _workspace(
        client, "stage24-partial@example.com", "Stage 24 partial"
    )
    shift = await _register_shift(client, headers, location_id, warehouse_id)
    variant_id = await _variant(client, headers, "Partial coffee", 170000)
    order = await _order(client, headers, shift["id"], variant_id)
    item_id = order["items"][0]["id"]
    quantity = await client.patch(
        f"/api/v1/sales/orders/{order['id']}/items/{item_id}",
        headers=headers,
        json={"quantity": 3},
    )
    assert quantity.status_code == 200, quantity.text
    discounted = await client.post(
        f"/api/v1/sales/orders/{order['id']}/discounts/custom",
        headers=headers,
        json={
            "client_discount_id": str(uuid4()),
            "type": "FIXED_AMOUNT",
            "amount_minor": 10000,
            "reason": "Exact partial refund test",
        },
    )
    assert discounted.status_code == 200, discounted.text
    assert (
        discounted.json()["subtotal_minor"],
        discounted.json()["discount_total_minor"],
        discounted.json()["total_minor"],
    ) == ("510000", "10000", "500000")
    payment = await client.post(
        f"/api/v1/payments/orders/{order['id']}/complete",
        headers=headers,
        json={
            "client_payment_id": str(uuid4()),
            "lines": [
                {
                    "method": "CASH",
                    "amount_minor": 500000,
                    "cash_received_minor": 500000,
                }
            ],
        },
    )
    assert payment.status_code == 201, payment.text

    expected = (166666, 166667, 166667)
    refunds = []
    for amount in expected:
        response = await client.post(
            "/api/v1/refunds",
            headers=headers,
            json={
                "client_refund_id": str(uuid4()),
                "payment_id": payment.json()["id"],
                "reason": "CUSTOMER_RETURN",
                "lines": [
                    {"order_item_id": item_id, "quantity": 1, "restock_quantity": 0}
                ],
                "payment_lines": [
                    {
                        "original_payment_line_id": payment.json()["lines"][0]["id"],
                        "amount_minor": amount,
                    }
                ],
            },
        )
        assert response.status_code == 201, response.text
        refunds.append(response.json()["lines"][0])

    assert sum(int(line["gross_refund_minor"]) for line in refunds) == 510000
    assert sum(int(line["discount_refund_minor"]) for line in refunds) == 10000
    assert sum(int(line["net_refund_minor"]) for line in refunds) == 500000
    async with sessions() as session:
        assert await session.scalar(
            select(func.sum(RefundDiscountAllocationModel.discount_amount_minor))
        ) == 10000
