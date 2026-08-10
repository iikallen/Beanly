"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export function useAnalyticsQuery<T>(key: string, enabled: boolean, loader: () => Promise<T>) {
  const [result, setResult] = useState<{ key: string; data: T } | null>(null);
  const [errorResult, setErrorResult] = useState<{ key: string; message: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);
  const requestId = useRef(0);

  useEffect(() => {
    let cancelled = false;
    const activeRequestId = ++requestId.current;
    async function load() {
      await Promise.resolve();
      if (cancelled || !enabled) return;
      setLoading(true);
      setErrorResult(null);
      try {
        const data = await loader();
        if (!cancelled && requestId.current === activeRequestId) setResult({ key, data });
      } catch (caught) {
        if (!cancelled && requestId.current === activeRequestId) setErrorResult({ key, message: caught instanceof Error ? caught.message : "Unable to load analytics" });
      } finally {
        if (!cancelled && requestId.current === activeRequestId) setLoading(false);
      }
    }
    void load();
    return () => { cancelled = true; };
  }, [enabled, key, loader, refreshKey]);

  const retry = useCallback(() => setRefreshKey((current) => current + 1), []);
  return {
    data: result?.key === key ? result.data : null,
    error: errorResult?.key === key ? errorResult.message : "",
    loading,
    retry,
  };
}
