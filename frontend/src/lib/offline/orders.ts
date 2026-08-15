import type { ExternalPaymentAttempt, SalesOrder, SalesOrderType } from "@/lib/api";

import { openPosDb, requestValue, stores, transactionDone } from "./db";
import { mergeExternalPaymentApproval, mergeSyncResult } from "./reconcile";
import { priceOfflineOrder } from "./pricing";
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
    location_timezone: session.shell.location_timezone ?? "UTC",
    shift_id: session.shift_id,
    warehouse_id: session.warehouse_id,
    offline_display_number: number,
    number: `Offline #${number}`,
    order_type: orderType,
    status: "OPEN",
    currency_code: session.shell.currency_code,
    items: [],
    subtotal_minor: "0",
    discount_total_minor: "0",
    total_minor: "0",
    discounts: [],
    manual_promotion_ids: [],
    pricing_promotions: session.catalog_snapshot.public_payload.promotions ?? [],
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

export async function importServerOrder(
  session: OfflineSession,
  source: SalesOrder,
): Promise<OfflineOrder> {
  if (source.status !== "OPEN") throw new Error("Only open orders can be imported into POS");
  if (source.order_source === "POS") throw new Error("Only online orders can be imported into POS");
  if (source.organization_id !== session.organization_id || source.shift_id !== session.shift_id || source.location_id !== session.location_id) {
    throw new Error("Online order belongs to another active shift or location");
  }
  const products = session.catalog_snapshot.public_payload.categories.flatMap((category) =>
    category.products.map((product) => ({ category_id: category.id, product })),
  );
  const order: OfflineOrder = {
    id: source.client_order_id,
    client_order_id: source.client_order_id,
    server_order_id: source.id,
    server_version: source.version,
    revision: source.version,
    last_synced_revision: source.version,
    catalog_snapshot_id: session.catalog_snapshot_id,
    session_id: session.id,
    organization_id: source.organization_id,
    location_id: source.location_id,
    location_timezone: session.shell.location_timezone ?? "UTC",
    shift_id: source.shift_id,
    warehouse_id: source.warehouse_id,
    offline_display_number: Number(source.number),
    number: `Order #${source.number}`,
    order_type: source.order_type,
    status: "SYNCED_OPEN",
    currency_code: source.currency_code,
    items: source.items.map((item) => {
      const product = products.find((value) => value.product.id === item.product_id);
      if (!product) throw new Error(`${item.product_name} is not in the current POS catalog`);
      return {
        id: item.client_item_id,
        client_item_id: item.client_item_id,
        product_id: item.product_id,
        category_id: product.category_id,
        product_variant_id: item.product_variant_id,
        product_name: item.product_name,
        variant_name: item.variant_name,
        selected_option_ids: item.modifiers.map((value) => value.modifier_option_id),
        quantity: item.quantity,
        base_price_minor: item.base_price_minor,
        modifier_price_minor: item.modifier_price_minor,
        unit_price_minor: item.unit_price_minor,
        line_total_minor: item.line_total_minor,
        discount_amount_minor: item.discount_amount_minor,
        net_line_total_minor: item.net_line_total_minor,
        note: item.note,
        modifiers: item.modifiers.map((value) => ({
          modifier_group_id: value.modifier_group_id,
          modifier_group_name: value.modifier_group_name,
          modifier_option_id: value.modifier_option_id,
          modifier_option_name: value.modifier_option_name,
          price_delta_minor: value.price_delta_minor,
        })),
      };
    }),
    subtotal_minor: source.subtotal_minor,
    discount_total_minor: source.discount_total_minor,
    total_minor: source.total_minor,
    discounts: source.discounts,
    manual_promotion_ids: [],
    pricing_promotions: [],
    payment: null,
    cancel_reason: null,
    created_at: source.created_at,
    updated_at: source.updated_at,
    sync_error: null,
  };
  const db = await openPosDb();
  const transaction = db.transaction(stores.orders, "readwrite");
  const store = transaction.objectStore(stores.orders);
  const existing = await requestValue(store.get(order.client_order_id)) as OfflineOrder | undefined;
  if (existing && existing.server_order_id !== source.id) {
    transaction.abort();
    db.close();
    throw new Error("A different local order already uses this client order ID");
  }
  if (!existing) store.put(order);
  await transactionDone(transaction);
  db.close();
  if (!existing) changed();
  return existing ?? order;
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

export async function applyServerPricing(clientOrderId: string, source: SalesOrder): Promise<OfflineOrder> {
  const db = await openPosDb();
  const transaction = db.transaction(stores.orders, "readwrite");
  const store = transaction.objectStore(stores.orders);
  const order = await requestValue(store.get(clientOrderId)) as OfflineOrder | undefined;
  if (!order) throw new Error("Local order not found");
  order.server_version = source.version;
  order.subtotal_minor = source.subtotal_minor;
  order.discount_total_minor = source.discount_total_minor;
  order.total_minor = source.total_minor;
  order.discounts = source.discounts;
  order.manual_promotion_ids = source.discounts.filter((discount) => discount.source === "MANUAL" && discount.promotion_id).map((discount) => discount.promotion_id!);
  for (const item of order.items) {
    const priced = source.items.find((candidate) => candidate.client_item_id === item.client_item_id);
    if (!priced) continue;
    item.discount_amount_minor = priced.discount_amount_minor;
    item.net_line_total_minor = priced.net_line_total_minor;
  }
  store.put(order);
  await transactionDone(transaction);
  db.close();
  changed();
  return order;
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
  for (const item of order.items) {
    item.line_total_minor = String(BigInt(item.unit_price_minor) * BigInt(item.quantity));
    item.discount_amount_minor = "0";
    item.net_line_total_minor = item.line_total_minor;
  }
  order.subtotal_minor = String(order.items.reduce((sum, item) => sum + BigInt(item.line_total_minor), BigInt(0)));
  order.discount_total_minor = "0";
  order.total_minor = order.subtotal_minor;
  order.discounts = [];
  Object.assign(order, priceOfflineOrder(order, order.pricing_promotions ?? [], order.manual_promotion_ids ?? [], order.location_timezone ?? "UTC"));
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
