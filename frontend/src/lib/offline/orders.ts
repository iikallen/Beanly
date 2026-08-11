import type { ExternalPaymentAttempt, SalesOrderType } from "@/lib/api";

import { openPosDb, requestValue, stores, transactionDone } from "./db";
import { mergeExternalPaymentApproval, mergeSyncResult } from "./reconcile";
import type { OfflineOrder, OfflinePaymentLine, OfflineSession, SyncResult } from "./types";

const EDITABLE = new Set<OfflineOrder["status"]>(["OPEN", "SYNCED_OPEN"]);

export async function createLocalOrder(session: OfflineSession, orderType: SalesOrderType): Promise<OfflineOrder> {
  const db = await openPosDb();
  const transaction = db.transaction([stores.meta, stores.orders], "readwrite");
  const meta = transaction.objectStore(stores.meta);
  const counterKey = `order_number:${session.id}`;
  const counter = await requestValue(meta.get(counterKey)) as { key: string; value: number } | undefined;
  const number = (counter?.value ?? 0) + 1;
  const now = logicalNow(session);
  const id = crypto.randomUUID();
  const order: OfflineOrder = {
    id,
    client_order_id: id,
    server_order_id: null,
    server_version: null,
    revision: 1,
    last_synced_revision: 0,
    catalog_snapshot_id: session.catalog_snapshot_id,
    session_id: session.id,
    organization_id: session.organization_id,
    location_id: session.location_id,
    shift_id: session.shift_id,
    warehouse_id: session.warehouse_id,
    offline_display_number: number,
    number: `Offline #${number}`,
    order_type: orderType,
    status: "OPEN",
    currency_code: session.shell.currency_code,
    items: [],
    subtotal_minor: "0",
    total_minor: "0",
    payment: null,
    cancel_reason: null,
    created_at: now,
    updated_at: now,
    sync_error: null,
  };
  meta.put({ key: counterKey, value: number });
  transaction.objectStore(stores.orders).put(order);
  await transactionDone(transaction);
  db.close();
  changed();
  return order;
}

export async function updateLocalOrder(
  clientOrderId: string,
  mutate: (order: OfflineOrder) => void,
  clockOffsetMs = 0,
  updatedAt?: string,
): Promise<OfflineOrder> {
  const db = await openPosDb();
  const transaction = db.transaction(stores.orders, "readwrite");
  const store = transaction.objectStore(stores.orders);
  const order = await requestValue(store.get(clientOrderId)) as OfflineOrder | undefined;
  if (!order) throw new Error("Local order not found");
  if (!EDITABLE.has(order.status)) throw new Error("Paid, cancelled, or conflicted orders cannot be edited");
  mutate(order);
  order.revision += 1;
  if (order.status === "SYNCED_OPEN") order.status = "OPEN";
  order.updated_at = updatedAt ?? new Date(Date.now() + clockOffsetMs).toISOString();
  order.sync_error = null;
  recalculate(order);
  store.put(order);
  await transactionDone(transaction);
  db.close();
  changed();
  return order;
}

export async function cancelLocalOrder(clientOrderId: string, reason: string, clockOffsetMs = 0): Promise<OfflineOrder> {
  return updateLocalOrder(clientOrderId, (order) => {
    order.status = "CANCELLED_PENDING_SYNC";
    order.cancel_reason = reason;
  }, clockOffsetMs);
}

export async function payLocalOrder(
  clientOrderId: string,
  clientPaymentId: string,
  lines: OfflinePaymentLine[],
  clockOffsetMs = 0,
): Promise<OfflineOrder> {
  const completedAt = new Date(Date.now() + clockOffsetMs).toISOString();
  const order = await updateLocalOrder(clientOrderId, (value) => {
    value.payment = { client_payment_id: clientPaymentId, completed_at: completedAt, lines };
    value.status = "PAID_PENDING_SYNC";
  }, clockOffsetMs, completedAt);
  return order;
}

export async function applySyncResults(results: SyncResult[]): Promise<void> {
  if (!results.length) return;
  const db = await openPosDb();
  const transaction = db.transaction(stores.orders, "readwrite");
  const store = transaction.objectStore(stores.orders);
  for (const result of results) {
    const order = await requestValue(store.get(result.client_order_id)) as OfflineOrder | undefined;
    if (!order) continue;
    store.put(mergeSyncResult(order, result));
  }
  await transactionDone(transaction);
  db.close();
  changed();
}

export async function markExternalPaymentApproved(clientOrderId: string, attempt: ExternalPaymentAttempt): Promise<OfflineOrder> {
  const db = await openPosDb();
  const transaction = db.transaction(stores.orders, "readwrite");
  const store = transaction.objectStore(stores.orders);
  const order = await requestValue(store.get(clientOrderId)) as OfflineOrder | undefined;
  if (!order) throw new Error("Local order not found");
  const next = mergeExternalPaymentApproval(order, attempt);
  store.put(next);
  await transactionDone(transaction);
  db.close();
  changed();
  return next;
}

export async function cleanupSyncedOrders(): Promise<void> {
  const cutoff = Date.now() - 7 * 24 * 60 * 60 * 1000;
  const db = await openPosDb();
  const transaction = db.transaction(stores.orders, "readwrite");
  const store = transaction.objectStore(stores.orders);
  const orders = await requestValue(store.getAll()) as OfflineOrder[];
  for (const order of orders) {
    if ((order.status === "SYNCED_PAID" || order.status === "SYNCED_CANCELLED") && Date.parse(order.updated_at) < cutoff) {
      store.delete(order.client_order_id);
    }
  }
  await transactionDone(transaction);
  db.close();
}

function recalculate(order: OfflineOrder) {
  for (const item of order.items) item.line_total_minor = String(BigInt(item.unit_price_minor) * BigInt(item.quantity));
  order.subtotal_minor = String(order.items.reduce((sum, item) => sum + BigInt(item.line_total_minor), BigInt(0)));
  order.total_minor = order.subtotal_minor;
}

function logicalNow(session: OfflineSession) {
  return new Date(Date.now() + session.clock_offset_ms).toISOString();
}

function changed() {
  if (!("BroadcastChannel" in globalThis)) return;
  const channel = new BroadcastChannel("beanly-pos-data");
  channel.postMessage("changed");
  channel.close();
}
