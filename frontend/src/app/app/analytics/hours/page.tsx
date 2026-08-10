"use client";

import { useCallback, useState, type CSSProperties } from "react";

import { AnalyticsHeader } from "@/components/analytics/analytics-controls";
import { useAnalyticsScope } from "@/components/analytics/analytics-provider";
import { AnalyticsAccessState, AnalyticsEmpty, AnalyticsError, AnalyticsLoading } from "@/components/analytics/analytics-state";
import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { useAnalyticsQuery } from "@/hooks/use-analytics-query";
import { api, type AnalyticsHourMetric } from "@/lib/api";
import { chartValue, formatAnalyticsDecimal, formatAnalyticsMoney } from "@/lib/analytics";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export default function AnalyticsHoursPage() {
  const { accessToken } = useAuth();
  const { currentOrganization } = useWorkspace();
  const scope = useAnalyticsScope();
  const [metric, setMetric] = useState<AnalyticsHourMetric>("REVENUE");
  const key = `${currentOrganization?.id}:${scope.dateFrom}:${scope.dateTo}:${scope.locationId}:${metric}`;
  const load = useCallback(async () => {
    if (!currentOrganization || !accessToken) throw new Error("Authentication required");
    return api.getAnalyticsHours(currentOrganization.id, accessToken, { dateFrom: scope.dateFrom, dateTo: scope.dateTo, locationId: scope.locationId || undefined, metric });
  }, [accessToken, currentOrganization, metric, scope.dateFrom, scope.dateTo, scope.locationId]);
  const query = useAnalyticsQuery(key, scope.canRead && Boolean(accessToken && currentOrganization), load);
  const data = query.data;

  return <>
    <AnalyticsHeader title="Sales by Hour" description="Weekly demand patterns in each location's local business time." dataAsOf={data?.data_as_of}>
      <label><span>Metric</span><select value={metric} onChange={(event) => setMetric(event.target.value as AnalyticsHourMetric)}><option value="REVENUE">Revenue</option><option value="ORDERS">Orders</option><option value="ITEMS">Items sold</option></select></label>
    </AnalyticsHeader>
    {!scope.canRead ? <AnalyticsAccessState /> : query.error ? <AnalyticsError message={query.error} onRetry={query.retry} /> : !data ? <AnalyticsLoading /> : !data.rows.some((row) => chartValue(row.value) !== 0) ? <AnalyticsEmpty message="No completed sales are available for this period." /> : <Heatmap metric={metric} rows={data.rows} currency={scope.currency} />}
  </>;
}

function Heatmap({ metric, rows, currency }: { metric: AnalyticsHourMetric; rows: Array<{ day_of_week: number; local_hour: number; value: string }>; currency: string }) {
  const values = new Map(rows.map((row) => [`${row.local_hour}:${row.day_of_week}`, row.value]));
  const max = Math.max(...rows.map((row) => chartValue(row.value)), 1);
  const format = (value: string) => metric === "REVENUE" ? formatAnalyticsMoney(value, currency) : formatAnalyticsDecimal(value, 0);
  return <section className="analytics-panel analytics-heatmap-panel"><header><div><span>Local business time</span><h2>Weekly Heatmap</h2></div><div className="analytics-heat-legend"><span>Quiet</span><i /><i /><i /><span>Busy</span></div></header><div className="analytics-heatmap-wrap"><table className="analytics-heatmap"><caption className="sr-only">{metric.toLowerCase()} by local hour and day of week</caption><thead><tr><th scope="col">Hour</th>{DAYS.map((day) => <th key={day} scope="col">{day}</th>)}</tr></thead><tbody>{Array.from({ length: 24 }, (_, hour) => <tr key={hour}><th scope="row">{String(hour).padStart(2, "0")}:00</th>{DAYS.map((day, dayIndex) => { const value = values.get(`${hour}:${dayIndex}`) ?? "0"; const intensity = chartValue(value) / max; return <td key={day} style={{ "--heat": Math.max(.04, intensity) } as CSSProperties} aria-label={`${day} ${String(hour).padStart(2, "0")}:00, ${format(value)}`}><span>{format(value)}</span></td>; })}</tr>)}</tbody></table></div></section>;
}
