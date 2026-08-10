from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from beanly.core.events import DomainEventSink, NullDomainEventSink
from beanly.core.money import MAX_BIGINT, MAX_NUMERIC_20_6_MINOR
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.payments.application.ports import (
    InventorySalePort,
    SalesSettlementPort,
    SaleStockLine,
)
from beanly.modules.payments.domain.entities import Payment, PaymentLine, ShiftPaymentSummary
from beanly.modules.payments.domain.enums import PaymentMethod
from beanly.modules.payments.domain.events import PaymentCompleted
from beanly.modules.payments.domain.exceptions import (
    InvalidPayment,
    OrderAlreadyPaid,
    OrderNotPayable,
    OrderShiftClosed,
    PaymentAmountMismatch,
    PaymentConflict,
    PaymentIdempotencyConflict,
    PaymentNotFound,
)
from beanly.modules.payments.domain.repositories import PaymentRepository
from beanly.modules.sales.domain.enums import OrderStatus


@dataclass(frozen=True, slots=True)
class PaymentLineInput:
    method: PaymentMethod
    amount_minor: int
    cash_received_minor: int | None = None
    reference: str | None = None


@dataclass(frozen=True, slots=True)
class CompletePaymentInput:
    client_payment_id: UUID
    lines: tuple[PaymentLineInput, ...]


class PaymentService:
    def __init__(
        self,
        repository: PaymentRepository,
        sales: SalesSettlementPort,
        inventory: InventorySalePort,
        sink: DomainEventSink | None = None,
    ) -> None:
        self.repository = repository
        self.sales = sales
        self.inventory = inventory
        self.sink = sink or NullDomainEventSink()

    async def complete(
        self,
        context: TenantContext,
        order_id: UUID,
        value: CompletePaymentInput,
    ) -> Payment:
        try:
            order = await self.sales.lock_order_for_payment(context, order_id)
            lines = _normalize_lines(value.lines)
            existing = await self.repository.get_by_client_id(
                context.organization_id, value.client_payment_id
            )
            if existing is not None:
                return _idempotent(existing, order_id, lines)
            if order.status == OrderStatus.PAID:
                raise OrderAlreadyPaid("Order is already paid")
            if order.status != OrderStatus.OPEN:
                raise OrderNotPayable("Only OPEN orders can be paid")
            if not order.shift_is_open:
                raise OrderShiftClosed("Order shift is not OPEN")
            if not order.has_items:
                raise OrderNotPayable("Order must contain at least one item")
            amount_minor = sum(line.amount_minor for line in lines)
            if amount_minor > MAX_NUMERIC_20_6_MINOR:
                raise InvalidPayment("Payment total exceeds the finance ledger limit")
            if amount_minor != order.total_minor:
                raise PaymentAmountMismatch("Payment lines must equal the order total")
            staged_sale = await self.inventory.stage_sale(
                context,
                order_id=order.id,
                order_number=order.order_number,
                warehouse_id=order.warehouse_id,
                lines=tuple(
                    SaleStockLine(
                        component.inventory_item_id,
                        component.base_unit,
                        component.quantity,
                    )
                    for component in order.sale_components
                ),
            )
            now = datetime.now(UTC)
            payment_id = uuid4()
            payment = Payment(
                payment_id,
                order.organization_id,
                order.location_id,
                order.id,
                order.shift_id,
                value.client_payment_id,
                order.currency_code,
                amount_minor,
                context.user_id,
                now,
                now,
                now,
                tuple(
                    PaymentLine(
                        uuid4(),
                        payment_id,
                        line.method,
                        line.amount_minor,
                        line.cash_received_minor,
                        line.change_minor,
                        line.reference,
                        sort_order,
                        now,
                    )
                    for sort_order, line in enumerate(lines)
                ),
            )
            saved = await self.repository.add(payment)
            await self.sales.mark_order_paid(
                order.id,
                context.user_id,
                now,
                staged_sale.inventory_transaction_id,
                staged_sale.cogs_amount,
                staged_sale.cogs_status,
            )
            await self.sink.stage_many(
                (
                    *staged_sale.events,
                    PaymentCompleted(
                        saved.id,
                        saved.order_id,
                        saved.organization_id,
                        saved.location_id,
                        saved.amount_minor,
                    ),
                )
            )
            await self.repository.commit()
        except PaymentConflict as exc:
            await self.repository.rollback()
            return await self._recover_conflict(
                context.organization_id,
                order_id,
                value.client_payment_id,
                value.lines,
                exc,
            )
        except Exception:
            await self.repository.rollback()
            raise
        return saved

    async def get(
        self, context: TenantContext, payment_id: UUID
    ) -> Payment:
        value = await self.repository.get(context.organization_id, payment_id)
        return await self._accessible(context, value)

    async def get_by_order(
        self, context: TenantContext, order_id: UUID
    ) -> Payment:
        value = await self.repository.get_by_order(context.organization_id, order_id)
        return await self._accessible(context, value)

    async def list(
        self,
        context: TenantContext,
        *,
        location_id: UUID | None,
        shift_id: UUID | None,
        date_from: datetime | None,
        date_to: datetime | None,
        method: PaymentMethod | None,
    ) -> list[Payment]:
        if any(
            value is not None and value.utcoffset() is None
            for value in (date_from, date_to)
        ):
            raise ValueError("Payment date filters must include a timezone")
        if date_from is not None and date_to is not None and date_from > date_to:
            raise ValueError("date_from cannot be after date_to")
        allowed = await self.sales.accessible_location_ids(context)
        if location_id is not None:
            if location_id not in allowed:
                raise PaymentNotFound("Location not found")
            location_ids = (location_id,)
        else:
            location_ids = allowed
        return await self.repository.list(
            context.organization_id,
            location_ids,
            shift_id=shift_id,
            date_from=date_from,
            date_to=date_to,
            method=method,
        )

    async def shift_summary(
        self, context: TenantContext, shift_id: UUID
    ) -> ShiftPaymentSummary:
        await self.sales.ensure_shift_access(context, shift_id)
        return await self.repository.shift_summary(context.organization_id, shift_id)

    async def _recover_conflict(
        self,
        organization_id: UUID,
        order_id: UUID,
        client_payment_id: UUID,
        requested: tuple[PaymentLineInput, ...],
        original: PaymentConflict,
    ) -> Payment:
        lines = _normalize_lines(requested)
        existing = await self.repository.get_by_client_id(
            organization_id, client_payment_id
        )
        if existing is not None:
            return _idempotent(existing, order_id, lines)
        if await self.repository.get_by_order(organization_id, order_id) is not None:
            raise OrderAlreadyPaid("Order is already paid") from original
        raise original

    async def _accessible(
        self, context: TenantContext, value: Payment | None
    ) -> Payment:
        if value is None:
            raise PaymentNotFound("Payment not found")
        await self.sales.ensure_location_access(context, value.location_id)
        return value

@dataclass(frozen=True, slots=True)
class _NormalizedLine:
    method: PaymentMethod
    amount_minor: int
    cash_received_minor: int | None
    change_minor: int
    reference: str | None


def _normalize_lines(values: tuple[PaymentLineInput, ...]) -> tuple[_NormalizedLine, ...]:
    if len(values) > 100:
        raise InvalidPayment("A payment cannot contain more than 100 lines")
    normalized: list[_NormalizedLine] = []
    for value in values:
        if not 0 <= value.amount_minor <= MAX_NUMERIC_20_6_MINOR:
            raise InvalidPayment("Payment line amount exceeds the finance ledger limit")
        reference = _reference(value.reference)
        if value.method == PaymentMethod.CASH:
            if value.cash_received_minor is None:
                raise InvalidPayment("Cash received is required for CASH")
            if not 0 <= value.cash_received_minor <= MAX_BIGINT:
                raise InvalidPayment("Cash received must fit a non-negative BIGINT")
            if value.cash_received_minor < value.amount_minor:
                raise InvalidPayment("Cash received cannot be below the applied amount")
            change_minor = value.cash_received_minor - value.amount_minor
        else:
            if value.cash_received_minor is not None:
                raise InvalidPayment("Cash received is only valid for CASH")
            change_minor = 0
        normalized.append(
            _NormalizedLine(
                value.method,
                value.amount_minor,
                value.cash_received_minor,
                change_minor,
                reference,
            )
        )
    return tuple(normalized)


def _reference(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if len(normalized) > 200:
        raise InvalidPayment("Payment reference cannot exceed 200 characters")
    return normalized or None


def _idempotent(
    existing: Payment,
    order_id: UUID,
    requested: tuple[_NormalizedLine, ...],
) -> Payment:
    persisted = tuple(
        _NormalizedLine(
            line.method,
            line.amount_minor,
            line.cash_received_minor,
            line.change_minor,
            line.reference,
        )
        for line in existing.lines
    )
    if existing.order_id != order_id or persisted != requested:
        raise PaymentIdempotencyConflict(
            "client_payment_id was already used with a different request"
        )
    return existing
