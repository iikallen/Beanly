import assert from "node:assert/strict";
import test from "node:test";

import { integrationJobLabel, integrationStatusLabel } from "./integrations.ts";

test("presents stable integration state and job labels", () => {
  assert.equal(integrationStatusLabel("DEGRADED"), "Needs attention");
  assert.equal(integrationStatusLabel("DEAD"), "Failed");
  assert.equal(integrationJobLabel("FISCALIZE_PAYMENT"), "Fiscalize payment");
});
