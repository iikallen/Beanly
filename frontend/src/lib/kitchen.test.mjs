import assert from "node:assert/strict";
import test from "node:test";

import { kitchenAging, kitchenProductionLabel, mergeKitchenTickets } from "./kitchen.mjs";

test("incremental kitchen polling replaces changed tickets without dropping others", () => {
  const first = { id: "a", fired_at: "2026-08-15T10:00:00Z", status: "QUEUED" };
  const second = { id: "b", fired_at: "2026-08-15T10:01:00Z", status: "QUEUED" };
  const changed = { ...second, status: "READY" };
  assert.deepEqual(mergeKitchenTickets([first, second], [changed]), [first, changed]);
  assert.deepEqual(mergeKitchenTickets([first], [changed], true), [changed]);
});

test("aging is based on fired time and uses half-open warning thresholds", () => {
  const fired = "2026-08-15T10:00:00Z";
  assert.equal(kitchenAging(fired, Date.parse("2026-08-15T10:04:59Z"), 300, 600).level, "normal");
  assert.equal(kitchenAging(fired, Date.parse("2026-08-15T10:05:00Z"), 300, 600).level, "warning");
  assert.equal(kitchenAging(fired, Date.parse("2026-08-15T10:10:00Z"), 300, 600).level, "late");
  assert.equal(kitchenProductionLabel("PREPARING"), "Paid · Preparing");
});
