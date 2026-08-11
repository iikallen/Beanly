"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { useNetworkStatus } from "./use-network-status";
import { usePosPwa } from "./use-pos-pwa";
import { readOrders, readSyncState } from "@/lib/offline/db";
import { cleanupSyncedOrders } from "@/lib/offline/orders";
import { prepareOfflineStorage } from "@/lib/offline/storage";
import { syncOfflineOrders } from "@/lib/offline/sync-engine";
import type { OfflineOrder, OfflineSession, StorageReadiness, SyncState } from "@/lib/offline/types";
import { acquireWriterLock } from "@/lib/offline/writer-lock";

const EMPTY_STORAGE: StorageReadiness = { indexedDb: false, catalog: false, persistent: false, device: false, shell: false, usage: 0, quota: 0 };
const EMPTY_SYNC: SyncState = { key: "state", status: "OFFLINE", last_sync_at: null, error: null };

export function useOfflinePos(session: OfflineSession | null) {
  const [orders, setOrders] = useState<OfflineOrder[]>([]);
  const [syncState, setSyncState] = useState(EMPTY_SYNC);
  const [storage, setStorage] = useState(EMPTY_STORAGE);
  const [isWriter, setIsWriter] = useState(false);
  const { status: networkStatus, check } = useNetworkStatus();

  const reload = useCallback(async () => {
    if (!session) return;
    const [nextOrders, nextSync, nextStorage] = await Promise.all([
      readOrders(session.id),
      readSyncState(),
      prepareOfflineStorage(),
    ]);
    setOrders(nextOrders);
    setSyncState(nextSync);
    setStorage(nextStorage);
  }, [session]);

  const syncNow = useCallback(async () => {
    if (!session || !isWriter) return;
    setSyncState((current) => ({ ...current, status: "SYNCING", error: null }));
    const result = await syncOfflineOrders(session);
    setSyncState(result);
    await reload();
  }, [isWriter, reload, session]);

  const pendingOrders = useMemo(() => orders.filter((order) =>
    order.status.endsWith("PENDING_SYNC") || order.revision > order.last_synced_revision,
  ), [orders]);
  const unresolvedOrders = useMemo(() => orders.filter((order) =>
    order.status === "CONFLICT" || order.status.endsWith("PENDING_SYNC") || order.revision > order.last_synced_revision,
  ), [orders]);
  const pendingTotal = useMemo(() => unresolvedOrders
    .filter((order) => order.status === "PAID_PENDING_SYNC" || (order.status === "CONFLICT" && order.payment))
    .reduce((sum, order) => sum + BigInt(order.total_minor), BigInt(0)), [unresolvedOrders]);

  const backgroundSync = useCallback(() => { void syncNow(); }, [syncNow]);
  const pwa = usePosPwa(unresolvedOrders.length, backgroundSync);

  useEffect(() => {
    let writerLease: { release: () => void } | undefined;
    let cancelled = false;
    void acquireWriterLock(setIsWriter).then((lease) => {
      if (cancelled) lease.release();
      else writerLease = lease;
    });
    return () => {
      cancelled = true;
      writerLease?.release();
    };
  }, []);

  useEffect(() => {
    queueMicrotask(() => { void reload(); });
    void cleanupSyncedOrders();
    const channel = new BroadcastChannel("beanly-pos-data");
    channel.onmessage = () => { void reload(); };
    return () => channel.close();
  }, [reload]);

  useEffect(() => {
    if (!("serviceWorker" in navigator)) return;
    const ready = () => { void prepareOfflineStorage().then(setStorage); };
    navigator.serviceWorker.addEventListener("controllerchange", ready);
    return () => navigator.serviceWorker.removeEventListener("controllerchange", ready);
  }, []);

  useEffect(() => {
    if (!session || !isWriter || networkStatus !== "ONLINE") return;
    queueMicrotask(() => { void syncNow(); });
  }, [isWriter, networkStatus, session, syncNow]);

  useEffect(() => {
    if (!session || !isWriter) return;
    const visible = () => { if (document.visibilityState === "visible") void check().then((online) => { if (online) void syncNow(); }); };
    document.addEventListener("visibilitychange", visible);
    const interval = window.setInterval(() => { if (pendingOrders.length) void syncNow(); }, 15_000);
    return () => {
      document.removeEventListener("visibilitychange", visible);
      window.clearInterval(interval);
    };
  }, [check, isWriter, pendingOrders.length, session, syncNow]);

  const requestPersistence = useCallback(async () => {
    const readiness = await prepareOfflineStorage(true);
    setStorage(readiness);
    return readiness;
  }, []);

  return {
    orders,
    reload,
    syncNow,
    syncState,
    networkStatus,
    storage,
    requestPersistence,
    isWriter,
    pendingCount: pendingOrders.length,
    unresolvedCount: unresolvedOrders.length,
    pendingTotal,
    ...pwa,
  };
}
