import assert from "node:assert/strict";
import test from "node:test";

import { priceOfflineOrder } from "./offline/pricing.ts";

test("offline combo keeps modifier upcharge", () => {
  const order = basket([item("coffee", "coffee-product", "coffee", "1800", "300"), item("croissant", "croissant-product", "bakery", "1500")]);
  const result = priceOfflineOrder(order, [promotion({ kind: "FIXED_PRICE", scope: "COMBO", fixed_price_minor: "2500", targets: [target("COMBO_COMPONENT", "PRODUCT", "coffee-product"), target("COMBO_COMPONENT", "PRODUCT", "croissant-product")] })], [], "Asia/Almaty");
  assert.equal(result.subtotal_minor, "3600");
  assert.equal(result.discount_total_minor, "800");
  assert.equal(result.total_minor, "2800");
});

test("offline happy hour uses half-open location time", () => {
  const promo = promotion({ percent_rate: "20.0000", schedules: [{ weekday: 0, start_local_time: "15:00:00", end_local_time: "17:00:00" }] });
  const at = (time) => priceOfflineOrder(basket([item("coffee", "coffee-product", "coffee", "1800")]), [promo], [], "Asia/Almaty", new Date(time)).discount_total_minor;
  assert.equal(at("2026-08-10T09:59:00Z"), "0");
  assert.equal(at("2026-08-10T10:00:00Z"), "360");
  assert.equal(at("2026-08-10T11:59:00Z"), "360");
  assert.equal(at("2026-08-10T12:00:00Z"), "0");
});

test("offline BOGO gives exactly one of three units free", () => {
  const order = basket([item("coffee", "coffee-product", "coffee", "1000", "0", 3)]);
  const result = priceOfflineOrder(order, [promotion({ kind: "BOGO", targets: [target("BUY", "PRODUCT", "coffee-product", 2), target("GET", "PRODUCT", "coffee-product")] })], [], "Asia/Almaty");
  assert.equal(result.discount_total_minor, "1000");
  assert.equal(result.total_minor, "2000");
});

test("offline stackable item and order percentages apply sequentially", () => {
  const order = basket([item("coffee", "coffee-product", "coffee", "1000")]);
  const itemPromo = promotion({ percent_rate: "20.0000", stacking: "STACKABLE" });
  const orderPromo = promotion({ promotion_id: "order-promo", percent_rate: "10.0000", scope: "ORDER", stacking: "STACKABLE", targets: [target("ELIGIBLE", "ALL", null)] });
  const result = priceOfflineOrder(order, [itemPromo, orderPromo], [], "Asia/Almaty");
  assert.equal(result.total_minor, "720");
});

function basket(items) { return { updated_at: "2026-08-10T09:30:00Z", items }; }
function item(id, product_id, category_id, base, modifier = "0", quantity = 1) { const unit = String(BigInt(base) + BigInt(modifier)); return { id, product_id, product_variant_id: `${product_id}-variant`, category_id, quantity, base_price_minor: base, modifier_price_minor: modifier, unit_price_minor: unit, line_total_minor: String(BigInt(unit) * BigInt(quantity)), discount_amount_minor: "0", net_line_total_minor: String(BigInt(unit) * BigInt(quantity)) }; }
function target(role, target_type, target_id, quantity = 1) { return { role, target_type, target_id, quantity, sort_order: 0 }; }
function promotion(overrides = {}) { return { promotion_id: "promo", name: "Promotion", application_mode: "AUTOMATIC", kind: "PERCENT", scope: "ITEM", percent_rate: "10.0000", amount_minor: null, fixed_price_minor: null, priority: 0, stacking: "EXCLUSIVE", include_modifier_price: false, minimum_subtotal_minor: null, maximum_discount_minor: null, valid_from: null, valid_to: null, schedules: [], targets: [target("ELIGIBLE", "ALL", null)], ...overrides }; }
