export function currentMonthRange(now = new Date()) {
  const year = now.getFullYear();
  const month = now.getMonth();
  return {
    dateFrom: localDate(new Date(year, month, 1)),
    dateTo: localDate(new Date(year, month + 1, 0)),
  };
}

export function financeApiRange(dateFrom: string, dateTo: string) {
  const exclusiveTo = new Date(`${dateTo}T00:00:00`);
  exclusiveTo.setDate(exclusiveTo.getDate() + 1);
  return {
    dateFrom: new Date(`${dateFrom}T00:00:00`).toISOString(),
    dateTo: exclusiveTo.toISOString(),
  };
}

export function formatFinanceMoney(amount: string | number | null | undefined, currency = "KZT") {
  const scale = currency === "KZT" ? 0 : 2;
  return formatScaled(decimalToScaled(String(amount ?? 0), scale), scale, currency);
}

export function formatFinanceOutflow(amount: string | number | null | undefined, currency = "KZT") {
  const value = String(amount ?? 0);
  return formatFinanceMoney(/^0+(?:\.0+)?$/.test(value) || value.startsWith("-") ? value : `-${value}`, currency);
}

export function formatFinanceMinor(amount: string | number | null | undefined, currency = "KZT") {
  const scale = currency === "KZT" ? 0 : 2;
  const minor = integer(String(amount ?? 0));
  if (minor === null) return formatScaled(BigInt(0), scale, currency);
  if (scale === 2) return formatScaled(minor, scale, currency);
  const negative = minor < BigInt(0);
  const absolute = negative ? -minor : minor;
  const rounded = absolute / BigInt(100) + (absolute % BigInt(100) >= BigInt(50) ? BigInt(1) : BigInt(0));
  return formatScaled(negative ? -rounded : rounded, 0, currency);
}

export function formatFinanceMinorOutflow(amount: string | number | null | undefined, currency = "KZT") {
  const value = String(amount ?? 0);
  return formatFinanceMinor(/^0+$/.test(value) || value.startsWith("-") ? value : `-${value}`, currency);
}

export function formatFinanceDate(value: string) {
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" }).format(new Date(value));
}

export function toMinorUnits(value: string) {
  return scaledMinor(value, false);
}

export function toSignedMinorUnits(value: string) {
  return scaledMinor(value, true);
}

function scaledMinor(value: string, signed: boolean) {
  const match = value.replace(/\s/g, "").match(signed ? /^([+-]?)(\d+)(?:[.,](\d{0,2}))?$/ : /^([+]?)(\d+)(?:[.,](\d{0,2}))?$/);
  if (!match) return null;
  const minor = BigInt(match[2]) * BigInt(100) + BigInt((match[3] ?? "").padEnd(2, "0") || "0");
  return String(match[1] === "-" ? -minor : minor);
}

function localDate(value: Date) {
  const offset = value.getTimezoneOffset() * 60_000;
  return new Date(value.getTime() - offset).toISOString().slice(0, 10);
}

function decimalToScaled(value: string, scale: number) {
  const match = value.trim().match(/^([+-]?)(\d+)(?:\.(\d+))?$/);
  if (!match) return BigInt(0);
  const factor = BigInt(10) ** BigInt(scale);
  const fraction = match[3] ?? "";
  const kept = fraction.slice(0, scale).padEnd(scale, "0");
  let result = BigInt(match[2]) * factor + BigInt(kept || "0");
  if ((fraction[scale] ?? "0") >= "5") result += BigInt(1);
  return match[1] === "-" ? -result : result;
}

function integer(value: string) {
  return /^-?\d+$/.test(value.trim()) ? BigInt(value.trim()) : null;
}

function formatScaled(value: bigint, scale: number, currency: string) {
  const negative = value < BigInt(0);
  const absolute = negative ? -value : value;
  const factor = BigInt(10) ** BigInt(scale);
  const whole = absolute / factor;
  const fraction = scale ? `.${String(absolute % factor).padStart(scale, "0")}` : "";
  const symbol = currency === "KZT" ? "₸" : currency === "USD" ? "$" : currency === "EUR" ? "€" : currency;
  return `${negative ? "-" : ""}${new Intl.NumberFormat().format(whole)}${fraction} ${symbol}`;
}
