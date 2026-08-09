import type { ProductStatus, ProductVariantStatus } from "@/lib/api";

const NON_NEGATIVE_DECIMAL = /^\d+(?:\.\d{1,6})?$/;

export function isPositiveMenuDecimal(value: string) {
  return NON_NEGATIVE_DECIMAL.test(value.trim()) && Number(value) > 0;
}

export function parseMenuPriceToMinor(value: string) {
  const trimmed = value.trim().replaceAll(" ", "").replace(",", ".");
  if (!/^\d+(?:\.\d{0,2})?$/.test(trimmed)) return null;
  const [whole, fraction = ""] = trimmed.split(".");
  const minor = BigInt(whole) * BigInt(100) + BigInt((fraction + "00").slice(0, 2));
  return minor <= BigInt("9223372036854775807") ? String(minor) : null;
}

export function priceMinorToInput(value: string) {
  const minor = BigInt(value);
  const hundred = BigInt(100);
  const whole = minor / hundred;
  const fraction = minor % hundred;
  return fraction === BigInt(0) ? String(whole) : `${whole}.${String(fraction).padStart(2, "0")}`;
}

export function formatMenuPriceMinor(value: string, currency: string) {
  const amount = priceMinorToInput(value);
  return formatMenuMoney(amount, currency, 2);
}

export function formatMenuMoney(
  value: string | null,
  currency: string,
  maximumFractionDigits = 2,
) {
  if (value === null) return "—";
  const formatted = formatDecimalExact(value, maximumFractionDigits);
  if (formatted === null) return "—";
  return currency === "KZT" ? `${formatted} ₸` : `${formatted} ${currency}`;
}

export function formatMenuPercent(value: string | null) {
  if (value === null) return "—";
  const formatted = formatDecimalExact(value, 2);
  return formatted === null ? "—" : `${formatted}%`;
}

export function formatMenuStatus(value: ProductStatus | ProductVariantStatus) {
  return value.charAt(0) + value.slice(1).toLowerCase();
}

export function menuStatusClass(value: ProductStatus | ProductVariantStatus) {
  return `menu-status status-${value.toLowerCase()}`;
}

export function minimumMinor(values: string[]) {
  return values.reduce<string | null>(
    (smallest, value) => smallest === null || BigInt(value) < BigInt(smallest) ? value : smallest,
    null,
  );
}

export function minimumDecimal(values: string[]) {
  return values.reduce<string | null>((smallest, value) => {
    if (smallest === null) return value;
    return decimalComparable(value) < decimalComparable(smallest) ? value : smallest;
  }, null);
}

function decimalComparable(value: string) {
  const [whole, fraction = ""] = value.split(".");
  return BigInt(whole) * BigInt(1_000_000) + BigInt((fraction + "000000").slice(0, 6));
}

function formatDecimalExact(value: string, maximumFractionDigits: number) {
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(value.trim());
  if (!match) return null;
  const sign = match[1];
  const whole = match[2];
  const fraction = match[3] ?? "";
  const scale = BigInt(10) ** BigInt(maximumFractionDigits);
  const kept = (fraction + "0".repeat(maximumFractionDigits)).slice(0, maximumFractionDigits);
  let scaled = BigInt(whole) * scale + BigInt(kept || "0");
  if ((fraction[maximumFractionDigits] ?? "0") >= "5") scaled += BigInt(1);
  const roundedWhole = scaled / scale;
  const roundedFraction = maximumFractionDigits === 0
    ? ""
    : String(scaled % scale).padStart(maximumFractionDigits, "0").replace(/0+$/, "");
  const grouped = new Intl.NumberFormat("en", { maximumFractionDigits: 0 }).format(roundedWhole);
  const negative = sign && scaled !== BigInt(0) ? "-" : "";
  return `${negative}${grouped}${roundedFraction ? `.${roundedFraction}` : ""}`;
}
