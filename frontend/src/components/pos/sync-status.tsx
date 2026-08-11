import { formatMenuPriceMinor } from "@/lib/menu";
import type { SyncState } from "@/lib/offline/types";

export function SyncStatus({
  state,
  pending,
  pendingTotal,
  currency,
  onSync,
  disabled = false,
}: {
  state: SyncState;
  pending: number;
  pendingTotal: bigint;
  currency: string;
  onSync: () => void;
  disabled?: boolean;
}) {
  return (
    <div className="pos-sync-status" role="status">
      <span>{state.status === "SYNCING" ? "Syncing…" : state.error ? "Sync issue" : state.last_sync_at ? `Synced ${relativeTime(state.last_sync_at)}` : "Not synced yet"}</span>
      {pending > 0 && <b>{pending} pending · {formatMenuPriceMinor(String(pendingTotal), currency)}</b>}
      {state.error && <small>{state.error}</small>}
      <button type="button" disabled={disabled || state.status === "SYNCING"} onClick={onSync}>Sync now</button>
    </div>
  );
}

function relativeTime(value: string) {
  const seconds = Math.max(0, Math.round((Date.now() - Date.parse(value)) / 1000));
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  return `${Math.floor(seconds / 3600)}h ago`;
}
