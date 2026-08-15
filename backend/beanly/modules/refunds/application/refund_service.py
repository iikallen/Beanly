from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from beanly.core.events.outbox.writer import DomainEventSink
from beanly.core.observability import metrics, traced
from beanly.core.security.audit import SecurityAuditRecorder
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.refunds.application.dto import RefundInput, RefundPreview
from beanly.modules.refunds.application.ports import (
    RefundAccessPort,
    RefundInventoryPort,
    RefundSourcePort,
    RefundStorePort,
)
from beanly.modules.refunds.domain.entities import Refund, RefundLine, RefundPaymentLine
from beanly.modules.refunds.domain.enums import RefundStatus
from beanly.modules.refunds.domain.events import RefundCompleted
from beanly.modules.refunds.domain.exceptions import (
    InvalidRefund,
    RefundConflict,
    RefundIdempotencyConflict,
    RefundNotFound,
)


class RefundService:
    def __init__(
        self,
        store: RefundStorePort,
        source: RefundSourcePort,
        inventory: RefundInventoryPort,
        access: RefundAccessPort,
        sink: DomainEventSink,
        audit: SecurityAuditRecorder | None = None,
    ) -> None:
        self.store, self.source, self.inventory, self.access = store, source, inventory, access
        self.sink, self.audit = sink, audit

    async def preview(self, context: TenantContext, value: RefundInput) -> RefundPreview:
        _bounded(value)
        location_id = await self.source.payment_location(context.organization_id, value.payment_id)
        if location_id is None:
            raise RefundNotFound("Payment not found")
        await self.access.ensure_location(context, location_id)
        plan = await self.source.plan(
            context.organization_id,
            value,
            lock=False,
            require_external_confirmation=False,
        )
        await self.access.ensure_location(context, plan.location_id)
        return plan.preview

    async def complete(
        self, context: TenantContext, value: RefundInput, *, commit: bool = True
    ) -> Refund:
        if value.client_refund_id is None:
            raise InvalidRefund("client_refund_id is required")
        _bounded(value)
        try:
            with traced("refund.complete", organization_id=str(context.organization_id)):
                existing = await self.store.get_by_client_id(
                    context.organization_id, value.client_refund_id
                )
                if existing is not None:
                    await self.access.ensure_location(context, existing.location_id)
                    _assert_idempotent(existing, value)
                    return existing
                location_id = await self.source.lock_payment(
                    context.organization_id, value.payment_id
                )
                await self.access.ensure_location(context, location_id)
                existing = await self.store.get_by_client_id(
                    context.organization_id, value.client_refund_id
                )
                if existing is not None:
                    await self.access.ensure_location(context, existing.location_id)
                    _assert_idempotent(existing, value)
                    await self.store.rollback()
                    return existing
                plan = await self.source.plan(
                    context.organization_id,
                    value,
                    lock=False,
                    require_external_confirmation=True,
                )
                await self.access.ensure_location(context, plan.location_id)
                now, refund_id = datetime.now(UTC), uuid4()
                refund = Refund(
                    refund_id,
                    context.organization_id,
                    plan.location_id,
                    plan.preview.order_id,
                    plan.preview.payment_id,
                    value.client_refund_id,
                    RefundStatus.PENDING,
                    value.reason,
                    _note(value.note),
                    plan.currency_code,
                    plan.preview.total_amount_minor,
                    None,
                    Decimal(0),
                    None,
                    context.user_id,
                    now,
                    None,
                    None,
                    None,
                    None,
                    tuple(
                        RefundLine(
                            uuid4(),
                            refund_id,
                            line.order_item_id,
                            line.quantity,
                            line.restock_quantity,
                            line.unit_refund_minor,
                            line.total_refund_minor,
                            now,
                            line.unit_refund_minor * line.quantity,
                            line.unit_refund_minor * line.quantity - line.total_refund_minor,
                            line.total_refund_minor,
                        )
                        for line in plan.preview.lines
                    ),
                    tuple(
                        RefundPaymentLine(
                            uuid4(),
                            refund_id,
                            line.original_payment_line_id,
                            line.method,
                            line.amount_minor,
                            next(
                                item.external_refund_confirmed
                                for item in value.payment_lines
                                if item.original_payment_line_id == line.original_payment_line_id
                            ),
                            next(
                                _reference(item.reference)
                                for item in value.payment_lines
                                if item.original_payment_line_id == line.original_payment_line_id
                            ),
                            now,
                        )
                        for line in plan.preview.payment_lines
                    ),
                    plan.preview.fulfillment_fee_minor,
                )
                await self.store.add(refund)
                transaction_id, cogs, inventory_events = await self.inventory.stage_return(
                    context, refund.id, plan.warehouse_id, plan.stock_lines
                )
                completed = replace(
                    refund,
                    status=RefundStatus.COMPLETED,
                    inventory_transaction_id=transaction_id,
                    cogs_reversal_amount=cogs,
                    cogs_quality_status=plan.cogs_quality_status if transaction_id else None,
                    completed_by_user_id=context.user_id,
                    completed_at=now,
                )
                await self.store.add(completed)
                await self.sink.stage_many(
                    (
                        *inventory_events,
                        RefundCompleted(
                            completed.id,
                            completed.organization_id,
                            completed.location_id,
                            completed.order_id,
                            completed.payment_id,
                            completed.total_amount_minor,
                            completed.cogs_reversal_amount,
                            completed.cogs_quality_status,
                            now,
                        ),
                    ),
                    occurred_at=now,
                )
                if self.audit:
                    await self.audit.record(
                        action="REFUND_COMPLETED",
                        resource_type="refund",
                        organization_id=context.organization_id,
                        actor_user_id=context.user_id,
                        resource_id=completed.id,
                        metadata={
                            "refund_id": str(completed.id),
                            "order_id": str(completed.order_id),
                            "amount_minor": completed.total_amount_minor,
                            "reason": completed.reason.value,
                        },
                    )
                if commit:
                    await self.store.commit()
                metrics.refund_completed.add(1)
                metrics.refund_amount.add(completed.total_amount_minor)
                return completed
        except RefundConflict:
            await self.store.rollback()
            existing = await self.store.get_by_client_id(
                context.organization_id, value.client_refund_id
            )
            if existing is None:
                raise
            await self.access.ensure_location(context, existing.location_id)
            _assert_idempotent(existing, value)
            return existing
        except Exception as exc:
            await self.store.rollback()
            metrics.refund_failed.add(1, {"refund.code": getattr(exc, "code", "UNKNOWN")})
            if self.audit:
                await self.audit.record(
                    action="REFUND_FAILED",
                    resource_type="refund",
                    organization_id=context.organization_id,
                    actor_user_id=context.user_id,
                    resource_id=value.client_refund_id,
                    metadata={
                        "payment_id": str(value.payment_id),
                        "reason": value.reason.value,
                        "failure_code": getattr(exc, "code", "REFUND_ERROR"),
                    },
                )
                if commit:
                    await self.store.commit()
            raise

    async def get(self, context: TenantContext, refund_id: UUID) -> Refund:
        value = await self.store.get(context.organization_id, refund_id)
        if value is None:
            raise RefundNotFound("Refund not found")
        await self.access.ensure_location(context, value.location_id)
        return value

    async def list_refunds(self, context: TenantContext, **filters) -> list[Refund]:
        location_ids = await self.access.location_ids(context)
        selected = filters.get("location_id")
        if selected is not None and selected not in location_ids:
            raise RefundNotFound("Location not found")
        return await self.store.list(context.organization_id, location_ids=location_ids, **filters)

    async def by_payment(self, context: TenantContext, payment_id: UUID) -> list[Refund]:
        values = await self.store.list(
            context.organization_id,
            location_ids=await self.access.location_ids(context),
            location_id=None,
            order_id=None,
            payment_id=payment_id,
            status=None,
            date_from=None,
            date_to=None,
        )
        return values

    async def fiscal_status(
        self, context: TenantContext, refund_id: UUID
    ) -> tuple[str, str | None, str | None]:
        return await self.store.fiscal_status(context.organization_id, refund_id)


def _assert_idempotent(existing: Refund, value: RefundInput) -> None:
    lines = tuple(
        sorted(
            (line.order_item_id, line.quantity, line.restock_quantity) for line in existing.lines
        )
    )
    requested = tuple(
        sorted((line.order_item_id, line.quantity, line.restock_quantity) for line in value.lines)
    )
    payments = tuple(
        sorted(
            (
                line.original_payment_line_id,
                line.amount_minor,
                line.external_refund_confirmed,
                _reference(line.reference),
            )
            for line in existing.payment_lines
        )
    )
    requested_payments = tuple(
        sorted(
            (
                line.original_payment_line_id,
                line.amount_minor,
                line.external_refund_confirmed,
                _reference(line.reference),
            )
            for line in value.payment_lines
        )
    )
    if (
        existing.payment_id != value.payment_id
        or existing.reason != value.reason
        or existing.note != _note(value.note)
        or existing.fulfillment_fee_minor != value.fulfillment_fee_minor
        or lines != requested
        or payments != requested_payments
    ):
        raise RefundIdempotencyConflict("client_refund_id was already used with another payload")


def _note(value: str | None) -> str | None:
    return value.strip() if value and value.strip() else None


def _reference(value: str | None) -> str | None:
    return value.strip() if value and value.strip() else None


def _bounded(value: RefundInput) -> None:
    if not 1 <= len(value.lines) <= 100 or not 1 <= len(value.payment_lines) <= 100:
        raise InvalidRefund("Refund supports between 1 and 100 lines")
    if value.fulfillment_fee_minor < 0:
        raise InvalidRefund("Fulfillment fee refund cannot be negative")
