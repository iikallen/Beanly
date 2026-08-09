import type {
  GoodsReceiptStatus,
  InventoryUnitCode,
  PurchaseOrderLine,
  PurchaseOrderStatus,
} from "@/lib/api";

const DECIMAL = /^\d+(?:\.\d{1,6})?$/;

export function isPositiveDecimal(value: string) {
  return DECIMAL.test(value.trim()) && Number(value) > 0;
}

export function isNonNegativeDecimal(value: string) {
  return DECIMAL.test(value.trim()) && Number(value) >= 0;
}

export function defaultPurchaseUnit(baseUnit: InventoryUnitCode) {
  if (baseUnit === "g") return { unit: "kg", multiplier: "1000" };
  if (baseUnit === "ml") return { unit: "l", multiplier: "1000" };
  return { unit: baseUnit, multiplier: "1" };
}

export function formatPurchaseUnit(value: string) {
  return value.toLowerCase() === "l" ? "L" : value;
}

export function formatMoneyMinor(value: string | number | undefined, currency: string) {
  const minor = Number(value ?? 0);
  const amount = minor / 100;

  if (currency === "KZT") {
    return `${new Intl.NumberFormat("en", {
      maximumFractionDigits: amount % 1 === 0 ? 0 : 2,
    }).format(amount)} ₸`;
  }

  return new Intl.NumberFormat("en", {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(amount);
}

export function formatMoneyAmount(value: string, currency: string) {
  if (currency === "KZT") {
    return `${new Intl.NumberFormat("en", {
      maximumFractionDigits: 6,
    }).format(Number(value))} ₸`;
  }

  return new Intl.NumberFormat("en", {
    style: "currency",
    currency,
    maximumFractionDigits: 6,
  }).format(Number(value));
}

export function formatPurchaseDate(value: string | null, fallback = "—") {
  if (!value) return fallback;
  return new Intl.DateTimeFormat("en", { dateStyle: "medium" }).format(new Date(value));
}

export function formatPurchaseStatus(value: PurchaseOrderStatus | GoodsReceiptStatus) {
  const label = value.toLowerCase().replaceAll("_", " ");
  return label.charAt(0).toUpperCase() + label.slice(1);
}

export function orderTotalMinor(lines: PurchaseOrderLine[]) {
  return lines.reduce((total, line) => total + Number(line.line_total_minor), 0);
}

export function decimalSubtract(left: string, right: string) {
  return String(Math.max(0, Number(left) - Number(right)));
}

export function statusClass(value: PurchaseOrderStatus | GoodsReceiptStatus) {
  return `purchasing-status status-${value.toLowerCase().replaceAll("_", "-")}`;
}
