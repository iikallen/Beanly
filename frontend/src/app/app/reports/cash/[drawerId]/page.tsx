"use client";

import { ArrowLeft, RefreshCcw } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { useCashPermissions } from "@/hooks/use-cash-permissions";
import { api, type CashDrawerReport, type FiscalShiftStatusResponse } from "@/lib/api";
import { formatMenuPriceMinor } from "@/lib/menu";

export default function CashReportDetailPage() {
  const { drawerId } = useParams<{ drawerId: string }>();
  const { accessToken } = useAuth();
  const { currentOrganization } = useWorkspace();
  const permissions = useCashPermissions();
  const [report, setReport] = useState<CashDrawerReport | null>(null);
  const [fiscal, setFiscal] = useState<FiscalShiftStatusResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      await Promise.resolve();
      if (cancelled || !accessToken || !currentOrganization || permissions.loading || !permissions.canReport) return;
      setLoading(true); setError("");
      try {
        const next = await api.getCashDrawerReport(drawerId, currentOrganization.id, accessToken);
        if (cancelled) return;
        setReport(next);
        const nextFiscal = await api.getFiscalShiftStatus(next.summary.drawer.shift_id, currentOrganization.id, accessToken).catch(() => null);
        if (!cancelled) setFiscal(nextFiscal);
      } catch (caught) { if (!cancelled) setError(messageOf(caught)); }
      finally { if (!cancelled) setLoading(false); }
    }
    void load();
    return () => { cancelled = true; };
  }, [accessToken, currentOrganization, drawerId, permissions.canReport, permissions.loading, revision]);

  if (!permissions.loading && !permissions.canReport) return <State title="Cash report access required" message="Your role cannot view drawer reports." />;
  if (error) return <State error title="Cash drawer could not be loaded" message={error} />;
  if (loading || !report) return <State message="Loading drawer report…" />;
  const { drawer } = report.summary;
  const showExpected = permissions.canViewExpected && report.summary.expected_visible;
  return <>
    <header className="cash-report-header"><div><Link className="cash-report-back" href="/app/reports/cash"><ArrowLeft />Cash drawers</Link><h1>{formatDate(drawer.opened_at)}</h1><span>Immutable session {drawer.id}</span></div><button className="secondary-button" disabled={loading} type="button" onClick={() => setRevision((value) => value + 1)}><RefreshCcw className={loading ? "is-spinning" : ""} />Refresh</button></header>
    {(fiscal?.status === "UNKNOWN" || fiscal?.status === "RECONCILIATION_REQUIRED") && <div className="cash-fiscal-warning" role="status"><strong>Fiscal close requires reconciliation.</strong><span>Do not retry the Z-report while the provider result is unknown.</span></div>}
    <div className="cash-report-kpis">
      <Metric label="Starting" value={report.summary.starting_cash_minor} currency={drawer.currency_code} />
      <Metric label="Cash sales" value={report.summary.cash_payments_minor} currency={drawer.currency_code} />
      <Metric label="Cash refunds" value={report.summary.cash_refunds_minor} currency={drawer.currency_code} />
      <Metric label="Pay in" value={report.summary.pay_in_minor} currency={drawer.currency_code} />
      <Metric label="Pay out" value={report.summary.pay_out_minor} currency={drawer.currency_code} />
      <Metric label="Expected" value={showExpected ? report.summary.expected_cash_minor : null} currency={drawer.currency_code} />
      <Metric label="Actual" value={report.summary.actual_cash_minor} currency={drawer.currency_code} />
      <Metric label="Variance" value={showExpected ? report.summary.variance_minor : null} currency={drawer.currency_code} variance />
    </div>
    <section className="cash-report-panel"><header><div><h2>Drawer movements</h2><p>Recorded money movements cannot be edited or deleted.</p></div><span>{report.movements.length} entries</span></header>
      {report.movements.length === 0 ? <State message="No drawer movements recorded." /> : <div className="cash-report-table-wrap"><table className="cash-report-table"><thead><tr><th>Time</th><th>Kind</th><th>Reason</th><th>Source</th><th>Amount</th></tr></thead><tbody>{report.movements.map((movement) => <tr key={movement.id}><td>{formatDate(movement.occurred_at)}</td><td>{movement.kind.replaceAll("_", " ").toLowerCase()}</td><td>{movement.reason ?? movement.note ?? "—"}</td><td>{movement.source_id ? `${movement.source_type} · ${movement.source_id}` : movement.source_type}</td><td className={BigInt(movement.amount_minor) < BigInt(0) ? "is-negative" : "is-positive"}>{formatMenuPriceMinor(movement.amount_minor, drawer.currency_code)}</td></tr>)}</tbody></table></div>}
    </section>
  </>;
}

function Metric({ label, value, currency, variance = false }: { label: string; value: string | null; currency: string; variance?: boolean }) { const changed = value !== null && BigInt(value) !== BigInt(0); return <article className={variance && changed ? BigInt(value) < BigInt(0) ? "is-negative" : "is-positive" : ""}><span>{label}</span><strong>{value === null ? "—" : formatMenuPriceMinor(value, currency)}</strong></article>; }
function State({ title, message, error = false }: { title?: string; message: string; error?: boolean }) { return <div className={`cash-report-state${error ? " is-error" : ""}`} role={error ? "alert" : undefined}>{title && <strong>{title}</strong>}<span>{message}</span></div>; }
function formatDate(value: string) { return new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)); }
function messageOf(error: unknown) { return error instanceof Error ? error.message : "Unable to load cash drawer."; }
