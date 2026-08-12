import type {
  OnboardingImportEntity,
  OnboardingImportEntityType,
  OnboardingImportRun,
  OnboardingImportStatus,
  OnboardingStatusResponse,
  OnboardingStepStatus,
} from "@/lib/api";

export const GENERIC_IMPORT_COLUMNS = [
  { value: "category", label: "Category" },
  { value: "product", label: "Product name" },
  { value: "description", label: "Description" },
  { value: "variant", label: "Variant / size" },
  { value: "sku", label: "SKU" },
  { value: "price", label: "Price" },
  { value: "location", label: "Location" },
  { value: "available", label: "Available" },
  { value: "name", label: "Inventory item name" },
  { value: "unit", label: "Unit" },
  { value: "opening quantity", label: "Opening quantity" },
  { value: "unit cost kzt", label: "Unit cost (KZT)" },
] as const;

const GENERIC_IMPORT_PROFILES = [
  ["category", "product", "price"],
  ["name", "unit"],
] as const;

export const IMPORT_ENTITY_LABELS: Record<OnboardingImportEntityType, string> = {
  CATEGORY: "Category",
  INVENTORY_ITEM: "Inventory item",
  PRODUCT: "Product",
  VARIANT: "Variant",
  RECIPE: "Recipe",
  MODIFIER_GROUP: "Modifier group",
  MODIFIER_OPTION: "Modifier option",
  LOCATION_PRICE: "Location price",
  OPENING_BALANCE: "Opening balance",
};

export const IMPORT_STATUS_LABELS: Record<OnboardingImportStatus, string> = {
  UPLOADED: "Uploaded",
  PARSING: "Parsing",
  NEEDS_REVIEW: "Needs review",
  READY: "Ready to apply",
  APPLYING: "Applying",
  APPLIED: "Applied",
  FAILED: "Failed",
  CANCELLED: "Cancelled",
};

export const STEP_STATUS_LABELS: Record<OnboardingStepStatus, string> = {
  COMPLETE: "Complete",
  NEEDS_ATTENTION: "Needs attention",
  OPTIONAL: "Optional",
  MISSING: "Not set up",
};

export function initialGenericImportMapping(columns: string[]) {
  const supported = new Set<string>(GENERIC_IMPORT_COLUMNS.map((column) => column.value));
  return Object.fromEntries(
    [...new Set(columns)].filter((column) => supported.has(column)).map((column) => [column, column]),
  );
}

export function genericImportMappingError(mapping: Record<string, string>) {
  const supported = new Set<string>(GENERIC_IMPORT_COLUMNS.map((column) => column.value));
  const targets = Object.values(mapping).filter(Boolean);
  const unsupported = targets.filter((target) => !supported.has(target));
  if (unsupported.length > 0) return `Unsupported Beanly fields: ${unsupported.join(", ")}.`;
  if (new Set(targets).size !== targets.length) {
    return "Each Beanly field can be mapped from only one source column.";
  }
  if (!GENERIC_IMPORT_PROFILES.some((profile) => profile.every((field) => targets.includes(field)))) {
    return "Map either Menu (category, product, price) or Inventory (name, unit) required fields.";
  }
  return null;
}

export type SetupProgressKey = "workspace" | "menu" | "inventory" | "prices" | "fiscal" | "pos";

export function resolveSetupStepStatus(
  key: SetupProgressKey,
  status: OnboardingStatusResponse,
): OnboardingStepStatus {
  if (key === "workspace") {
    const business = ["workspace", "location", "warehouse", "register"].map(
      (step) => status.steps[step]?.status ?? "MISSING",
    );
    if (business.includes("MISSING")) return "MISSING";
    if (business.includes("NEEDS_ATTENTION")) return "NEEDS_ATTENTION";
    if (business.includes("OPTIONAL")) return "OPTIONAL";
    return "COMPLETE";
  }
  if (key === "prices") return status.steps.prices?.status ?? status.steps.menu?.status ?? "MISSING";
  if (key === "pos") return status.pos_ready ? "COMPLETE" : "NEEDS_ATTENTION";
  return status.steps[key]?.status ?? "MISSING";
}

export function entityDisplayName(entity: OnboardingImportEntity) {
  for (const key of ["name", "product_name", "variant_name", "inventory_item_name", "category_name"]) {
    const value = entity.payload[key];
    if (typeof value === "string" && value.trim()) return value;
  }
  return entity.source_key;
}

export function entityPayloadSummary(entity: OnboardingImportEntity) {
  const ignored = new Set(["name", "product_name", "variant_name", "inventory_item_name", "category_name"]);
  return Object.entries(entity.payload)
    .filter(([key, value]) => !ignored.has(key) && (typeof value === "string" || typeof value === "number" || typeof value === "boolean"))
    .slice(0, 3)
    .map(([key, value]) => `${key.replaceAll("_", " ")}: ${String(value)}`)
    .join(" · ");
}

export function entityCounts(run: OnboardingImportRun) {
  return run.entities.reduce<Partial<Record<OnboardingImportEntityType, number>>>((counts, entity) => {
    counts[entity.entity_type] = (counts[entity.entity_type] ?? 0) + 1;
    return counts;
  }, {});
}

export function runNeedsInventoryWrite(run: OnboardingImportRun) {
  return run.entities.some((entity) =>
    entity.resolution !== "SKIP" && ["INVENTORY_ITEM", "RECIPE", "OPENING_BALANCE"].includes(entity.entity_type),
  );
}

export function readyProductIds(run: OnboardingImportRun) {
  return run.entities
    .filter((entity) => entity.entity_type === "PRODUCT" && entity.resolution !== "SKIP" && entity.target_id)
    .map((entity) => entity.target_id as string);
}

export type ImportProductReadiness = {
  productId: string;
  productName: string;
  ready: boolean;
  reasons: string[];
};

export function importProductReadiness(
  run: OnboardingImportRun,
  starterRecipesReviewed = false,
): ImportProductReadiness[] {
  const entities = run.entities.filter((entity) => entity.resolution !== "SKIP");
  const variants = entities.filter((entity) => entity.entity_type === "VARIANT" && entity.target_id);
  const locationPrices = entities.filter((entity) => entity.entity_type === "LOCATION_PRICE");
  const recipes = entities.filter((entity) => entity.entity_type === "RECIPE");

  return entities
    .filter((entity) => entity.entity_type === "PRODUCT" && entity.target_id)
    .map((product) => {
      const productVariants = variants.filter((variant) => variant.payload.product_key === product.source_key);
      const reasons: string[] = [];
      if (productVariants.length === 0) reasons.push("VARIANT_REQUIRED");
      if (productVariants.some((variant) => {
        const locationPrice = locationPrices.find((price) => price.payload.variant_key === variant.source_key);
        return !positiveMinor(locationPrice?.payload.price_minor ?? variant.payload.price_minor);
      })) reasons.push("PRICE_REQUIRED");
      const productRecipes = recipes.filter((recipe) =>
        productVariants.some((variant) => recipe.payload.variant_key === variant.source_key),
      );
      if (productRecipes.some((recipe) => recipeComponents(recipe).length === 0)) {
        reasons.push("VALID_RECIPE_REQUIRED");
      }
      if (!starterRecipesReviewed && productRecipes.some((recipe) =>
        recipe.warning_codes.includes("DRAFT_RECIPE_REVIEW_REQUIRED"),
      )) reasons.push("STARTER_RECIPE_REVIEW_REQUIRED");
      return {
        productId: product.target_id as string,
        productName: entityDisplayName(product),
        ready: reasons.length === 0,
        reasons,
      };
    });
}

export function recipeComponents(entity: OnboardingImportEntity) {
  const components = entity.payload.components;
  if (!Array.isArray(components)) return [];
  return components.flatMap((component) => {
    if (!component || typeof component !== "object") return [];
    const value = component as Record<string, unknown>;
    const inventoryItemKey = String(value.inventory_item_key ?? "").trim();
    const quantity = String(value.quantity ?? "").trim();
    const unit = String(value.unit ?? "").trim();
    return inventoryItemKey && quantity && unit ? [{ inventoryItemKey, quantity, unit }] : [];
  });
}

export function readinessReasonLabel(reason: string) {
  return ({
    VARIANT_REQUIRED: "Variant required",
    PRICE_REQUIRED: "Positive price required",
    VALID_RECIPE_REQUIRED: "Valid recipe required",
    STARTER_RECIPE_REVIEW_REQUIRED: "Starter recipe review required",
  } as Record<string, string>)[reason] ?? reason.replaceAll("_", " ").toLowerCase();
}

function positiveMinor(value: unknown) {
  try {
    return BigInt(String(value)) > BigInt(0);
  } catch {
    return false;
  }
}

export function formatBytes(bytes: number) {
  if (bytes < 1024 * 1024) return `${Math.ceil(bytes / 1024)} KB`;
  return `${Math.round(bytes / (1024 * 1024))} MB`;
}
