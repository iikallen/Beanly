"use client";

import { useCallback, useEffect, useRef, useState } from "react";

type SyncRegistration = ServiceWorkerRegistration & { sync?: { register: (tag: string) => Promise<void> } };

export function usePosPwa(pendingCount: number, onBackgroundSync: () => void) {
  const [updateWaiting, setUpdateWaiting] = useState<ServiceWorker | null>(null);
  const accepted = useRef(false);

  useEffect(() => {
    if (!("serviceWorker" in navigator)) return;
    const message = (event: MessageEvent) => {
      if (event.data?.type === "BEANLY_POS_SYNC") onBackgroundSync();
    };
    const controllerChange = () => { if (accepted.current) window.location.reload(); };
    navigator.serviceWorker.addEventListener("message", message);
    navigator.serviceWorker.addEventListener("controllerchange", controllerChange);
    navigator.serviceWorker.register("/sw.js").then((value) => {
      if (value.waiting) setUpdateWaiting(value.waiting);
      value.addEventListener("updatefound", () => {
        value.installing?.addEventListener("statechange", () => {
          if (value.waiting) setUpdateWaiting(value.waiting);
        });
      });
    }).catch(() => undefined);
    return () => {
      navigator.serviceWorker.removeEventListener("message", message);
      navigator.serviceWorker.removeEventListener("controllerchange", controllerChange);
    };
  }, [onBackgroundSync]);

  useEffect(() => {
    if (!pendingCount || !("serviceWorker" in navigator)) return;
    navigator.serviceWorker.ready
      .then((registration) => (registration as SyncRegistration).sync?.register("beanly-pos-sync"))
      .catch(() => undefined);
  }, [pendingCount]);

  const applyUpdate = useCallback(() => {
    if (!updateWaiting || pendingCount > 0) return;
    accepted.current = true;
    updateWaiting.postMessage({ type: "SKIP_WAITING" });
  }, [pendingCount, updateWaiting]);

  return { updatePending: Boolean(updateWaiting), applyUpdate };
}
