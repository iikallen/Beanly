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
