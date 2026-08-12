import assert from "node:assert/strict";
import test from "node:test";

import {
  genericImportMappingError,
  importProductReadiness,
  initialGenericImportMapping,
  recipeComponents,
  readyProductIds,
  resolveSetupStepStatus,
  runNeedsInventoryWrite,
} from "./onboarding.ts";

function runWith(entities) {
  return { entities };
}

test("activation uses only applied product targets that were not skipped", () => {
  const run = runWith([
    { entity_type: "PRODUCT", resolution: "CREATE", target_id: "product-a" },
    { entity_type: "PRODUCT", resolution: "SKIP", target_id: "product-b" },
    { entity_type: "PRODUCT", resolution: "CREATE", target_id: null },
    { entity_type: "VARIANT", resolution: "CREATE", target_id: "variant-a" },
  ]);

  assert.deepEqual(readyProductIds(run), ["product-a"]);
});

test("inventory-bearing drafts require inventory write access", () => {
  assert.equal(runNeedsInventoryWrite(runWith([
    { entity_type: "PRODUCT", resolution: "CREATE" },
    { entity_type: "RECIPE", resolution: "CREATE" },
  ])), true);
  assert.equal(runNeedsInventoryWrite(runWith([
    { entity_type: "OPENING_BALANCE", resolution: "SKIP" },
    { entity_type: "PRODUCT", resolution: "CREATE" },
  ])), false);
});

test("generic import mapping follows the backend field contract", () => {
  assert.deepEqual(initialGenericImportMapping([
    "category", "product", "price", "inventory item", "category",
  ]), { category: "category", product: "product", price: "price" });
  assert.equal(genericImportMappingError({ group: "group" }), "Unsupported Beanly fields: group.");
  assert.equal(
    genericImportMappingError({ a: "category", b: "product" }),
    "Map either Menu (category, product, price) or Inventory (name, unit) required fields.",
  );
  assert.equal(genericImportMappingError({ a: "category", b: "product", c: "price" }), null);
  assert.equal(genericImportMappingError({ a: "name", b: "unit" }), null);
});

test("setup progress uses readiness statuses, independently of import READY", () => {
  const status = {
    steps: {
      workspace: { status: "COMPLETE" },
      location: { status: "COMPLETE" },
      warehouse: { status: "MISSING" },
      register: { status: "COMPLETE" },
      menu: { status: "NEEDS_ATTENTION" },
      inventory: { status: "OPTIONAL" },
      fiscal: { status: "OPTIONAL" },
    },
    pos_ready: false,
  };
  assert.equal(resolveSetupStepStatus("workspace", status), "MISSING");
  assert.equal(resolveSetupStepStatus("prices", status), "NEEDS_ATTENTION");
  assert.equal(resolveSetupStepStatus("inventory", status), "OPTIONAL");
  assert.equal(resolveSetupStepStatus("pos", status), "NEEDS_ATTENTION");
});

test("recipe review exposes every component and readiness is deterministic", () => {
  const recipe = {
    entity_type: "RECIPE",
    resolution: "CREATE",
    warning_codes: ["DRAFT_RECIPE_REVIEW_REQUIRED"],
    payload: {
      variant_key: "variant:latte:350",
      components: [
        { inventory_item_key: "inventory:coffee", quantity: "18", unit: "g" },
        { inventory_item_key: "inventory:milk", quantity: "180", unit: "ml" },
      ],
    },
  };
  const run = runWith([
    { entity_type: "PRODUCT", source_key: "product:latte", target_id: "product-a", resolution: "CREATE", payload: { name: "Latte" } },
    { entity_type: "VARIANT", source_key: "variant:latte:350", target_id: "variant-a", resolution: "CREATE", payload: { product_key: "product:latte", price_minor: "180000" } },
    recipe,
  ]);

  assert.deepEqual(recipeComponents(recipe), [
    { inventoryItemKey: "inventory:coffee", quantity: "18", unit: "g" },
    { inventoryItemKey: "inventory:milk", quantity: "180", unit: "ml" },
  ]);
  assert.deepEqual(importProductReadiness(run)[0].reasons, ["STARTER_RECIPE_REVIEW_REQUIRED"]);
  assert.equal(importProductReadiness(run, true)[0].ready, true);
});

test("activation pre-check reports missing variants, prices, and recipe components", () => {
  const run = runWith([
    { entity_type: "PRODUCT", source_key: "product:empty", target_id: "product-empty", resolution: "CREATE", payload: { name: "Empty" } },
    { entity_type: "PRODUCT", source_key: "product:latte", target_id: "product-latte", resolution: "CREATE", payload: { name: "Latte" } },
    { entity_type: "VARIANT", source_key: "variant:latte", target_id: "variant-latte", resolution: "CREATE", payload: { product_key: "product:latte", price_minor: "0" } },
    { entity_type: "RECIPE", source_key: "recipe:latte", target_id: "recipe-latte", resolution: "CREATE", warning_codes: [], payload: { variant_key: "variant:latte", components: [] } },
  ]);

  const readiness = importProductReadiness(run, true);
  assert.deepEqual(readiness.find((item) => item.productId === "product-empty").reasons, ["VARIANT_REQUIRED"]);
  assert.deepEqual(readiness.find((item) => item.productId === "product-latte").reasons, ["PRICE_REQUIRED", "VALID_RECIPE_REQUIRED"]);
});
