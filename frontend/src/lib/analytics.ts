import { formatFinanceMoney } from "@/lib/finance";
export { compareAnalyticsDecimal, formatAnalyticsDecimal, formatAnalyticsInteger, sumAnalyticsDecimals } from "@/lib/analytics-decimal";
import { formatAnalyticsDecimal } from "@/lib/analytics-decimal";

export function analyticsDateRange(timeZone?: string, now = new Date()) {
  const dateTo = timeZone ? dateInTimeZone(now, timeZone) : localDate(now);
  const from = new Date(`${dateTo}T00:00:00Z`);
  from.setUTCDate(from.getUTCDate() - 29);
  return { dateFrom: from.toISOString().slice(0, 10), dateTo };
}

export function formatAnalyticsMoney(value: string | null | undefined, currency: string) {
  return value === null || value === undefined ? "—" : formatFinanceMoney(value, currency);
}

export function formatAnalyticsPercent(value: string | null) {
  return value === null ? "—" : `${formatAnalyticsDecimal(value, 1)}%`;
}

export function formatAnalyticsQuantity(value: string, unit: string) {
  return `${formatAnalyticsDecimal(value, 3)} ${unit}`;
}

export function formatAnalyticsDateTime(value: string | null) {
  if (!value) return "No projections yet";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export function chartValue(value: string) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function localDate(value: Date) {
  const offset = value.getTimezoneOffset() * 60_000;
  return new Date(value.getTime() - offset).toISOString().slice(0, 10);
}

function dateInTimeZone(value: Date, timeZone: string) {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(value);
  const part = (type: Intl.DateTimeFormatPartTypes) => parts.find((item) => item.type === type)?.value ?? "";
  return `${part("year")}-${part("month")}-${part("day")}`;
}
