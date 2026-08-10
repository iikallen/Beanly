export function formatAnalyticsInteger(value: string | number) {
  const integer = typeof value === "number" ? BigInt(value) : parseInteger(value);
  return integer === null ? "—" : new Intl.NumberFormat().format(integer);
}

export function formatAnalyticsDecimal(value: string | null, maximumFractionDigits = 2) {
  if (value === null) return "—";
  const match = value.trim().match(/^([+-]?)(\d+)(?:\.(\d+))?$/);
  if (!match) return "—";
  const fraction = (match[3] ?? "").slice(0, maximumFractionDigits).replace(/0+$/, "");
  return `${match[1] === "-" ? "-" : ""}${new Intl.NumberFormat().format(BigInt(match[2]))}${fraction ? `.${fraction}` : ""}`;
}

export function compareAnalyticsDecimal(left: string | null, right: string | null) {
  if (left === right) return 0;
  if (left === null) return -1;
  if (right === null) return 1;
  const normalizedLeft = comparableDecimal(left);
  const normalizedRight = comparableDecimal(right);
  if (!normalizedLeft || !normalizedRight) return left.localeCompare(right);
  const scale = Math.max(normalizedLeft.scale, normalizedRight.scale);
  const leftValue = normalizedLeft.value * BigInt(10) ** BigInt(scale - normalizedLeft.scale);
  const rightValue = normalizedRight.value * BigInt(10) ** BigInt(scale - normalizedRight.scale);
  return leftValue < rightValue ? -1 : leftValue > rightValue ? 1 : 0;
}

export function sumAnalyticsDecimals(values: string[]) {
  const parsed = values.map(comparableDecimal);
  if (parsed.some((value) => value === null)) return "0";
  const decimals = parsed.filter((value): value is NonNullable<typeof value> => value !== null);
  const scale = Math.max(0, ...decimals.map((value) => value.scale));
  const total = decimals.reduce((sum, value) => sum + value.value * BigInt(10) ** BigInt(scale - value.scale), BigInt(0));
  const negative = total < BigInt(0);
  const absolute = negative ? -total : total;
  const digits = String(absolute).padStart(scale + 1, "0");
  const whole = scale ? digits.slice(0, -scale) : digits;
  const fraction = scale ? digits.slice(-scale).replace(/0+$/, "") : "";
  return `${negative ? "-" : ""}${whole}${fraction ? `.${fraction}` : ""}`;
}

function parseInteger(value: string) {
  return /^-?\d+$/.test(value.trim()) ? BigInt(value.trim()) : null;
}

function comparableDecimal(value: string) {
  const match = value.trim().match(/^([+-]?)(\d+)(?:\.(\d+))?$/);
  if (!match) return null;
  const fraction = match[3] ?? "";
  const absolute = BigInt(`${match[2]}${fraction}`);
  return { value: match[1] === "-" ? -absolute : absolute, scale: fraction.length };
}
