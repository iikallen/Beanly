import assert from "node:assert/strict";
import test from "node:test";

import { compareAnalyticsDecimal, formatAnalyticsDecimal, sumAnalyticsDecimals } from "./analytics-decimal.ts";

test("keeps analytics decimal strings exact above Number.MAX_SAFE_INTEGER", () => {
  assert.match(formatAnalyticsDecimal("90071992547409912345.678900", 6), /90.*071.*992.*547.*409.*912.*345\.6789/);
  assert.equal(sumAnalyticsDecimals(["90071992547409912345.1", "0.2"]), "90071992547409912345.3");
  assert.equal(compareAnalyticsDecimal("90071992547409912345.3", "90071992547409912345.2"), 1);
});
