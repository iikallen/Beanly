import type { DashboardOverview } from "@/lib/api";
import {
  formatDashboardMinor,
  formatDashboardMoney,
  formatTrendBucket,
} from "@/lib/dashboard";
import { DashboardEmpty, type DashboardEmptyActions } from "@/components/dashboard/dashboard-state";

const WIDTH = 720;
const HEIGHT = 220;
const TOP = 18;
const BOTTOM = 38;
const LEFT = 12;
const RIGHT = 12;

export function DashboardTrend({
  points,
  currency,
  period,
  timezone,
  emptyActions,
}: {
  points: DashboardOverview["trend"];
  currency: string;
  period: DashboardOverview["scope"]["period"];
  timezone: string;
  emptyActions: DashboardEmptyActions;
}) {
  const hasRefundMetrics = points.some((point) => point.net_sales_minor !== undefined);
  const values = points.map((point) => Math.max(0, Number(point.net_sales_minor ?? point.revenue)));
  const max = Math.max(...values, 0);
  if (!points.some((point) => point.orders > 0)) {
    return (
      <section className="dashboard-panel dashboard-trend-panel">
        <header><h2>{hasRefundMetrics ? "Net sales" : "Revenue"} trend</h2><span>{hasRefundMetrics ? "Sales after refunds" : "Revenue"} and paid orders</span></header>
        <DashboardEmpty actions={emptyActions} />
      </section>
    );
  }

  const usableWidth = WIDTH - LEFT - RIGHT;
  const usableHeight = HEIGHT - TOP - BOTTOM;
  const scaleMax = max || 1;
  const coordinates = values.map((value, index) => ({
    x: LEFT + (points.length === 1 ? usableWidth / 2 : index * usableWidth / (points.length - 1)),
    y: TOP + usableHeight - (value / scaleMax) * usableHeight,
  }));
  const line = coordinates.map(({ x, y }) => `${x},${y}`).join(" ");
  const area = [
    `${coordinates[0].x},${HEIGHT - BOTTOM}`,
    ...coordinates.map(({ x, y }) => `${x},${y}`),
    `${coordinates.at(-1)?.x ?? LEFT},${HEIGHT - BOTTOM}`,
  ].join(" ");

  return (
    <section className="dashboard-panel dashboard-trend-panel">
      <header><h2>{hasRefundMetrics ? "Net sales" : "Revenue"} trend</h2><span>{hasRefundMetrics ? "Sales after refunds" : "Revenue"} and paid orders</span></header>
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-labelledby="dashboard-trend-title dashboard-trend-description">
        <title id="dashboard-trend-title">{hasRefundMetrics ? "Net sales" : "Revenue"} trend</title>
        <desc id="dashboard-trend-description">{hasRefundMetrics ? "Net sales after refunds" : "Revenue"} across the selected reporting period. Each point also includes its paid order count.</desc>
        {[0, 1, 2, 3].map((lineIndex) => {
          const y = TOP + (usableHeight * lineIndex) / 3;
          return <line key={lineIndex} x1={LEFT} x2={WIDTH - RIGHT} y1={y} y2={y} className="dashboard-chart-grid" />;
        })}
        <polygon points={area} className="dashboard-chart-area" />
        <polyline points={line} className="dashboard-chart-line" />
        {coordinates.map(({ x, y }, index) => (
          <g key={points[index].bucket_start}>
            <circle cx={x} cy={y} r="4">
              <title>{`${formatTrendBucket(points[index].bucket_start, period, timezone)}: ${points[index].net_sales_minor !== undefined ? formatDashboardMinor(points[index].net_sales_minor, currency) : formatDashboardMoney(points[index].revenue, currency)}, ${points[index].orders} orders`}</title>
            </circle>
            {(points.length <= 12 || index % Math.ceil(points.length / 8) === 0 || index === points.length - 1) && (
              <text x={x} y={HEIGHT - 12} textAnchor="middle">
                {formatTrendBucket(points[index].bucket_start, period, timezone)}
              </text>
            )}
          </g>
        ))}
      </svg>
    </section>
  );
}
