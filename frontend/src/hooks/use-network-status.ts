"use client";

import { useCallback, useEffect, useState } from "react";

import { pingOfflineApi } from "@/lib/offline/api";

export type NetworkStatus = "CHECKING" | "ONLINE" | "OFFLINE";

export function useNetworkStatus() {
  const [status, setStatus] = useState<NetworkStatus>("CHECKING");

  const check = useCallback(async () => {
    const reachable = await pingOfflineApi();
    setStatus(reachable ? "ONLINE" : "OFFLINE");
    return reachable;
  }, []);

  useEffect(() => {
    queueMicrotask(() => { void check(); });
    const trigger = () => { void check(); };
    window.addEventListener("online", trigger);
    window.addEventListener("offline", trigger);
    const interval = window.setInterval(trigger, 30_000);
    return () => {
      window.removeEventListener("online", trigger);
      window.removeEventListener("offline", trigger);
      window.clearInterval(interval);
    };
  }, [check]);

  return { status, check };
}
