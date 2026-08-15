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

test("KDS ticket card renders authoritative source, fulfillment, and due time to minute precision", async () => {
  const { readFile } = await import("node:fs/promises");
  const page = await readFile(new URL("../app/app/kitchen/page.tsx", import.meta.url), "utf8");
  assert.match(page, /ticket\.order_source/);
  assert.match(page, /ticket\.fulfillment_type/);
  assert.match(page, /ticket\.promised_at/);
  assert.match(page, /ticket\.guest_instructions/);
  assert.match(page, /hour: "2-digit", minute: "2-digit"/);
});
