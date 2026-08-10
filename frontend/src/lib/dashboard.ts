import type {
  DashboardDirection,
  DashboardMetric,
  DashboardOverview,
  DashboardPeriod,
} from "@/lib/api";
import { formatFinanceMinor, formatFinanceMoney } from "@/lib/finance";

export const DASHBOARD_PERIODS: Array<{ value: DashboardPeriod; label: string }> = [
  { value: "TODAY", label: "Today" },
  { value: "YESTERDAY", label: "Yesterday" },
  { value: "LAST_7_DAYS", label: "Last 7 days" },
  { value: "THIS_MONTH", label: "This month" },
  { value: "CUSTOM", label: "Custom" },
];

export function formatDashboardMoney(value: string, currency: string) {
  return formatFinanceMoney(value, currency);
}

export function formatDashboardMinor(value: string, currency: string) {
  return formatFinanceMinor(value, currency);
}

export function comparisonLabel(metric: DashboardMetric<string | number>) {
  if (metric.percent_change === null) return "No previous baseline";
  if (metric.direction === "FLAT") return "No change vs previous";
  const sign = metric.direction === "UP" ? "↑" : "↓";
  return `${sign} ${formatPercent(metric.percent_change.replace(/^[+-]/, ""))} vs previous`;
}

export function comparisonTone(
  direction: DashboardDirection,
  favorable: "UP" | "DOWN" | "NONE" = "UP",
) {
  if (direction === "FLAT" || favorable === "NONE") return "neutral";
  return direction === favorable ? "positive" : "negative";
}

export function formatPercent(value: string | null) {
  if (value === null) return "—";
  return `${new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(Number(value))}%`;
}

export function formatScopeDate(scope: DashboardOverview["scope"]) {
  const formatter = new Intl.DateTimeFormat(undefined, {
    timeZone: scope.timezone,
    weekday: scope.period === "TODAY" || scope.period === "YESTERDAY" ? "long" : undefined,
    month: "short",
    day: "numeric",
    year: "numeric",
  });
  const from = new Date(scope.current.from);
  if (scope.period === "TODAY" || scope.period === "YESTERDAY") return formatter.format(from);
  const to = new Date(new Date(scope.current.to).getTime() - 1);
  return `${formatter.format(from)} – ${formatter.format(to)}`;
}

export function formatTrendBucket(
  value: string,
  period: DashboardPeriod,
  timezone: string,
) {
  return new Intl.DateTimeFormat(undefined, {
    timeZone: timezone,
    hour: period === "TODAY" || period === "YESTERDAY" ? "2-digit" : undefined,
    hour12: false,
    month: period === "TODAY" || period === "YESTERDAY" ? undefined : "short",
    day: period === "TODAY" || period === "YESTERDAY" ? undefined : "numeric",
  }).format(new Date(value));
}

export function paymentMethodLabel(method: string) {
  return method === "CARD" ? "Card" : method === "CASH" ? "Cash" : "Other";
}

export function localDateInput(now = new Date()) {
  const offset = now.getTimezoneOffset() * 60_000;
  return new Date(now.getTime() - offset).toISOString().slice(0, 10);
}
