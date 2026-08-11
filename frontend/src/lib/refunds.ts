import type { Payment, Refund, SalesOrder } from "./api.ts";

export function refundedItemQuantity(refunds: Refund[], orderItemId: string) {
  return refunds
    .filter((refund) => refund.status === "COMPLETED")
    .flatMap((refund) => refund.lines)
    .filter((line) => line.order_item_id === orderItemId)
    .reduce((total, line) => total + line.quantity, 0);
}

export function refundDraftTotal(order: SalesOrder, quantities: Record<string, number>) {
  return order.items.reduce(
    (total, item) => total + BigInt(item.unit_price_minor) * BigInt(quantities[item.id] ?? 0),
    BigInt(0),
  );
}

export function allocateRefundPayment(total: bigint, payment: Payment, refunds: Refund[]) {
  let remaining = total;
  return payment.lines.map((line) => {
    const refunded = refunds
      .filter((refund) => refund.status === "COMPLETED")
      .flatMap((refund) => refund.payment_lines)
      .filter((refundLine) => refundLine.original_payment_line_id === line.id)
      .reduce((sum, refundLine) => sum + BigInt(refundLine.amount_minor), BigInt(0));
    const available = BigInt(line.amount_minor) - refunded;
    const amount = remaining > available ? available : remaining;
    remaining -= amount;
    return { line, available, amount };
  });
}

export function refundAttempt(
  previous: { id: string; payload: string } | null,
  payload: string,
  createId: () => string,
) {
  return previous?.payload === payload ? previous : { id: createId(), payload };
}
