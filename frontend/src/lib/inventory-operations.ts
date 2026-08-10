import type { InventoryLineValue } from "@/components/inventory-lines-editor";

const POSITIVE_DECIMAL = /^\d+(?:\.\d{1,6})?$/;

export function validOperationLines(lines: InventoryLineValue[]) {
  return lines.length > 0 && lines.every((line) =>
    line.inventoryItemId && POSITIVE_DECIMAL.test(line.quantity.trim()) && Number(line.quantity) > 0,
  );
}

export function localDateTimeNow() {
  const date = new Date(Date.now() - new Date().getTimezoneOffset() * 60_000);
  return date.toISOString().slice(0, 16);
}

export function toApiDate(value: string) {
  return new Date(value).toISOString();
}

export function decimalDifference(actual: string, expected: string) {
  if (!actual.trim()) return "—";
  const difference = Number(actual) - Number(expected);
  return Number.isFinite(difference) ? String(Math.round(difference * 1_000_000) / 1_000_000) : "—";
}
