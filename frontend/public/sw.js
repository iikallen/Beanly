const CACHE = "beanly-pos-shell-__BEANLY_BUILD__";
const SHELL = ["/beanly-icon.svg", "/beanly-icon-192.png", "/beanly-icon-512.png", "/manifest.webmanifest"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then(async (cache) => {
    await cache.addAll(SHELL);
    const shell = await fetch("/app/pos", { credentials: "include", cache: "no-store" });
    if (!shell.ok || !new URL(shell.url).pathname.startsWith("/app/pos")) throw new Error("POS shell requires an authenticated page load");
    await cache.put("/app/pos", shell);
  }));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((key) => key.startsWith("beanly-pos-shell-") && key !== CACHE).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return;

  if (request.mode === "navigate") {
    if (!url.pathname.startsWith("/app/pos")) return;
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok && new URL(response.url).pathname.startsWith("/app/pos")) caches.open(CACHE).then((cache) => cache.put("/app/pos", response.clone()));
          return response;
        })
        .catch(() => caches.match("/app/pos")),
    );
    return;
  }

  if (url.pathname.startsWith("/_next/static/") || url.pathname.startsWith("/beanly-icon") || url.pathname === "/manifest.webmanifest") {
    event.respondWith(
      caches.match(request).then((cached) => cached ?? fetch(request).then((response) => {
        if (response.ok) caches.open(CACHE).then((cache) => cache.put(request, response.clone()));
        return response;
      })),
    );
  }
});

self.addEventListener("sync", (event) => {
  if (event.tag !== "beanly-pos-sync") return;
  event.waitUntil(backgroundSync().finally(() => self.clients.matchAll({ type: "window", includeUncontrolled: true })
    .then((clients) => clients.forEach((client) => client.postMessage({ type: "BEANLY_POS_SYNC" })))));
});

self.addEventListener("message", (event) => {
  if (event.data?.type === "SKIP_WAITING") self.skipWaiting();
});

async function backgroundSync() {
  const db = await openDb();
  const sessions = await idb(db.transaction("offline_session").objectStore("offline_session").getAll());
  const session = sessions
    .filter((value) => value.status === "ACTIVE" || value.status === "EXPIRED")
    .sort((a, b) => b.started_at.localeCompare(a.started_at))[0];
  if (!session) return;
  const orders = (await idb(db.transaction("orders").objectStore("orders").index("session_id").getAll(session.id)))
    .filter((order) => order.status !== "CONFLICT" && (order.status.endsWith("PENDING_SYNC") || order.revision > order.last_synced_revision));
  for (let offset = 0; offset < orders.length; offset += 100) {
    const response = await fetch("/api/v1/pos/offline/sync", {
      method: "POST",
      credentials: "include",
      cache: "no-store",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ session_id: session.id, orders: orders.slice(offset, offset + 100).map(syncPayload) }),
    });
    if (!response.ok) throw new Error(`Background sync failed (${response.status})`);
  }
}

function syncPayload(order) {
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
      : order.status === "CANCELLED_PENDING_SYNC" || order.status === "SYNCED_CANCELLED" ? "CANCELLED" : "OPEN",
    items: order.items.map((item) => ({
      client_item_id: item.client_item_id,
      variant_id: item.product_variant_id,
      selected_option_ids: item.selected_option_ids,
      quantity: item.quantity,
      note: item.note,
    })),
    payment: order.payment,
  };
}

function openDb() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open("beanly-pos-v1", 1);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function idb(request) {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}
