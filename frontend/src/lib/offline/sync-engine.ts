import { readPendingOrders, readSyncState, writeSyncState } from "./db";
import { applySyncResults } from "./orders";
import { pingOfflineApi } from "./api";
import type { OfflineOrder, OfflineSession, SyncResult, SyncState } from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const activeSync = new Map<string, Promise<SyncState>>();
const requestedAgain = new Set<string>();

export function syncOfflineOrders(session: OfflineSession): Promise<SyncState> {
  requestedAgain.add(session.id);
  const running = activeSync.get(session.id);
  if (running) return running;
  const next = runQueued(session).finally(() => { activeSync.delete(session.id); });
  activeSync.set(session.id, next);
  return next;
}

async function runQueued(session: OfflineSession) {
  let state: SyncState;
  do {
    requestedAgain.delete(session.id);
    state = await runSync(session);
  } while (requestedAgain.has(session.id));
  return state;
}

async function runSync(session: OfflineSession): Promise<SyncState> {
  const previous = await readSyncState();
  await writeSyncState({ ...previous, status: "SYNCING", error: null });
  if (!(await pingOfflineApi())) return finish("OFFLINE", previous.last_sync_at, null);

  const orders = await readPendingOrders(session.id);
  if (!orders.length) return finish("ONLINE", new Date().toISOString(), null);

  try {
    let lastServerTime = new Date().toISOString();
    let hasConflict = false;
    for (let offset = 0; offset < orders.length; offset += 100) {
      const response = await fetch(`${API_URL}/api/v1/pos/offline/sync`, {
        method: "POST",
        credentials: "include",
        cache: "no-store",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ session_id: session.id, orders: orders.slice(offset, offset + 100).map(syncPayload) }),
      });
      if (!response.ok) throw new Error(await responseMessage(response));
      const body = await response.json() as { server_time: string; results: SyncResult[] };
      await applySyncResults(body.results);
      lastServerTime = body.server_time;
      hasConflict ||= body.results.some((result) => result.status === "CONFLICT");
    }
    return finish(hasConflict ? "ISSUE" : "ONLINE", lastServerTime, hasConflict ? "Paid order requires attention" : null);
  } catch (error) {
    return finish("ISSUE", previous.last_sync_at, error instanceof Error ? error.message : "Sync failed");
  }
}

function syncPayload(order: OfflineOrder) {
  return {
    client_order_id: order.client_order_id,
    revision: order.revision,
    base_server_version: order.server_version,
    catalog_snapshot_id: order.catalog_snapshot_id,
    offline_display_number: order.offline_display_number,
    created_at: order.created_at,
    updated_at: order.updated_at,
    order_type: order.order_type,
    status: order.status === "PAID_PENDING_SYNC" || order.status === "SYNCED_PAID"
      ? "PAID"
      : order.status === "CANCELLED_PENDING_SYNC" || order.status === "SYNCED_CANCELLED"
        ? "CANCELLED"
        : "OPEN",
    items: order.items.map((item) => ({
      client_item_id: item.client_item_id,
      variant_id: item.product_variant_id,
      selected_option_ids: item.selected_option_ids,
      quantity: item.quantity,
      note: item.note,
    })),
    manual_promotion_ids: order.manual_promotion_ids ?? [],
    payment: order.payment,
  };
}

async function finish(status: SyncState["status"], lastSyncAt: string | null, error: string | null) {
  const state: SyncState = { key: "state", status, last_sync_at: lastSyncAt, error };
  await writeSyncState(state);
  if (typeof BroadcastChannel !== "undefined") {
    const channel = new BroadcastChannel("beanly-pos-data");
    channel.postMessage("changed");
    channel.close();
  }
  return state;
}

async function responseMessage(response: Response) {
  const body = await response.json().catch(() => null) as { detail?: string | { message?: string }; message?: string } | null;
  return (typeof body?.detail === "string" ? body.detail : body?.detail?.message)
    ?? body?.message
    ?? `Sync failed (${response.status})`;
}
