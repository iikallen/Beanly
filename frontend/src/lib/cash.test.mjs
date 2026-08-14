import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { formatMenuPriceMinor, parseMenuPriceToMinor, priceMinorToInput } from "./menu.ts";

test("cash helpers preserve signed bigint money exactly", () => {
  assert.equal(parseMenuPriceToMinor("22 950.01"), "2295001");
  assert.equal(priceMinorToInput("-5050"), "-50.50");
  assert.equal(formatMenuPriceMinor("9223372036854775807", "KZT"), "92,233,720,368,547,758.07 ₸");
  assert.equal(formatMenuPriceMinor("-5000", "KZT"), "-50 ₸");
});

test("POS close is blind, synchronized, and never calls the legacy shift close", () => {
  const page = readFileSync(new URL("../app/app/pos/page.tsx", import.meta.url), "utf8");
  const drawer = readFileSync(new URL("../components/pos/cash-drawer.tsx", import.meta.url), "utf8");
  assert.doesNotMatch(page, /api\.closeRegisterShift/);
  assert.match(drawer, /pendingOperations === 0/);
  assert.match(drawer, /The expected amount stays hidden during a blind close/);
  assert.match(drawer, /summary\?\.expected_visible && canViewExpected/);
  assert.match(drawer, /Do not retry the Z-report/);
  assert.match(drawer, /api\.reconcileFiscalShift/);
  assert.doesNotMatch(drawer, /Number\(/);
});

test("cash reports enforce report and expected-value permissions", () => {
  const list = readFileSync(new URL("../app/app/reports/cash/page.tsx", import.meta.url), "utf8");
  const detail = readFileSync(new URL("../app/app/reports/cash/[drawerId]/page.tsx", import.meta.url), "utf8");
  assert.match(list, /permissions\.canReport/);
  assert.match(list, /permissions\.canViewExpected/);
  assert.match(detail, /report\.summary\.expected_visible/);
});
