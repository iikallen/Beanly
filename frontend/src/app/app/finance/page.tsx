"use client";

import { AlertTriangle } from "lucide-react";
import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { useFinancePermissions } from "@/hooks/use-finance-permissions";
import { api, type FinancePnl } from "@/lib/api";
import { currentMonthRange, financeApiRange, formatFinanceMoney } from "@/lib/finance";

export default function FinanceOverviewPage() {
  const { accessToken } = useAuth();
  const { currentOrganization } = useWorkspace();
  const { canRead, loading: permissionsLoading } = useFinancePermissions();
  const initial = currentMonthRange();
  const [dateFrom, setDateFrom] = useState(initial.dateFrom);
  const [dateTo, setDateTo] = useState(initial.dateTo);
  const [pnl, setPnl] = useState<FinancePnl | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      await Promise.resolve();
      if (cancelled || !accessToken || !currentOrganization || permissionsLoading || !canRead) return;
      setLoading(true);
      setError("");
      try {
        const next = await api.getFinancePnl(currentOrganization.id, accessToken, financeApiRange(dateFrom, dateTo));
        if (!cancelled) setPnl(next);
      } catch (caught) {
        if (!cancelled) setError(caught instanceof Error ? caught.message : "Unable to load finance overview");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => { cancelled = true; };
  }, [accessToken, canRead, currentOrganization, dateFrom, dateTo, permissionsLoading]);

  const currency = pnl?.currency_code ?? currentOrganization?.currency_code ?? "KZT";

  return (
    <>
      <header className="finance-header">
        <div><h1>Finance</h1><p>Organization-wide management results and cash health.</p></div>
        <div className="finance-period">
          <label><span>From</span><input type="date" value={dateFrom} max={dateTo} onChange={(event) => setDateFrom(event.target.value)} /></label>
          <label><span>To</span><input type="date" value={dateTo} min={dateFrom} onChange={(event) => setDateTo(event.target.value)} /></label>
        </div>
      </header>
      {!permissionsLoading && !canRead ? (
        <div className="finance-state"><strong>Finance access required</strong><span>Your role cannot view financial reports.</span></div>
      ) : error ? (
        <div className="finance-state is-error" role="alert"><strong>Finance overview could not be loaded.</strong><span>{error}</span></div>
      ) : loading || !pnl ? (
        <div className="finance-state" aria-live="polite">Loading finance overview…</div>
      ) : (
        <>
          {pnl.data_quality.incomplete_cogs_sales > 0 && (
            <div className="finance-quality-warning" role="status">
              <AlertTriangle aria-hidden="true" />
              <div><strong>Profit estimate may be understated.</strong><p>{pnl.data_quality.incomplete_cogs_sales} sales have incomplete inventory cost.</p></div>
            </div>
          )}
          <div className="finance-kpi-grid">
            <article className="finance-kpi"><span>Revenue</span><strong>{formatFinanceMoney(pnl.revenue, currency)}</strong><small>Completed payments</small></article>
            <article className="finance-kpi is-primary"><span>Gross Profit</span><strong>{formatFinanceMoney(pnl.gross_profit, currency)}</strong><small>{pnl.gross_margin_percent === null ? "No revenue in this period" : `${pnl.gross_margin_percent}% margin`}</small></article>
            <article className="finance-kpi"><span>Operating Expenses</span><strong>{formatFinanceMoney(pnl.operating_expenses, currency)}</strong><small>Posted manual expenses</small></article>
            <article className={`finance-kpi is-primary${pnl.operating_profit.startsWith("-") ? " is-negative" : ""}`}><span>Operating Profit</span><strong>{formatFinanceMoney(pnl.operating_profit, currency)}</strong><small>After COGS, losses and expenses</small></article>
          </div>
        </>
      )}
    </>
  );
}
