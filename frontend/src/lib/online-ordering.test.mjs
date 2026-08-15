import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("public QR requests keep the station identity in both the rate-limit query and authoritative payload", async () => {
  const source = await readFile(new URL("./api.ts", import.meta.url), "utf8");
  const storefront = await readFile(new URL("../app/order/[slug]/public-order-client.tsx", import.meta.url), "utf8");
  for (const action of ["quote", "orders"]) {
    const request = source.slice(source.indexOf(`/${action}\${`), source.indexOf("),", source.indexOf(`/${action}\${`)));
    assert.match(request, /\?station=/);
    assert.match(request, /JSON\.stringify\(input\)/);
  }
  assert.match(storefront, /fulfillment_type: station \? "PICKUP"/);
});

test("public status uses the privacy-limited contract and does not persist order secrets", async () => {
  const api = await readFile(new URL("./api.ts", import.meta.url), "utf8");
  const storefront = await readFile(new URL("../app/order/[slug]/public-order-client.tsx", import.meta.url), "utf8");
  assert.match(api, /getPublicOnlineOrder:.*request<PublicOnlineOrder>/);
  assert.match(api, /submitPublicOrder:.*request<PublicOrderCreated>/);
  assert.doesNotMatch(storefront, /sessionStorage|localStorage/);
});

test("public modifiers use the reduced storefront contract", async () => {
  const api = await readFile(new URL("./api.ts", import.meta.url), "utf8");
  const contract = api.slice(api.indexOf("export type PublicModifierGroup"), api.indexOf("export type PublicOrderingMenu"));
  assert.match(contract, /price_delta_minor: string/);
  assert.doesNotMatch(contract, /organization_id|effective_price_delta_minor|is_active/);
});

test("POS import accepts only same-workspace online orders and preserves an existing projection", async () => {
  const source = await readFile(new URL("./offline/orders.ts", import.meta.url), "utf8");
  const importOrder = source.slice(source.indexOf("export async function importServerOrder"), source.indexOf("export async function markExternalPaymentApproved"));
  assert.match(importOrder, /source\.order_source === "POS"/);
  assert.match(importOrder, /source\.organization_id !== session\.organization_id/);
  assert.match(importOrder, /return existing \?\? order/);
});

test("manager close-today sends the explicit backend flag", async () => {
  const api = await readFile(new URL("./api.ts", import.meta.url), "utf8");
  const setup = await readFile(new URL("../app/app/online-orders/page.tsx", import.meta.url), "utf8");
  assert.match(api, /closed_today: closedToday/);
  assert.match(setup, /"Closed today", null, organization!\.id, accessToken!, true/);
});

test("staff order loads and POS imports are scoped against tenant switches", async () => {
  const hub = await readFile(new URL("../app/app/online-orders/page.tsx", import.meta.url), "utf8");
  const pos = await readFile(new URL("../app/app/pos/page.tsx", import.meta.url), "utf8");
  assert.match(hub, /activeScope\.current !== requestedScope \|\| loadRequest\.current !== requestId/);
  assert.match(hub, /activeScope\.current === actionScope/);
  assert.match(pos, /`\$\{organizationId\}:\$\{offlineSession\.id\}:\$\{orderId\}`/);
  assert.match(pos, /cancelled \? null : importServerOrder/);
});

test("sidebar polls a permission-gated workspace-scoped pending count", async () => {
  const sidebar = await readFile(new URL("../components/app-sidebar.tsx", import.meta.url), "utf8");
  assert.match(sidebar, /onlinePermissions\.canRead/);
  assert.match(sidebar, /listOnlineOrders\(\{ locationId: currentLocation\.id, status: "PENDING" \}, currentOrganization\.id, accessToken\)/);
  assert.match(sidebar, /if \(!cancelled\) setPendingOnlineOrders\(orders\.length\)/);
  assert.match(sidebar, /className="app-nav-badge"/);
});

test("manager pause controls cover reasons and every Stage 29 pause duration", async () => {
  const setup = await readFile(new URL("../app/app/online-orders/page.tsx", import.meta.url), "utf8");
  for (const value of ["Kitchen overloaded", "Closing soon", "Outage", "Pause 15 min", "Pause 30 min", "Until resumed", "Close today", "Resume"]) assert.match(setup, new RegExp(value));
  assert.match(setup, /pauseOnlineOrdering\(location!\.id, pauseReason, 15,/);
  assert.match(setup, /pauseOnlineOrdering\(location!\.id, pauseReason, 30,/);
  assert.match(setup, /pauseOnlineOrdering\(location!\.id, pauseReason, null,/);
});

test("public pause and status copy stay guest-facing while AWAITING_PAYMENT remains authoritative", async () => {
  const storefront = await readFile(new URL("../app/order/[slug]/public-order-client.tsx", import.meta.url), "utf8");
  const status = await readFile(new URL("../app/order/status/[statusToken]/public-order-status.tsx", import.meta.url), "utf8");
  assert.match(storefront, /"Temporarily not accepting orders"/);
  assert.match(status, /\["Order received", "Accepted", "Payment required", "Preparing", "Ready", "Completed"\]/);
  assert.match(status, /AWAITING_PAYMENT: 2/);
  assert.doesNotMatch(status, /"ACCEPTED"/);
});

test("staff cards render channel-prefixed authoritative order numbers", async () => {
  const api = await readFile(new URL("./api.ts", import.meta.url), "utf8");
  const hub = await readFile(new URL("../app/app/online-orders/page.tsx", import.meta.url), "utf8");
  assert.match(api, /order_number: number/);
  assert.match(hub, /#\{order\.source === "QR" \? "Q" : "O"\}-\{order\.order_number\}/);
});

test("guest fulfillment uses frozen options and sends the same selection to quote and submit", async () => {
  const api = await readFile(new URL("./api.ts", import.meta.url), "utf8");
  const storefront = await readFile(new URL("../app/order/[slug]/public-order-client.tsx", import.meta.url), "utf8");
  assert.match(api, /getPublicFulfillmentOptions:.*request<OnlineFulfillmentOptions>/);
  assert.match(api, /quotePublicOrder:.*OnlineFulfillmentSelection/);
  assert.match(api, /submitPublicOrder:.*OnlineFulfillmentSelection/);
  assert.match(storefront, /Pickup[\s\S]*Delivery/);
  assert.match(storefront, /ASAP[\s\S]*Scheduled/);
  assert.match(storefront, /requested_at:.*requestedAt/);
});

test("delivery checkout renders only server quote money and requires zone and address", async () => {
  const storefront = await readFile(new URL("../app/order/[slug]/public-order-client.tsx", import.meta.url), "utf8");
  assert.match(storefront, /Delivery zone/);
  assert.match(storefront, /delivery_zone_id: delivery \? deliveryZoneId/);
  assert.match(storefront, /delivery_address: delivery \? deliveryAddress\.trim\(\)/);
  assert.match(storefront, /quote\.fulfillment_fee_minor/);
  assert.doesNotMatch(storefront, /zone\.delivery_fee_minor/);
});

test("scheduled checkout disables full slots and recovers from the frozen 409 code", async () => {
  const storefront = await readFile(new URL("../app/order/[slug]/public-order-client.tsx", import.meta.url), "utf8");
  assert.match(storefront, /disabled=\{slot\.remaining_capacity < 1\}/);
  assert.match(storefront, /ONLINE_FULFILLMENT_SLOT_UNAVAILABLE/);
  assert.match(storefront, /Choose another slot/);
  assert.match(storefront, /hour: "2-digit", minute: "2-digit"/);
});

test("staff fulfillment cards expose due context and all lifecycle actions", async () => {
  const hub = await readFile(new URL("../app/app/online-orders/page.tsx", import.meta.url), "utf8");
  const api = await readFile(new URL("./api.ts", import.meta.url), "utf8");
  assert.match(hub, /order\.fulfillment_type/);
  assert.match(hub, /dueLabel\(order\.promised_at, location\?\.timezone\)/);
  for (const action of ["Accept", "Reject", "Ready", "Complete", "Cancel"]) assert.match(hub, new RegExp(`\\b${action}\\b`));
  assert.match(api, /readyOnlineOrder:/);
  assert.match(api, /completeOnlineOrder:/);
});

test("guest status renders fulfillment details and trusts can_cancel", async () => {
  const status = await readFile(new URL("../app/order/status/[statusToken]/public-order-status.tsx", import.meta.url), "utf8");
  assert.match(status, /order\.order_number/);
  assert.match(status, /order\.promised_at/);
  assert.match(status, /order\.delivery_address/);
  assert.match(status, /order\.fulfillment_fee_minor/);
  assert.match(status, /order\.can_cancel &&/);
  assert.doesNotMatch(status, /order\.status === "PENDING" && <button/);
});
