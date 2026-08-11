import type { ExternalPaymentAttempt } from "@/lib/api";

import type { OfflineOrder, SyncResult } from "./types";

export function mergeSyncResult(order: OfflineOrder, result: SyncResult): OfflineOrder {
  if (result.status === "CONFLICT") {
    if (result.revision !== order.revision) return order;
    return { ...order, status: "CONFLICT", sync_error: result.code ?? "ORDER_CHANGED_ON_SERVER" };
  }

  const next: OfflineOrder = {
    ...order,
    server_order_id: result.server_order_id ?? order.server_order_id,
    server_version: result.server_version ?? order.server_version,
    number: result.server_order_number ? String(result.server_order_number) : order.number,
    last_synced_revision: Math.max(order.last_synced_revision, result.revision),
    sync_error: null,
  };
  if (order.revision === result.revision) {
    if (order.status === "PAID_PENDING_SYNC") next.status = "SYNCED_PAID";
    else if (order.status === "CANCELLED_PENDING_SYNC") next.status = "SYNCED_CANCELLED";
    else next.status = "SYNCED_OPEN";
  }
  return next;
}

export function mergeExternalPaymentApproval(order: OfflineOrder, attempt: ExternalPaymentAttempt): OfflineOrder {
  if (attempt.status !== "APPROVED" || !attempt.payment_id) throw new Error("Terminal payment is not approved");
  if (order.server_order_id !== attempt.order_id) throw new Error("Terminal payment belongs to another order");
  if (order.total_minor !== attempt.amount_minor || order.currency_code !== attempt.currency_code) throw new Error("Terminal payment amount does not match order");
  return {
    ...order,
    status: "SYNCED_PAID",
    last_synced_revision: order.revision,
    payment: {
      client_payment_id: attempt.client_attempt_id,
      completed_at: attempt.approved_at ?? attempt.created_at,
      lines: [{
        method: "CARD",
        amount_minor: attempt.amount_minor,
        reference: attempt.provider_reference ?? attempt.provider_code,
        external_settlement_confirmed: true,
      }],
    },
    updated_at: attempt.approved_at ?? attempt.created_at,
    sync_error: null,
  };
}
