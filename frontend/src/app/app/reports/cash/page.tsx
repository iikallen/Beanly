"use client";

import { RefreshCcw } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { useCashPermissions } from "@/hooks/use-cash-permissions";
import { api, type CashDrawerReportRow, type CashDrawerStatus } from "@/lib/api";
import { formatMenuPriceMinor } from "@/lib/menu";

export default function CashReportsPage() {
  const { accessToken } = useAuth();
  const { currentOrganization, locations } = useWorkspace();
  const permissions = useCashPermissions();
  const initial = currentMonth();
  const [dateFrom, setDateFrom] = useState(initial.from);
  const [dateTo, setDateTo] = useState(initial.to);
  const [locationId, setLocationId] = useState("");
  const [status, setStatus] = useState<CashDrawerStatus | "">("");
  const [rows, setRows] = useState<CashDrawerReportRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      await Promise.resolve();
      if (cancelled || !accessToken || !currentOrganization || permissions.loading || !permissions.canReport) return;
      setLoading(true); setError("");
      try { const next = await api.listCashDrawerReports(currentOrganization.id, accessToken, { locationId, dateFrom, dateTo, status }); if (!cancelled) setRows(next); }
      catch (caught) { if (!cancelled) setError(messageOf(caught)); }
      finally { if (!cancelled) setLoading(false); }
    }
    void load();
    return () => { cancelled = true; };
  }, [accessToken, currentOrganization, dateFrom, dateTo, locationId, permissions.canReport, permissions.loading, revision, status]);

  return <>
    <header className="cash-report-header"><div><p>Reports / Cash</p><h1>Cash drawers</h1><span>Immutable drawer movements and close-of-day reconciliation.</span></div><button className="secondary-button" disabled={loading} type="button" onClick={() => setRevision((value) => value + 1)}><RefreshCcw className={loading ? "is-spinning" : ""} />Refresh</button></header>
    <div className="cash-report-filters">
      <label><span>From</span><input type="date" max={dateTo} value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} /></label>
      <label><span>To</span><input type="date" min={dateFrom} value={dateTo} onChange={(event) => setDateTo(event.target.value)} /></label>
      <label><span>Location</span><select value={locationId} onChange={(event) => setLocationId(event.target.value)}><option value="">All accessible locations</option>{locations.filter((item) => item.is_active).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      <label><span>Status</span><select value={status} onChange={(event) => setStatus(event.target.value as CashDrawerStatus | "")}><option value="">All statuses</option><option value="OPEN">Open</option><option value="CLOSING">Closing</option><option value="CLOSED">Closed</option></select></label>
    </div>
    {!permissions.loading && !permissions.canReport ? <State title="Cash report access required" message="Your role cannot view drawer reports." />
      : error ? <State error title="Cash reports could not be loaded" message={error} />
      : loading ? <State message="Loading cash drawers…" />
      : rows.length === 0 ? <State title="No cash drawers found" message="No drawer sessions match these filters." />
      : <div className="cash-report-table-wrap" tabIndex={0} aria-label="Cash drawer reports"><table className="cash-report-table"><thead><tr><th>Date</th><th>Location / Register</th><th>Cashier</th><th>Status</th><th>Starting</th><th>Expected</th><th>Actual</th><th>Variance</th></tr></thead><tbody>{rows.map((row) => <tr key={row.id}><td><Link href={`/app/reports/cash/${row.id}`}>{formatDate(row.opened_at)}</Link></td><td><strong>{row.location_name}</strong><small>{row.register_name}</small></td><td>{row.cashier_name}</td><td><span className={`cash-status status-${row.status.toLowerCase()}`}>{row.status.toLowerCase()}</span></td><td>{formatMenuPriceMinor(row.starting_cash_minor, row.currency_code)}</td><td>{permissions.canViewExpected && row.expected_cash_minor !== null ? formatMenuPriceMinor(row.expected_cash_minor, row.currency_code) : "—"}</td><td>{row.actual_cash_minor === null ? "—" : formatMenuPriceMinor(row.actual_cash_minor, row.currency_code)}</td><td className={varianceClass(row.variance_minor)}>{permissions.canViewExpected && row.variance_minor !== null ? formatMenuPriceMinor(row.variance_minor, row.currency_code) : "—"}</td></tr>)}</tbody></table></div>}
  </>;
}

function State({ title, message, error = false }: { title?: string; message: string; error?: boolean }) { return <div className={`cash-report-state${error ? " is-error" : ""}`} role={error ? "alert" : undefined}>{title && <strong>{title}</strong>}<span>{message}</span></div>; }
function currentMonth() { const now = new Date(); return { from: localDate(new Date(now.getFullYear(), now.getMonth(), 1)), to: localDate(new Date(now.getFullYear(), now.getMonth() + 1, 0)) }; }
function localDate(value: Date) { return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`; }
function formatDate(value: string) { return new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)); }
function varianceClass(value: string | null) { return value && BigInt(value) !== BigInt(0) ? BigInt(value) < BigInt(0) ? "is-negative" : "is-positive" : ""; }
function messageOf(error: unknown) { return error instanceof Error ? error.message : "Unable to load cash reports."; }
