"use client";

import { Banknote, CircleAlert, PackageOpen, Percent, ReceiptText, RotateCcw, ShoppingBag } from "lucide-react";
import Link from "next/link";
import { useCallback } from "react";

import { AnalyticsHeader } from "@/components/analytics/analytics-controls";
import { useAnalyticsScope } from "@/components/analytics/analytics-provider";
import { AnalyticsAccessState, AnalyticsEmpty, AnalyticsError, AnalyticsLoading } from "@/components/analytics/analytics-state";
import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { useAnalyticsQuery } from "@/hooks/use-analytics-query";
import { api, type AnalyticsHours, type AnalyticsInventoryConsumption, type AnalyticsOverview, type AnalyticsProducts } from "@/lib/api";
import { compareAnalyticsDecimal, formatAnalyticsInteger, formatAnalyticsMoney, formatAnalyticsPercent, formatAnalyticsQuantity, sumAnalyticsDecimals } from "@/lib/analytics";

type OverviewBundle = { overview: AnalyticsOverview; products: AnalyticsProducts; hours: AnalyticsHours; inventory: AnalyticsInventoryConsumption };

export default function AnalyticsOverviewPage() {
  const { accessToken } = useAuth();
  const { currentOrganization } = useWorkspace();
  const scope = useAnalyticsScope();
  const key = `${currentOrganization?.id}:${scope.dateFrom}:${scope.dateTo}:${scope.locationId}`;
  const load = useCallback(async (): Promise<OverviewBundle> => {
    if (!currentOrganization || !accessToken) throw new Error("Authentication required");
    const filters = { dateFrom: scope.dateFrom, dateTo: scope.dateTo, locationId: scope.locationId || undefined };
    const [overview, products, hours, inventory] = await Promise.all([
      api.getAnalyticsOverview(currentOrganization.id, accessToken, filters),
      api.getAnalyticsProducts(currentOrganization.id, accessToken, { ...filters, groupBy: "PRODUCT", sortBy: "REVENUE", limit: "5" }),
      api.getAnalyticsHours(currentOrganization.id, accessToken, { ...filters, metric: "REVENUE" }),
      api.getAnalyticsInventoryConsumption(currentOrganization.id, accessToken, filters),
    ]);
    return { overview, products, hours, inventory };
  }, [accessToken, currentOrganization, scope.dateFrom, scope.dateTo, scope.locationId]);
  const query = useAnalyticsQuery(key, scope.canRead && Boolean(accessToken && currentOrganization), load);
  const data = query.data;
  const peakHours = data ? peakHourRanges(data.hours) : [];
  const hasRefundMetrics = data?.overview.gross_revenue !== undefined
    && data.overview.refund_amount !== undefined
    && data.overview.net_revenue !== undefined;

  return <>
    <AnalyticsHeader title="Analytics" description="Historical performance built from event-driven read models." dataAsOf={data?.overview.data_as_of} />
    {!scope.canRead ? <AnalyticsAccessState /> : query.error ? <AnalyticsError message={query.error} onRetry={query.retry} /> : !data ? <AnalyticsLoading /> : data.overview.paid_orders === 0 && data.inventory.rows.length === 0 ? <AnalyticsEmpty /> : <>
      <section className="analytics-kpi-grid" aria-label="Analytics overview metrics">
        {hasRefundMetrics ? <>
          <Metric icon={<Banknote />} label="Gross Sales" value={formatAnalyticsMoney(data.overview.gross_revenue!, data.overview.currency_code)} />
          <Metric icon={<RotateCcw />} label="Refunds" value={`−${formatAnalyticsMoney(data.overview.refund_amount!, data.overview.currency_code)}`} />
          <Metric icon={<Banknote />} label="Net Sales" value={formatAnalyticsMoney(data.overview.net_revenue!, data.overview.currency_code)} />
        </> : <Metric icon={<Banknote />} label="Revenue" value={formatAnalyticsMoney(data.overview.revenue, data.overview.currency_code)} />}
        <Metric icon={<ShoppingBag />} label="Orders" value={formatAnalyticsInteger(data.overview.paid_orders)} />
        <Metric icon={<ReceiptText />} label="Average check" value={formatAnalyticsMoney(data.overview.average_check, data.overview.currency_code)} />
        {scope.canReadFinance ? <Metric icon={<Percent />} label="Gross margin" value={formatAnalyticsPercent(data.overview.gross_margin_percent)} /> : <Metric icon={<PackageOpen />} label="Items sold" value={formatAnalyticsInteger(data.overview.items_sold)} />}
      </section>
      {scope.canReadFinance && (data.overview.incomplete_cogs_orders ?? 0) > 0 && <div className="finance-quality-warning" role="status"><CircleAlert aria-hidden="true" /><div><strong>Estimated or incomplete COGS</strong><p>{formatAnalyticsInteger(data.overview.incomplete_cogs_orders ?? 0)} orders need recipe or cost review. Net sales and refunds are unaffected.</p></div></div>}
      <div className="analytics-overview-grid">
        <section className="analytics-panel analytics-top-products"><header><div><span>Sales mix</span><h2>Top Products</h2></div><Link href="/app/analytics/products">View all</Link></header>{data.products.rows.length ? <ol>{data.products.rows.map((row, index) => <li key={row.product_id}><span><b>{index + 1}</b>{row.name}</span><strong>{formatAnalyticsMoney(row.net_revenue ?? row.revenue, data.overview.currency_code)}</strong></li>)}</ol> : <p className="analytics-panel-empty">No product sales in this period.</p>}</section>
        <section className="analytics-panel analytics-peak-hours"><header><div><span>Demand</span><h2>Peak Hours</h2></div><Link href="/app/analytics/hours">Open heatmap</Link></header>{peakHours.length ? <div className="analytics-peak-list">{peakHours.map((hour) => <article key={hour.hour}><strong>{String(hour.hour).padStart(2, "0")}:00 — {String((hour.hour + 1) % 24).padStart(2, "0")}:00</strong><span>{formatAnalyticsMoney(hour.value, data.overview.currency_code)} revenue</span></article>)}</div> : <p className="analytics-panel-empty">No hourly sales in this period.</p>}</section>
        <section className="analytics-panel analytics-overview-inventory"><header><div><span>Stock usage</span><h2>Inventory Consumption</h2></div><Link href="/app/analytics/inventory">View details</Link></header>{data.inventory.rows.length ? <div>{data.inventory.rows.slice(0, 5).map((row) => <article key={row.inventory_item_id}><PackageOpen aria-hidden="true" /><span><strong>{row.name}</strong><small>{formatAnalyticsQuantity(row.sale_quantity, row.base_unit)} used in sales</small></span>{scope.canReadFinance && <b>{formatAnalyticsMoney(row.sale_cost_amount, data.overview.currency_code)}</b>}</article>)}</div> : <p className="analytics-panel-empty">No consumption in this period.</p>}</section>
      </div>
    </>}
  </>;
}

function Metric({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return <article className="analytics-kpi"><span aria-hidden="true">{icon}</span><div><small>{label}</small><strong>{value}</strong></div></article>;
}

function peakHourRanges(hours: AnalyticsHours) {
  const grouped = new Map<number, string[]>();
  for (const row of hours.rows) grouped.set(row.local_hour, [...(grouped.get(row.local_hour) ?? []), row.value]);
  return [...grouped].map(([hour, values]) => ({ hour, value: sumAnalyticsDecimals(values) })).sort((left, right) => compareAnalyticsDecimal(right.value, left.value)).slice(0, 3);
}
