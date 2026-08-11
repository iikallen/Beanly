import type { OfflineOrder, OfflineSession, PublicCatalogSnapshot, SyncState } from "./types";

const DB_NAME = "beanly-pos-v1";
const DB_VERSION = 1;

export const stores = {
  meta: "meta",
  session: "offline_session",
  catalogs: "catalog_snapshots",
  orders: "orders",
  sync: "sync_state",
} as const;

export function openPosDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(stores.meta)) db.createObjectStore(stores.meta, { keyPath: "key" });
      if (!db.objectStoreNames.contains(stores.session)) db.createObjectStore(stores.session, { keyPath: "id" });
      if (!db.objectStoreNames.contains(stores.catalogs)) db.createObjectStore(stores.catalogs, { keyPath: "id" });
      if (!db.objectStoreNames.contains(stores.orders)) {
        const orders = db.createObjectStore(stores.orders, { keyPath: "client_order_id" });
        orders.createIndex("session_id", "session_id");
        orders.createIndex("updated_at", "updated_at");
      }
      if (!db.objectStoreNames.contains(stores.sync)) db.createObjectStore(stores.sync, { keyPath: "key" });
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("IndexedDB unavailable"));
    request.onblocked = () => reject(new Error("Close other Beanly tabs to update offline storage"));
  });
}

export function requestValue<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("IndexedDB request failed"));
  });
}

export function transactionDone(transaction: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error ?? new Error("IndexedDB transaction failed"));
    transaction.onabort = () => reject(transaction.error ?? new Error("IndexedDB transaction aborted"));
  });
}

export async function readCurrentSession(): Promise<OfflineSession | null> {
  const db = await openPosDb();
  try {
    const values = await requestValue(db.transaction(stores.session).objectStore(stores.session).getAll()) as OfflineSession[];
    return values.sort((a, b) => b.started_at.localeCompare(a.started_at))[0] ?? null;
  } finally {
    db.close();
  }
}

export async function saveSession(session: OfflineSession): Promise<void> {
  const db = await openPosDb();
  const transaction = db.transaction([stores.session, stores.catalogs], "readwrite");
  transaction.objectStore(stores.session).put(session);
  transaction.objectStore(stores.catalogs).put(session.catalog_snapshot);
  await transactionDone(transaction);
  db.close();
}

export async function saveCatalog(snapshot: PublicCatalogSnapshot): Promise<void> {
  const db = await openPosDb();
  const transaction = db.transaction(stores.catalogs, "readwrite");
  transaction.objectStore(stores.catalogs).put(snapshot);
  await transactionDone(transaction);
  db.close();
}

export async function readCatalog(id: string): Promise<PublicCatalogSnapshot | null> {
  const db = await openPosDb();
  try {
    return (await requestValue(db.transaction(stores.catalogs).objectStore(stores.catalogs).get(id)) as PublicCatalogSnapshot | undefined) ?? null;
  } finally {
    db.close();
  }
}

export async function readOrders(sessionId: string): Promise<OfflineOrder[]> {
  const db = await openPosDb();
  try {
    const values = await requestValue(db.transaction(stores.orders).objectStore(stores.orders).index("session_id").getAll(sessionId)) as OfflineOrder[];
    return values.sort((a, b) => b.created_at.localeCompare(a.created_at));
  } finally {
    db.close();
  }
}

export async function readPendingOrders(sessionId: string): Promise<OfflineOrder[]> {
  return (await readOrders(sessionId)).filter((order) =>
    order.revision > order.last_synced_revision || order.status.endsWith("PENDING_SYNC"),
  ).filter((order) => order.status !== "CONFLICT");
}

export async function readSyncState(): Promise<SyncState> {
  const db = await openPosDb();
  try {
    return (await requestValue(db.transaction(stores.sync).objectStore(stores.sync).get("state")) as SyncState | undefined)
      ?? { key: "state", status: "OFFLINE", last_sync_at: null, error: null };
  } finally {
    db.close();
  }
}

export async function writeSyncState(state: SyncState): Promise<void> {
  const db = await openPosDb();
  const transaction = db.transaction(stores.sync, "readwrite");
  transaction.objectStore(stores.sync).put(state);
  await transactionDone(transaction);
  db.close();
}

export async function assertWritable(): Promise<void> {
  const db = await openPosDb();
  const transaction = db.transaction(stores.meta, "readwrite");
  transaction.objectStore(stores.meta).put({ key: "write_check", value: Date.now() });
  await transactionDone(transaction);
  db.close();
}
