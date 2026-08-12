import assert from "node:assert/strict";
import test from "node:test";

import {
  genericImportMappingError,
  initialGenericImportMapping,
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
