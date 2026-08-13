import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { assertPublicCatalog, buildLocalItem } from "./offline/catalog.ts";
import { mergeExternalPaymentApproval, mergeSyncResult } from "./offline/reconcile.ts";

test("an open order keeps snapshot A pricing after catalog B arrives", () => {
  const productA = product("180000", "20000");
  const itemA = buildLocalItem(productA, productA.variants[0], ["oat"], "item-a", 2);
  const productB = product("200000", "30000");
  const itemB = buildLocalItem(productB, productB.variants[0], ["oat"], "item-b", 1);

  assert.equal(itemA.unit_price_minor, "200000");
  assert.equal(itemA.line_total_minor, "400000");
  assert.equal(itemA.discount_amount_minor, "0");
  assert.equal(itemA.net_line_total_minor, "400000");
  assert.equal(itemB.unit_price_minor, "230000");
  assert.deepEqual(itemA.selected_option_ids, ["oat"]);
});

test("catalog boundary rejects invalid money and private recipe fields", () => {
  const valid = { location_id: "location", categories: [{ id: "hot", products: [product("180000", "0")] }] };
  assert.equal(assertPublicCatalog(valid), valid);

  assert.throws(
    () => assertPublicCatalog({ ...valid, categories: [{ id: "hot", products: [product("18.00", "0")] }] }),
    /minor-unit strings/,
  );
  assert.throws(
    () => assertPublicCatalog({ ...valid, recipe: { components: [{ inventory_item_id: "secret" }] } }),
    /Private catalog fields/,
  );
});

test("service worker excludes every API request and waits for explicit update approval", async () => {
  const worker = await readFile(new URL("../../public/sw.js", import.meta.url), "utf8");
  assert.match(worker, /url\.pathname\.startsWith\("\/api\/"\)/);
  assert.match(worker, /event\.data\?\.type === "SKIP_WAITING"/);
  const installHandler = worker.slice(worker.indexOf('addEventListener("install"'), worker.indexOf('addEventListener("activate"'));
  assert.doesNotMatch(installHandler, /skipWaiting/);
});

test("a stale conflict cannot freeze a newer local revision", () => {
  const order = { client_order_id: "order", revision: 3, last_synced_revision: 1, status: "OPEN", sync_error: null };
  const stale = mergeSyncResult(order, { client_order_id: "order", revision: 2, status: "CONFLICT", code: "ORDER_CHANGED_ON_SERVER" });
  assert.equal(stale.status, "OPEN");
  assert.equal(stale.sync_error, null);

  const current = mergeSyncResult(order, { client_order_id: "order", revision: 3, status: "CONFLICT", code: "ORDER_CHANGED_ON_SERVER" });
  assert.equal(current.status, "CONFLICT");
});

test("approved terminal attempt closes the local projection without queuing another payment", () => {
  const order = {
    client_order_id: "local-order",
    server_order_id: "server-order",
    revision: 3,
    last_synced_revision: 3,
    status: "SYNCED_OPEN",
    total_minor: "280000",
    currency_code: "KZT",
    payment: null,
    updated_at: "2026-08-11T10:00:00Z",
    sync_error: null,
  };
  const next = mergeExternalPaymentApproval(order, {
    status: "APPROVED",
    payment_id: "payment",
    order_id: "server-order",
    amount_minor: "280000",
    currency_code: "KZT",
    client_attempt_id: "attempt-client",
    provider_reference: "kaspi-reference",
    provider_code: "kaspi_smart_pos",
    approved_at: "2026-08-11T10:01:00Z",
    created_at: "2026-08-11T10:00:30Z",
  });
  assert.equal(next.status, "SYNCED_PAID");
  assert.equal(next.last_synced_revision, next.revision);
  assert.equal(next.payment.client_payment_id, "attempt-client");
  assert.equal(next.payment.lines[0].reference, "kaspi-reference");
});

function product(price, modifierPrice) {
  return {
    id: "coffee",
    name: "Cappuccino",
    status: "ACTIVE",
    is_available: true,
    is_visible: true,
    variants: [{
      id: "large",
      name: "Large",
      status: "ACTIVE",
      effective_price_minor: price,
      modifier_groups: [{
        id: "milk",
        name: "Milk",
        selection_type: "SINGLE",
        min_selections: 0,
        max_selections: 1,
        is_active: true,
        options: [{ id: "oat", name: "Oat", is_available: true, effective_price_delta_minor: modifierPrice }],
      }],
    }],
  };
}
