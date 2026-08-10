import assert from "node:assert/strict";
import test from "node:test";

import { financeApiRange, formatFinanceMinor, formatFinanceMoney, toMinorUnits, toSignedMinorUnits } from "./finance.ts";

test("keeps BIGINT minor requests exact above Number.MAX_SAFE_INTEGER", () => {
  assert.equal(toMinorUnits("900719925474099.91"), "90071992547409991");
  assert.equal(toSignedMinorUnits("-900719925474099.91"), "-90071992547409991");
  assert.equal(toMinorUnits("-1"), null);
  assert.match(formatFinanceMinor("90071992547409991", "USD"), /900.*719.*925.*474.*099\.91/);
});

test("rounds six-decimal ledger amounts only for display", () => {
  assert.equal(formatFinanceMoney("343.824731", "USD"), "343.82 $");
  assert.equal(formatFinanceMoney("343.824731", "KZT"), "344 ₸");
});

test("uses an exclusive next-day upper bound for inclusive UI dates", () => {
  const range = financeApiRange("2026-08-01", "2026-08-31");
  assert.equal(new Date(range.dateTo).getTime() - new Date(range.dateFrom).getTime(), 31 * 24 * 60 * 60 * 1000);
});
