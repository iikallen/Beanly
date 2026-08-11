"use client";

import { MapPin } from "lucide-react";
import { useCallback } from "react";

import { AnalyticsHeader } from "@/components/analytics/analytics-controls";
import { useAnalyticsScope } from "@/components/analytics/analytics-provider";
import { AnalyticsAccessState, AnalyticsEmpty, AnalyticsError, AnalyticsLoading } from "@/components/analytics/analytics-state";
import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { useAnalyticsQuery } from "@/hooks/use-analytics-query";
import { api } from "@/lib/api";
import { formatAnalyticsInteger, formatAnalyticsMoney, formatAnalyticsPercent } from "@/lib/analytics";

export default function AnalyticsLocationsPage() {
  const { accessToken } = useAuth();
  const { currentOrganization } = useWorkspace();
  const scope = useAnalyticsScope();
  const key = `${currentOrganization?.id}:${scope.dateFrom}:${scope.dateTo}`;
  const load = useCallback(async () => {
    if (!currentOrganization || !accessToken) throw new Error("Authentication required");
    return api.getAnalyticsLocations(currentOrganization.id, accessToken, { dateFrom: scope.dateFrom, dateTo: scope.dateTo });
  }, [accessToken, currentOrganization, scope.dateFrom, scope.dateTo]);
  const query = useAnalyticsQuery(key, scope.canRead && Boolean(accessToken && currentOrganization), load);
  const data = query.data;
  const rows = [...(data?.rows ?? [])].sort((left, right) => left.revenue_rank - right.revenue_rank);
  const hasRefundMetrics = rows.some((row) => row.net_revenue !== undefined);

  return <>
    <AnalyticsHeader title="Locations" description="Transparent ranking across every location you can access." dataAsOf={data?.data_as_of} showLocation={false} />
    {!scope.canRead ? <AnalyticsAccessState /> : query.error ? <AnalyticsError message={query.error} onRetry={query.retry} /> : !data ? <AnalyticsLoading /> : !rows.length ? <AnalyticsEmpty message="No location metrics are available for this period." /> : <>
      <section className="analytics-location-cards" aria-label="Location highlights">{rows.slice(0, 3).map((row) => <article key={row.location_id}><header><span><MapPin aria-hidden="true" /></span><div><small>{hasRefundMetrics ? "Net sales" : "Revenue"} rank #{row.revenue_rank}</small><h2>{row.location_name}</h2></div></header><strong>{formatAnalyticsMoney(row.net_revenue ?? row.revenue, scope.currency)}</strong>{row.gross_revenue !== undefined && row.refund_amount !== undefined && <small className="analytics-refund-breakdown">Gross {formatAnalyticsMoney(row.gross_revenue, scope.currency)} · Refunds −{formatAnalyticsMoney(row.refund_amount, scope.currency)}</small>}<dl><div><dt>Orders</dt><dd>{formatAnalyticsInteger(row.paid_orders)} <small>#{row.orders_rank}</small></dd></div><div><dt>Average check</dt><dd>{formatAnalyticsMoney(row.average_check, scope.currency)} <small>#{row.average_check_rank}</small></dd></div>{scope.canReadFinance && <><div><dt>Gross margin</dt><dd>{formatAnalyticsPercent(row.gross_margin_percent)} {row.gross_margin_rank && <small>#{row.gross_margin_rank}</small>}</dd></div><div><dt>Operating profit</dt><dd>{formatAnalyticsMoney(row.operating_profit, scope.currency)} {row.operating_profit_rank && <small>#{row.operating_profit_rank}</small>}</dd></div></>}</dl></article>)}</section>
      <section className="analytics-panel analytics-table-panel"><header><div><span>All accessible locations</span><h2>Location Benchmarking</h2></div><p>Ranks are shown per metric — no hidden composite score</p></header><div className="analytics-table-wrap"><table className="analytics-table"><thead><tr><th scope="col">Location</th><th scope="col">{hasRefundMetrics ? "Net revenue" : "Revenue"}</th><th scope="col">Orders</th><th scope="col">Items</th><th scope="col">Average check</th>{scope.canReadFinance && <><th scope="col">Gross margin</th><th scope="col">Operating profit</th></>}</tr></thead><tbody>{rows.map((row) => <tr key={row.location_id}><th scope="row">{row.location_name}</th><td>{formatAnalyticsMoney(row.net_revenue ?? row.revenue, scope.currency)} <Rank value={row.revenue_rank} />{row.gross_revenue !== undefined && row.refund_amount !== undefined && <small>Gross {formatAnalyticsMoney(row.gross_revenue, scope.currency)} · Refunds −{formatAnalyticsMoney(row.refund_amount, scope.currency)}</small>}</td><td>{formatAnalyticsInteger(row.paid_orders)} <Rank value={row.orders_rank} /></td><td>{formatAnalyticsInteger(row.items_sold)}</td><td>{formatAnalyticsMoney(row.average_check, scope.currency)} <Rank value={row.average_check_rank} /></td>{scope.canReadFinance && <><td>{formatAnalyticsPercent(row.gross_margin_percent)} <Rank value={row.gross_margin_rank} /></td><td>{formatAnalyticsMoney(row.operating_profit, scope.currency)} <Rank value={row.operating_profit_rank} /></td></>}</tr>)}</tbody></table></div></section>
    </>}
  </>;
}

function Rank({ value }: { value: number | null }) {
  return value === null ? null : <small className="analytics-rank">#{value}</small>;
}
