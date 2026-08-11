import type { StorageReadiness } from "@/lib/offline/types";

export function OfflineReady({ readiness, onPrepare }: { readiness: StorageReadiness; onPrepare: () => void }) {
  const ready = readiness.indexedDb && readiness.catalog && readiness.device && readiness.shell;
  return (
    <div className={ready ? "pos-offline-ready is-ready" : "pos-offline-ready"}>
      <strong>{ready ? "Offline ready" : "Offline mode unavailable"}</strong>
      <span>{readiness.indexedDb ? "✓" : "×"} IndexedDB</span>
      <span>{readiness.catalog ? "✓" : "×"} Catalog</span>
      <span>{readiness.device ? "✓" : "×"} POS device</span>
      <span>{readiness.shell ? "✓ App shell" : "× App shell"}</span>
      <span>{readiness.persistent ? "✓ Persistent storage" : "⚠ Storage may be cleared"}</span>
      {!readiness.persistent && <button type="button" onClick={onPrepare}>Protect offline data</button>}
    </div>
  );
}
