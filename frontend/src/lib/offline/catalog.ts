import type { MenuProduct, MenuReadModel, ProductVariant } from "@/lib/api";

import type { OfflineOrderItem } from "./types";

const PRIVATE_KEYS = new Set(["components", "recipe", "inventory_item_id", "base_unit", "quantity_per_unit"]);

export function assertPublicCatalog(value: unknown): MenuReadModel {
  if (!value || typeof value !== "object") throw new Error("Offline catalog payload is invalid");
  rejectPrivateFields(value);
  const catalog = value as MenuReadModel;
  if (typeof catalog.location_id !== "string" || !Array.isArray(catalog.categories)) throw new Error("Offline catalog payload is invalid");
  for (const category of catalog.categories) {
    if (typeof category.id !== "string" || !Array.isArray(category.products)) throw new Error("Offline catalog category is invalid");
    for (const product of category.products) {
      if (!Array.isArray(product.variants)) throw new Error("Offline catalog product is invalid");
      for (const variant of product.variants) {
        assertMoney(variant.effective_price_minor);
        for (const group of variant.modifier_groups ?? []) {
          for (const option of group.options) assertMoney(option.effective_price_delta_minor);
        }
      }
    }
  }
  return catalog;
}

export function catalogSelectionIsValid(product: MenuProduct, variant: ProductVariant, selectedOptionIds: string[]) {
  const selected = new Set(selectedOptionIds);
  const groups = (variant.modifier_groups ?? []).filter((group) => group.is_active);
  const available = new Set(groups.flatMap((group) => group.options
    .filter((option) => option.is_available)
    .map((option) => option.id)));
  return product.status === "ACTIVE"
    && product.is_available !== false
    && product.is_visible !== false
    && variant.status === "ACTIVE"
    && product.variants.some((candidate) => candidate.id === variant.id)
    && selectedOptionIds.length === selected.size
    && selectedOptionIds.every((id) => available.has(id))
    && groups.every((group) => {
      const count = group.options.filter((option) => option.is_available && selected.has(option.id)).length;
      return count >= group.min_selections && count <= group.max_selections;
    });
}

export function buildLocalItem(
  product: MenuProduct,
  variant: ProductVariant,
  selectedOptionIds: string[],
  clientItemId: string,
  quantity = 1,
  note: string | null = null,
): OfflineOrderItem {
  if (!catalogSelectionIsValid(product, variant, selectedOptionIds)) throw new Error("Catalog selection is unavailable");
  const selected = new Set(selectedOptionIds);
  const modifiers = (variant.modifier_groups ?? []).flatMap((group) =>
    group.options.filter((option) => selected.has(option.id)).map((option) => ({
      modifier_group_id: group.id,
      modifier_group_name: group.name,
      modifier_option_id: option.id,
      modifier_option_name: option.name,
      price_delta_minor: option.effective_price_delta_minor,
    })),
  );
  const modifierPrice = modifiers.reduce((sum, modifier) => sum + BigInt(modifier.price_delta_minor), BigInt(0));
  const unitPrice = BigInt(variant.effective_price_minor) + modifierPrice;
  return {
    id: clientItemId,
    client_item_id: clientItemId,
    product_id: product.id,
    category_id: product.category_id,
    product_variant_id: variant.id,
    product_name: product.name,
    variant_name: variant.name,
    selected_option_ids: selectedOptionIds,
    quantity,
    base_price_minor: variant.effective_price_minor,
    modifier_price_minor: String(modifierPrice),
    unit_price_minor: String(unitPrice),
    line_total_minor: String(unitPrice * BigInt(quantity)),
    discount_amount_minor: "0",
    net_line_total_minor: String(unitPrice * BigInt(quantity)),
    note,
    modifiers,
  };
}

function assertMoney(value: unknown) {
  if (typeof value !== "string" || !/^\d{1,19}$/.test(value)) throw new Error("Offline catalog money must use minor-unit strings");
}

function rejectPrivateFields(value: unknown) {
  if (!value || typeof value !== "object") return;
  if (Array.isArray(value)) {
    for (const item of value) rejectPrivateFields(item);
    return;
  }
  for (const [key, child] of Object.entries(value)) {
    if (PRIVATE_KEYS.has(key)) throw new Error("Private catalog fields cannot be stored on the POS device");
    rejectPrivateFields(child);
  }
}
