from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from beanly.core.money import MAX_NUMERIC_20_6
from beanly.modules.finance.application.source_ports import FinanceSourceReader
from beanly.modules.finance.domain.entities import CashEntry, FinanceEntry
from beanly.modules.finance.domain.enums import CashFlowActivity, FinanceEntryType
from beanly.modules.finance.domain.exceptions import FinanceNotFound
from beanly.modules.finance.domain.repositories import FinanceRepository


class FinanceProjectionService:
    """Idempotent projections; transaction ownership stays with the dispatcher."""

    def __init__(self, repository: FinanceRepository, sources: FinanceSourceReader) -> None:
        self.repository = repository
        self.sources = sources

    async def apply_refund_completed(
        self, event_id: UUID, organization_id: UUID, refund_id: UUID
    ) -> None:
        refund = await self.sources.refund(organization_id, refund_id)
        now = datetime.now(UTC)
        await self.repository.add_finance_entry(
            FinanceEntry(
                uuid4(),
                organization_id,
                refund.location_id,
                FinanceEntryType.REVENUE,
                _amount(-Decimal(refund.amount_minor) / 100),
                refund.currency_code,
                refund.completed_at,
                "Refund revenue reversal",
                None,
                "REFUND",
                refund.refund_id,
                event_id,
                "REVENUE_REFUND",
                None,
                None,
                now,
            )
        )
        if refund.cogs_reversal_amount:
            await self.repository.add_finance_entry(
                FinanceEntry(
                    uuid4(),
                    organization_id,
                    refund.location_id,
                    FinanceEntryType.COGS,
                    _amount(refund.cogs_reversal_amount),
                    refund.currency_code,
                    refund.completed_at,
                    "Refund COGS reversal",
                    None,
                    "REFUND",
                    refund.refund_id,
                    event_id,
                    "COGS_REFUND_REVERSAL",
                    None,
                    refund.cogs_quality_status or "INCOMPLETE",
                    now,
                )
            )
        for line in refund.payment_lines:
            account = await self.repository.system_account(
                organization_id, refund.location_id, line.method, refund.currency_code
            )
            await self.repository.add_cash_entry(
                CashEntry(
                    uuid4(),
                    organization_id,
                    account.location_id,
                    account.id,
                    -line.amount_minor,
                    refund.currency_code,
                    CashFlowActivity.OPERATING,
                    refund.completed_at,
                    f"Refund {line.method.lower()}",
                    "REFUND",
                    refund.refund_id,
                    event_id,
                    f"REFUND_PAYMENT_LINE:{line.id}",
                    None,
                    now,
                )
            )

    async def apply_payment_completed(
        self,
        event_id: UUID,
        organization_id: UUID,
        payment_id: UUID,
        order_id: UUID,
    ) -> None:
        payment = await self.sources.payment(organization_id, payment_id)
        sale = await self.sources.sale(organization_id, order_id)
        if (
            payment.order_id != order_id
            or payment.organization_id != sale.organization_id
            or payment.location_id != sale.location_id
            or payment.currency_code != sale.currency_code
        ):
            raise ValueError("Payment and paid sale snapshots do not match")
        now = datetime.now(UTC)
        await self.repository.add_finance_entry(
            FinanceEntry(
                uuid4(),
                organization_id,
                payment.location_id,
                FinanceEntryType.REVENUE,
                _amount(Decimal(sale.gross_amount_minor) / 100),
                payment.currency_code,
                payment.completed_at,
                "Gross sales revenue",
                None,
                "PAYMENT",
                payment.payment_id,
                event_id,
                "REVENUE_GROSS",
                None,
                None,
                now,
            )
        )
        if sale.discount_amount_minor:
            await self.repository.add_finance_entry(
                FinanceEntry(
                    uuid4(),
                    organization_id,
                    payment.location_id,
                    FinanceEntryType.REVENUE,
                    _amount(-Decimal(sale.discount_amount_minor) / 100),
                    payment.currency_code,
                    payment.completed_at,
                    "Sales discount",
                    None,
                    "PAYMENT",
                    payment.payment_id,
                    event_id,
                    "SALES_DISCOUNT",
                    None,
                    None,
                    now,
                )
            )
        await self.repository.add_finance_entry(
            FinanceEntry(
                uuid4(),
                organization_id,
                sale.location_id,
                FinanceEntryType.COGS,
                _amount(-sale.cogs_amount),
                sale.currency_code,
                sale.paid_at,
                "Cost of goods sold",
                None,
                "SALE",
                sale.order_id,
                event_id,
                "COGS",
                None,
                sale.cogs_status,
                now,
            )
        )
        for line in payment.lines:
            account = await self.repository.system_account(
                organization_id,
                payment.location_id,
                line.method,
                payment.currency_code,
            )
            await self.repository.add_cash_entry(
                CashEntry(
                    uuid4(),
                    organization_id,
                    account.location_id,
                    account.id,
                    line.amount_minor,
                    payment.currency_code,
                    CashFlowActivity.OPERATING,
                    payment.completed_at,
                    f"Payment {line.method.lower()}",
                    "PAYMENT",
                    payment.payment_id,
                    event_id,
                    f"PAYMENT_LINE:{line.id}",
                    None,
                    now,
                )
            )

    async def apply_writeoff_posted(
        self, event_id: UUID, organization_id: UUID, writeoff_id: UUID
    ) -> None:
        value = await self.sources.writeoff(organization_id, writeoff_id)
        await self.repository.add_finance_entry(
            FinanceEntry(
                uuid4(),
                organization_id,
                value.location_id,
                FinanceEntryType.INVENTORY_LOSS,
                _amount(-abs(value.total_cost_amount)),
                await self.repository.currency(organization_id),
                value.posted_at,
                "Inventory write-off",
                None,
                "INVENTORY_WRITE_OFF",
                value.writeoff_id,
                event_id,
                "INVENTORY_LOSS",
                None,
                None,
                datetime.now(UTC),
            )
        )

    async def apply_writeoff_reversed(
        self, event_id: UUID, organization_id: UUID, writeoff_id: UUID
    ) -> None:
        original = await self.repository.find_finance_entry(
            organization_id,
            "INVENTORY_WRITE_OFF",
            writeoff_id,
            "INVENTORY_LOSS",
        )
        if original is None:
            # Events are ordered, but backfill/retry may encounter reversal first.
            await self.apply_writeoff_posted(event_id, organization_id, writeoff_id)
            original = await self.repository.find_finance_entry(
                organization_id,
                "INVENTORY_WRITE_OFF",
                writeoff_id,
                "INVENTORY_LOSS",
            )
        if original is None:
            raise FinanceNotFound("Write-off finance entry not found")
        source = await self.sources.writeoff(organization_id, writeoff_id)
        await self.repository.add_finance_entry(
            FinanceEntry(
                uuid4(),
                organization_id,
                original.location_id,
                original.entry_type,
                -original.amount,
                original.currency_code,
                source.reversed_at or datetime.now(UTC),
                "Inventory write-off reversal",
                None,
                "INVENTORY_WRITE_OFF_REVERSAL",
                writeoff_id,
                event_id,
                "INVENTORY_LOSS_REVERSAL",
                original.id,
                None,
                datetime.now(UTC),
            )
        )

    async def apply_inventory_count_posted(
        self, event_id: UUID, organization_id: UUID, inventory_count_id: UUID
    ) -> None:
        value = await self.sources.count(organization_id, inventory_count_id)
        currency = await self.repository.currency(organization_id)
        now = datetime.now(UTC)
        if value.loss_amount:
            await self.repository.add_finance_entry(
                FinanceEntry(
                    uuid4(),
                    organization_id,
                    value.location_id,
                    FinanceEntryType.INVENTORY_LOSS,
                    _amount(-value.loss_amount),
                    currency,
                    value.posted_at,
                    "Inventory count loss",
                    None,
                    "INVENTORY_COUNT",
                    value.inventory_count_id,
                    event_id,
                    "INVENTORY_LOSS",
                    None,
                    None,
                    now,
                )
            )
        if value.gain_amount:
            await self.repository.add_finance_entry(
                FinanceEntry(
                    uuid4(),
                    organization_id,
                    value.location_id,
                    FinanceEntryType.INVENTORY_GAIN,
                    _amount(value.gain_amount),
                    currency,
                    value.posted_at,
                    "Inventory count gain",
                    None,
                    "INVENTORY_COUNT",
                    value.inventory_count_id,
                    event_id,
                    "INVENTORY_GAIN",
                    None,
                    None,
                    now,
                )
            )


def _amount(value: Decimal) -> Decimal:
    if not value.is_finite() or abs(value) > MAX_NUMERIC_20_6:
        raise ValueError("Finance amount exceeds NUMERIC(20,6)")
    return value
