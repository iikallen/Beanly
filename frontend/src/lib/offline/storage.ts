import { assertWritable, readCatalog, readCurrentSession } from "./db";
import type { StorageReadiness } from "./types";

export async function prepareOfflineStorage(requestPersistence = false): Promise<StorageReadiness> {
  let indexedDb = false;
  try {
    await assertWritable();
    indexedDb = true;
  } catch {
    return { indexedDb: false, catalog: false, persistent: false, device: false, shell: false, usage: 0, quota: 0 };
  }

  const session = await readCurrentSession();
  const catalog = session ? Boolean(await readCatalog(session.catalog_snapshot_id)) : false;
  const persistent = "storage" in navigator && "persisted" in navigator.storage
    ? requestPersistence && "persist" in navigator.storage
      ? await navigator.storage.persist()
      : await navigator.storage.persisted()
    : false;
  const estimate = "storage" in navigator && "estimate" in navigator.storage
    ? await navigator.storage.estimate()
    : {};
  const shell = "serviceWorker" in navigator && "caches" in globalThis
    ? Boolean(navigator.serviceWorker.controller && await caches.match("/app/pos").catch(() => undefined))
    : false;
  return {
    indexedDb,
    catalog,
    persistent,
    device: Boolean(session?.device_id),
    shell,
    usage: estimate.usage ?? 0,
    quota: estimate.quota ?? 0,
  };
}
