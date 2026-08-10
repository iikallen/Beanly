"use client";

import { LockKeyhole } from "lucide-react";
import { useCallback } from "react";

import { AnalyticsHeader } from "@/components/analytics/analytics-controls";
import { useAnalyticsScope } from "@/components/analytics/analytics-provider";
import { AnalyticsAccessState, AnalyticsEmpty, AnalyticsError, AnalyticsLoading } from "@/components/analytics/analytics-state";
import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { useAnalyticsQuery } from "@/hooks/use-analytics-query";
import { api, type AnalyticsMenuClass, type AnalyticsMenuEngineering } from "@/lib/api";
import { chartValue, formatAnalyticsInteger, formatAnalyticsMoney, formatAnalyticsPercent } from "@/lib/analytics";

const CLASS_LABEL: Record<AnalyticsMenuClass, string> = { HERO: "Hero", WORKHORSE: "Workhorse", PUZZLE: "Puzzle", LOW_PERFORMER: "Low Performer" };
const CLASS_NOTE: Record<AnalyticsMenuClass, string> = { HERO: "Protect / promote", WORKHORSE: "Inspect price / recipe", PUZZLE: "Improve visibility", LOW_PERFORMER: "Reconsider menu position" };

export default function MenuEngineeringPage() {
  const { accessToken } = useAuth();
  const { currentOrganization } = useWorkspace();
  const scope = useAnalyticsScope();
  const key = `${currentOrganization?.id}:${scope.dateFrom}:${scope.dateTo}:${scope.locationId}`;
  const load = useCallback(async () => {
    if (!currentOrganization || !accessToken) throw new Error("Authentication required");
    return api.getAnalyticsMenuEngineering(currentOrganization.id, accessToken, { dateFrom: scope.dateFrom, dateTo: scope.dateTo, locationId: scope.locationId || undefined });
  }, [accessToken, currentOrganization, scope.dateFrom, scope.dateTo, scope.locationId]);
  const query = useAnalyticsQuery(key, scope.canRead && scope.canReadFinance && Boolean(accessToken && currentOrganization), load);
  const data = query.data;

  return <>
    <AnalyticsHeader title="Menu Engineering" description="Popularity and contribution margin reveal each product's role." dataAsOf={data?.data_as_of} />
    {!scope.canRead ? <AnalyticsAccessState /> : !scope.canReadFinance ? <div className="analytics-state"><LockKeyhole aria-hidden="true" /><strong>Finance access required</strong><span>Menu Engineering classifies products using confidential profit data.</span></div> : query.error ? <AnalyticsError message={query.error} onRetry={query.retry} /> : !data ? <AnalyticsLoading /> : !data.rows.length ? <AnalyticsEmpty message="Products with no sales are excluded from classification." /> : <>
      <section className="analytics-panel analytics-scatter-panel"><header><div><span>Beanly v1 matrix</span><h2>Product Portfolio</h2></div><p>Popularity × contribution margin</p></header><MenuScatter data={data} currency={scope.currency} /></section>
      <section className="analytics-panel analytics-menu-table"><header><div><span>Four quadrants</span><h2>Classification</h2></div><p>Popularity threshold: {formatAnalyticsPercent(data.thresholds.high_popularity_share_percent)}</p></header><div className="analytics-table-wrap"><table className="analytics-table"><thead><tr><th scope="col">Product</th><th scope="col">Sold</th><th scope="col">Popularity</th><th scope="col">Margin / item</th><th scope="col">Gross margin</th><th scope="col">Class</th></tr></thead><tbody>{data.rows.map((row) => <tr key={row.product_id}><th scope="row">{row.name}</th><td>{formatAnalyticsInteger(row.quantity_sold)}</td><td>{formatAnalyticsPercent(row.popularity_share_percent)}</td><td>{formatAnalyticsMoney(row.contribution_margin_per_item, scope.currency)}</td><td>{formatAnalyticsPercent(row.gross_margin_percent)}</td><td><span className={`analytics-menu-class class-${row.classification.toLowerCase().replace("_", "-")}`}>{CLASS_LABEL[row.classification]}</span><small>{CLASS_NOTE[row.classification]}</small></td></tr>)}</tbody></table></div></section>
    </>}
  </>;
}

function MenuScatter({ data, currency }: { data: AnalyticsMenuEngineering; currency: string }) {
  const width = 900;
  const height = 480;
  const left = 72;
  const top = 38;
  const right = 30;
  const bottom = 58;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const maxPopularity = Math.max(chartValue(data.thresholds.high_popularity_share_percent) * 2, ...data.rows.map((row) => chartValue(row.popularity_share_percent)), 1);
  const maxMargin = Math.max(chartValue(data.thresholds.average_contribution_margin_per_item) * 2, ...data.rows.map((row) => chartValue(row.contribution_margin_per_item)), 1);
  const thresholdX = left + Math.min(1, chartValue(data.thresholds.high_popularity_share_percent) / maxPopularity) * plotWidth;
  const thresholdY = top + (1 - Math.min(1, chartValue(data.thresholds.average_contribution_margin_per_item) / maxMargin)) * plotHeight;
  return <div className="analytics-scatter-wrap"><svg viewBox={`0 0 ${width} ${height}`} role="img" aria-labelledby="menu-scatter-title menu-scatter-description"><title id="menu-scatter-title">Menu Engineering product matrix</title><desc id="menu-scatter-description">Products plotted by popularity on the horizontal axis and contribution margin per item on the vertical axis.</desc>
    <rect x={left} y={top} width={thresholdX - left} height={thresholdY - top} className="zone-puzzle" /><rect x={thresholdX} y={top} width={width - right - thresholdX} height={thresholdY - top} className="zone-hero" /><rect x={left} y={thresholdY} width={thresholdX - left} height={height - bottom - thresholdY} className="zone-low" /><rect x={thresholdX} y={thresholdY} width={width - right - thresholdX} height={height - bottom - thresholdY} className="zone-workhorse" />
    <line x1={thresholdX} x2={thresholdX} y1={top} y2={height - bottom} className="analytics-scatter-threshold" /><line x1={left} x2={width - right} y1={thresholdY} y2={thresholdY} className="analytics-scatter-threshold" />
    <text x={left + 14} y={top + 24}>PUZZLE</text><text x={thresholdX + 14} y={top + 24}>HERO</text><text x={left + 14} y={height - bottom - 14}>LOW PERFORMER</text><text x={thresholdX + 14} y={height - bottom - 14}>WORKHORSE</text>
    {data.rows.map((row) => { const x = left + Math.min(1, chartValue(row.popularity_share_percent) / maxPopularity) * plotWidth; const y = top + (1 - Math.min(1, chartValue(row.contribution_margin_per_item) / maxMargin)) * plotHeight; return <g key={row.product_id} tabIndex={0} role="img" aria-label={`${row.name}: ${formatAnalyticsPercent(row.popularity_share_percent)} popularity, ${formatAnalyticsMoney(row.contribution_margin_per_item, currency)} contribution margin per item, ${CLASS_LABEL[row.classification]}`}><title>{`${row.name}\n${row.quantity_sold} sold\n${formatAnalyticsPercent(row.popularity_share_percent)} popularity\n${formatAnalyticsMoney(row.contribution_margin_per_item, currency)} contribution margin/item\n${formatAnalyticsPercent(row.gross_margin_percent)} gross margin\n${CLASS_LABEL[row.classification]}`}</title><circle cx={x} cy={y} r="8" className={`point-${row.classification.toLowerCase().replace("_", "-")}`} /><text x={x + 12} y={y + 4} className="analytics-point-label">{row.name}</text></g>; })}
    <text x={left + plotWidth / 2} y={height - 14} className="analytics-axis-label">Popularity →</text><text transform={`translate(18 ${top + plotHeight / 2}) rotate(-90)`} className="analytics-axis-label">Contribution margin / item →</text>
  </svg></div>;
}
