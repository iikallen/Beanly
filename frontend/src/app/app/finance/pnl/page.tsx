"use client";

import { AlertTriangle } from "lucide-react";
import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { useFinancePermissions } from "@/hooks/use-finance-permissions";
import { api, type FinancePnl, type FinancePnlBreakdown } from "@/lib/api";
import { currentMonthRange, financeApiRange, formatFinanceMoney, formatFinanceOutflow } from "@/lib/finance";

export default function ProfitAndLossPage() {
  const { accessToken } = useAuth();
  const { currentOrganization, locations } = useWorkspace();
  const { canRead, loading: permissionsLoading } = useFinancePermissions();
  const initial = currentMonthRange();
  const [dateFrom, setDateFrom] = useState(initial.dateFrom);
  const [dateTo, setDateTo] = useState(initial.dateTo);
  const [locationId, setLocationId] = useState("");
  const [pnl, setPnl] = useState<FinancePnl | null>(null);
  const [breakdown, setBreakdown] = useState<FinancePnlBreakdown | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      await Promise.resolve();
      if (cancelled || !accessToken || !currentOrganization || permissionsLoading || !canRead) return;
      setLoading(true);
      setError("");
      const filters = { ...financeApiRange(dateFrom, dateTo), locationId: locationId || undefined };
      try {
        const [nextPnl, nextBreakdown] = await Promise.all([
          api.getFinancePnl(currentOrganization.id, accessToken, filters),
          api.getFinancePnlBreakdown(currentOrganization.id, accessToken, filters),
        ]);
        if (!cancelled) { setPnl(nextPnl); setBreakdown(nextBreakdown); }
      } catch (caught) {
        if (!cancelled) setError(caught instanceof Error ? caught.message : "Unable to load profit and loss");
      } finally { if (!cancelled) setLoading(false); }
    }
    void load();
    return () => { cancelled = true; };
  }, [accessToken, canRead, currentOrganization, dateFrom, dateTo, locationId, permissionsLoading]);

  const currency = pnl?.currency_code ?? currentOrganization?.currency_code ?? "KZT";

  return (
    <>
      <header className="finance-header">
        <div><h1>Profit &amp; Loss</h1><p>Management profitability by period and location.</p></div>
        <div className="finance-header-actions">
          <label className="finance-filter"><span>Location</span><select value={locationId} onChange={(event) => setLocationId(event.target.value)}><option value="">All locations</option>{locations.map((location) => <option key={location.id} value={location.id}>{location.name}</option>)}</select></label>
          <div className="finance-period"><label><span>From</span><input type="date" value={dateFrom} max={dateTo} onChange={(event) => setDateFrom(event.target.value)} /></label><label><span>To</span><input type="date" value={dateTo} min={dateFrom} onChange={(event) => setDateTo(event.target.value)} /></label></div>
        </div>
      </header>
      {!permissionsLoading && !canRead ? (
        <div className="finance-state"><strong>Finance access required</strong><span>Your role cannot view P&amp;L.</span></div>
      ) : error ? (
        <div className="finance-state is-error" role="alert"><strong>Profit &amp; Loss could not be loaded.</strong><span>{error}</span></div>
      ) : loading || !pnl || !breakdown ? (
        <div className="finance-state" aria-live="polite">Loading Profit &amp; Loss…</div>
      ) : (
        <>
          {!pnl.data_quality.cogs_complete && <div className="finance-quality-warning" role="status"><AlertTriangle aria-hidden="true" /><div><strong>Profit estimate may be understated.</strong><p>{pnl.data_quality.incomplete_cogs_sales} sales have incomplete inventory cost.</p></div></div>}
          <section className="finance-statement" aria-label="Profit and loss statement">
            <div className="finance-statement-row"><span>Revenue</span><strong>{formatFinanceMoney(pnl.revenue, currency)}</strong></div>
            <div className="finance-statement-row is-negative"><span>Cost of Goods Sold</span><strong>{formatFinanceOutflow(pnl.cogs, currency)}</strong></div>
            <div className="finance-statement-row is-subtotal"><span>Gross Profit <small>{pnl.gross_margin_percent === null ? "" : `${pnl.gross_margin_percent}%`}</small></span><strong>{formatFinanceMoney(pnl.gross_profit, currency)}</strong></div>
            <div className="finance-statement-row is-negative"><span>Inventory losses</span><strong>{formatFinanceOutflow(pnl.inventory_losses, currency)}</strong></div>
            <div className="finance-statement-row"><span>Inventory gains</span><strong>{formatFinanceMoney(pnl.inventory_gains, currency)}</strong></div>
            <h2 className="finance-statement-heading">Operating expenses</h2>
            {breakdown.operating_expenses.length === 0 ? <div className="finance-statement-row"><span>No posted expenses</span><strong>{formatFinanceMoney("0", currency)}</strong></div> : breakdown.operating_expenses.map((row) => <div className="finance-statement-row is-negative" key={row.category_id ?? row.name}><span>{row.name}</span><strong>{formatFinanceOutflow(row.amount, currency)}</strong></div>)}
            <div className="finance-statement-row is-negative"><span>Total operating expenses</span><strong>{formatFinanceOutflow(pnl.operating_expenses, currency)}</strong></div>
            <div className="finance-statement-row"><span>Other income</span><strong>{formatFinanceMoney(pnl.other_income, currency)}</strong></div>
            <div className="finance-statement-row is-negative"><span>Other expenses</span><strong>{formatFinanceOutflow(pnl.other_expenses, currency)}</strong></div>
            <div className="finance-statement-row is-total"><span>Operating Profit</span><strong>{formatFinanceMoney(pnl.operating_profit, currency)}</strong></div>
          </section>
        </>
      )}
    </>
  );
}
