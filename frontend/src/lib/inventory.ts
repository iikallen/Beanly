import type { InventoryUnitCode } from "@/lib/api";

export function formatInventoryQuantity(
  value: string,
  baseUnit: InventoryUnitCode,
  signed = false,
) {
  const normalized = normalizeDecimal(value);
  const positive = !normalized.startsWith("-") && normalized !== "0";
  const sign = signed && positive ? "+" : "";

  if ((baseUnit === "g" || baseUnit === "ml") && atLeastOneThousand(normalized)) {
    return `${sign}${shiftDecimalLeftThree(normalized)} ${baseUnit === "g" ? "kg" : "L"}`;
  }
  return `${sign}${normalized} ${baseUnit === "l" ? "L" : baseUnit}`;
}

export function formatInventoryDate(value: string | null) {
  if (!value) return "Not posted";
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function formatTransactionType(value: string) {
  return value
    .toLowerCase()
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export function formatInventoryMoney(value: string | null, currencyCode: string) {
  if (value === null) return "Hidden";
  const symbol = new Intl.NumberFormat("en", {
    style: "currency",
    currency: currencyCode,
  }).formatToParts(0).find((part) => part.type === "currency")?.value ?? currencyCode;
  return `${normalizeDecimal(value)} ${symbol}`;
}

export function formatUnitCost(
  value: string | null,
  baseUnit: InventoryUnitCode,
  currencyCode: string,
  quantityForDisplay?: string | null,
) {
  if (value === null) return "Hidden";
  const displayUnit = quantityForDisplay
    ? preferredDisplayUnit(quantityForDisplay, baseUnit)
    : baseUnit;
  const displayValue = displayUnit === "kg" || displayUnit === "l"
    ? shiftDecimalRightThree(normalizeDecimal(value))
    : value;
  return `${formatInventoryMoney(displayValue, currencyCode)} / ${displayUnit === "l" ? "L" : displayUnit}`;
}

export function unitsFor(baseUnit: InventoryUnitCode): InventoryUnitCode[] {
  if (baseUnit === "g" || baseUnit === "kg") return ["g", "kg"];
  if (baseUnit === "ml" || baseUnit === "l") return ["ml", "l"];
  return ["pcs"];
}

export function preferredDisplayUnit(value: string, baseUnit: InventoryUnitCode) {
  if (baseUnit === "g" && atLeastOneThousand(normalizeDecimal(value))) return "kg";
  if (baseUnit === "ml" && atLeastOneThousand(normalizeDecimal(value))) return "l";
  return baseUnit;
}

export function isZeroDecimal(value: string) {
  return /^[+-]?0*(?:\.0*)?$/.test(value.trim());
}

export function isNegativeDecimal(value: string) {
  return value.trim().startsWith("-") && !isZeroDecimal(value);
}

function normalizeDecimal(value: string) {
  const match = value.trim().match(/^([+-]?)(\d+)(?:\.(\d+))?$/);
  if (!match) return value;
  const negative = match[1] === "-";
  const integer = match[2].replace(/^0+(?=\d)/, "");
  const fraction = (match[3] ?? "").replace(/0+$/, "");
  const normalized = fraction ? `${integer}.${fraction}` : integer;
  return negative && normalized !== "0" ? `-${normalized}` : normalized;
}

function atLeastOneThousand(value: string) {
  const absolute = value.replace(/^[+-]/, "");
  const integer = absolute.split(".")[0].replace(/^0+/, "") || "0";
  return integer.length > 3 || (integer.length === 4 && integer >= "1000");
}

function shiftDecimalLeftThree(value: string) {
  const negative = value.startsWith("-");
  const absolute = value.replace(/^[+-]/, "");
  const [integer, fraction = ""] = absolute.split(".");
  const padded = integer.padStart(4, "0");
  const split = padded.length - 3;
  const nextInteger = padded.slice(0, split).replace(/^0+(?=\d)/, "") || "0";
  const nextFraction = `${padded.slice(split)}${fraction}`.replace(/0+$/, "");
  const shifted = nextFraction ? `${nextInteger}.${nextFraction}` : nextInteger;
  return negative ? `-${shifted}` : shifted;
}

function shiftDecimalRightThree(value: string) {
  const negative = value.startsWith("-");
  const absolute = value.replace(/^[+-]/, "");
  const [integer, fraction = ""] = absolute.split(".");
  const paddedFraction = fraction.padEnd(3, "0");
  const nextInteger = `${integer}${paddedFraction.slice(0, 3)}`
    .replace(/^0+(?=\d)/, "") || "0";
  const nextFraction = paddedFraction.slice(3).replace(/0+$/, "");
  const shifted = nextFraction ? `${nextInteger}.${nextFraction}` : nextInteger;
  return negative && shifted !== "0" ? `-${shifted}` : shifted;
}
