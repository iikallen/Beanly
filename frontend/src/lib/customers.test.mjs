import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = (path) => readFileSync(new URL(path, import.meta.url), "utf8");

test("customer and loyalty data stay out of offline POS storage", () => {
  const offline = ["./offline/types.ts", "./offline/db.ts", "./offline/api.ts", "./offline/catalog.ts", "./offline/orders.ts"]
    .map(source).join("\n");
  assert.doesNotMatch(offline, /customer_id|customer_phone|customer_name|loyalty_redemption/);

  const pos = source("../app/app/pos/page.tsx");
  assert.match(pos, /!currentOrder\?\.server_order_id \|\| offline\.networkStatus !== "ONLINE" \|\| !canReadCustomers/);
  const clearCustomerState = pos.match(/function clearCustomerState\(\) \{([\s\S]*?)\r?\n    \}/)?.[1];
  assert.ok(clearCustomerState);
  for (const clear of [
    "setAttachedCustomer(null)", "setCustomerLoyalty(null)", "setCustomerResults([])", "setCustomerSearch(\"\")",
    "setLoyaltyPoints(\"\")", "setLoyaltyQuote(null)", "setNewCustomerPhone(\"\")", "setNewCustomerName(\"\")", "setShowCustomers(false)",
  ]) assert.match(clearCustomerState, new RegExp(clear.replace(/[()[\]]/g, "\\$&")));

  const api = source("./api.ts");
  const offlinePromotion = api.match(/export type OfflinePromotion = \{([\s\S]*?)\r?\n\};/)?.[1];
  assert.ok(offlinePromotion);
  assert.doesNotMatch(offlinePromotion, /audience_kind|customer_ids|tier_id/);
});

test("POS uses server reservation and explicit release endpoints", () => {
  const api = source("./api.ts");
  assert.match(api, /\/sales\/orders\/\$\{orderId\}\/loyalty\/redeem/);
  assert.match(api, /\/sales\/orders\/\$\{orderId\}\/loyalty\/redemption/);
  assert.match(api, /method: "DELETE"/);
});

test("first POS session pairs after privacy-preserving device not found", () => {
  const posSource = readFileSync(new URL("../app/app/pos/page.tsx", import.meta.url), "utf8");
  assert.match(posSource, /\[401, 404\]\.includes\(caught\.status\)/);
  assert.match(posSource, /await pairDevice\(/);
});
