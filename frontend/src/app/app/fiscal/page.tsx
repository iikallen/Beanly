"use client";

import { AlertTriangle, CheckCircle2, CircleAlert, Clock3, ExternalLink, RefreshCcw } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { useIntegrationPermissions } from "@/hooks/use-integration-permissions";
import { api, type FiscalOperations, type FiscalReceipt, type FiscalReceiptStatus } from "@/lib/api";
import { fiscalReceiptAction, fiscalStatusLabel, safeReceiptUrl } from "@/lib/fiscal-live";

const FILTERS: Array<{ value: FiscalReceiptStatus | ""; label: string }> = [
  { value: "", label: "All statuses" },
  { value: "PENDING", label: "Pending" },
  { value: "PROCESSING", label: "Processing" },
  { value: "RETRYING", label: "Retrying" },
  { value: "UNKNOWN", label: "Unknown" },
  { value: "DEAD", label: "Needs attention" },
  { value: "SUCCEEDED", label: "Issued" },
];

export default function FiscalOperationsPage() {
  const { accessToken } = useAuth();
  const { currentOrganization, currentLocation } = useWorkspace();
  const permissions = useIntegrationPermissions();
  const [operations, setOperations] = useState<FiscalOperations | null>(null);
  const [receipts, setReceipts] = useState<FiscalReceipt[]>([]);
  const [status, setStatus] = useState<FiscalReceiptStatus | "">("");
  const [loading, setLoading] = useState(true);
  const [workingId, setWorkingId] = useState("");
  const [error, setError] = useState("");
  const requestId = useRef(0);

  const load = useCallback(async () => {
    if (!accessToken || !currentOrganization || !currentLocation || permissions.loading || !permissions.canReadFiscal) {
      setLoading(false);
      return;
    }
    const activeRequest = ++requestId.current;
    setLoading(true);
    setError("");
    setOperations(null);
    setReceipts([]);
    try {
      const [nextOperations, nextReceipts] = await Promise.all([
        api.getFiscalOperations(currentLocation.id, currentOrganization.id, accessToken),
        api.listFiscalReceipts(currentOrganization.id, accessToken, {
          locationId: currentLocation.id,
          status,
          limit: "50",
          offset: "0",
        }),
      ]);
      if (activeRequest !== requestId.current) return;
      setOperations(nextOperations);
      setReceipts(nextReceipts.items);
    } catch (caught) {
      if (activeRequest === requestId.current) setError(messageOf(caught));
    } finally {
      if (activeRequest === requestId.current) setLoading(false);
    }
  }, [accessToken, currentLocation, currentOrganization, permissions.canReadFiscal, permissions.loading, status]);

  useEffect(() => { queueMicrotask(() => { void load(); }); }, [load]);

  async function act(receipt: FiscalReceipt) {
    if (!accessToken || !currentOrganization || !permissions.canWriteFiscal) return;
    const action = fiscalReceiptAction(receipt.status);
    if (action === "NONE") return;
    setWorkingId(receipt.id);
    setError("");
    try {
      const updated = action === "RECONCILE"
        ? await api.reconcileFiscalReceipt(receipt.id, currentOrganization.id, accessToken)
        : await api.retryFiscalReceipt(receipt.id, currentOrganization.id, accessToken);
      setReceipts((current) => current.map((item) => item.id === updated.id ? updated : item));
      await load();
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setWorkingId("");
    }
  }

  if (permissions.loading) return <div className="fiscal-state">Loading fiscal operations…</div>;
  if (!permissions.canReadFiscal) return <div className="fiscal-state"><strong>Fiscal operations access required</strong><span>Your role cannot view fiscal receipts.</span></div>;

  return (
    <>
      <header className="fiscal-operations-header">
        <div><h1>Fiscal</h1><p>{currentLocation?.name} · Live receipt operations</p></div>
        <div><Link className="secondary-button" href="/app/settings/fiscal">Settings</Link><button className="secondary-button" disabled={loading} type="button" onClick={() => void load()}><RefreshCcw className={loading ? "is-spinning" : ""} aria-hidden="true" />Refresh</button></div>
      </header>

      {error && <div className="fiscal-alert" role="alert"><CircleAlert aria-hidden="true" />{error}</div>}
      {operations && operations.unknown > 0 && <div className="fiscal-operations-alert is-critical" role="alert"><AlertTriangle aria-hidden="true" /><div><strong>{operations.unknown} receipt {operations.unknown === 1 ? "has" : "have"} an unknown result</strong><p>Do not issue another receipt. Reconcile the provider operation first.</p></div></div>}
      {operations && operations.pending > 0 && <div className="fiscal-operations-alert"><Clock3 aria-hidden="true" /><div><strong>{operations.pending} receipt {operations.pending === 1 ? "is" : "are"} pending</strong><p>{operations.oldest_pending_seconds === null ? "Beanly will continue processing." : `Oldest pending for ${formatDuration(operations.oldest_pending_seconds)}.`}</p></div></div>}

      <section className="fiscal-operations-summary" aria-label="Today's fiscal receipt summary">
        <article><span>Provider</span><strong>{operations?.provider_code || "Not configured"}</strong><small className={operations?.connected ? "is-success" : "is-danger"}>{operations?.connected ? "● Connected" : "● Disconnected"}</small></article>
        <article><span>Receipts</span><strong>{operations?.receipts_today ?? "—"}</strong><small>Today</small></article>
        <article><span>Successful</span><strong>{operations?.successful_today ?? "—"}</strong><small>Issued today</small></article>
        <article><span>Pending</span><strong>{operations?.pending ?? "—"}</strong><small>Queued or retrying</small></article>
        <article><span>Failed</span><strong>{operations?.failed ?? "—"}</strong><small>Needs attention</small></article>
      </section>

      <section className="fiscal-receipts" aria-labelledby="fiscal-receipts-title">
        <div className="fiscal-receipts-heading"><div><h2 id="fiscal-receipts-title">Receipts</h2><p>Payment remains complete while fiscal delivery is pending.</p></div><label><span>Status</span><select value={status} onChange={(event) => setStatus(event.target.value as FiscalReceiptStatus | "")}>{FILTERS.map((filter) => <option key={filter.value || "all"} value={filter.value}>{filter.label}</option>)}</select></label></div>
        {loading && receipts.length === 0 ? <div className="fiscal-state is-compact">Loading receipts…</div> : receipts.length === 0 ? <div className="fiscal-state is-compact"><CheckCircle2 aria-hidden="true" /><strong>No receipts in this view</strong><span>New fiscal operations will appear here.</span></div> : <div className="fiscal-receipt-list">{receipts.map((receipt) => {
          const action = fiscalReceiptAction(receipt.status);
          const receiptUrl = safeReceiptUrl(receipt.receipt_url);
          return <article key={receipt.id}>
            <time dateTime={receipt.created_at}>{formatTime(receipt.created_at)}</time>
            <div><strong>{receipt.source_type === "SALE" ? "Sale" : "Refund"} · {shortId(receipt.source_id)}</strong><span>{receipt.receipt_number ? `Receipt ${receipt.receipt_number}` : receipt.provider_code}</span>{receipt.last_error_message && <small>{receipt.last_error_message}</small>}</div>
            <span className={`fiscal-receipt-status is-${receipt.status.toLowerCase()}`}><i aria-hidden="true" />{fiscalStatusLabel(receipt.status)}</span>
            <div className="fiscal-receipt-actions">{receiptUrl && <a href={receiptUrl} target="_blank" rel="noreferrer">View <ExternalLink aria-hidden="true" /></a>}{permissions.canWriteFiscal && action !== "NONE" && <button className="secondary-button" disabled={workingId === receipt.id} type="button" onClick={() => void act(receipt)}>{workingId === receipt.id ? "Working…" : action === "RECONCILE" ? "Check provider" : "Retry"}</button>}</div>
          </article>;
        })}</div>}
      </section>
    </>
  );
}

function shortId(value: string) { return value.length > 12 ? `${value.slice(0, 8)}…` : value; }
function formatTime(value: string) { return new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" }).format(new Date(value)); }
function formatDuration(seconds: number) { const minutes = Math.floor(seconds / 60); return minutes ? `${minutes}m ${seconds % 60}s` : `${seconds}s`; }
function messageOf(error: unknown) { return error instanceof Error ? error.message : "Unable to load fiscal operations"; }
