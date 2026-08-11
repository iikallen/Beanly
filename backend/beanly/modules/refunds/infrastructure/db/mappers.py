from beanly.modules.refunds.domain.entities import Refund, RefundLine, RefundPaymentLine
from beanly.modules.refunds.domain.enums import RefundReason, RefundStatus
from beanly.modules.refunds.infrastructure.db.models import RefundModel


def to_refund(value: RefundModel) -> Refund:
    return Refund(
        value.id,
        value.organization_id,
        value.location_id,
        value.order_id,
        value.payment_id,
        value.client_refund_id,
        RefundStatus(value.status),
        RefundReason(value.reason),
        value.note,
        value.currency_code,
        value.total_amount_minor,
        value.inventory_transaction_id,
        value.cogs_reversal_amount,
        value.cogs_quality_status,
        value.created_by_user_id,
        value.created_at,
        value.completed_by_user_id,
        value.completed_at,
        value.failed_at,
        value.failure_code,
        tuple(
            RefundLine(
                line.id,
                line.refund_id,
                line.order_item_id,
                line.quantity,
                line.restock_quantity,
                line.unit_refund_minor,
                line.total_refund_minor,
                line.created_at,
            )
            for line in value.lines
        ),
        tuple(
            RefundPaymentLine(
                line.id,
                line.refund_id,
                line.original_payment_line_id,
                line.method,
                line.amount_minor,
                line.external_refund_confirmed,
                line.reference,
                line.created_at,
            )
            for line in value.payment_lines
        ),
    )
