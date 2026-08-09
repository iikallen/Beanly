"use client";

import { ArrowLeft, Check, CircleAlert, Plus, Search, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { useMenuPermissions } from "@/hooks/use-menu-permissions";
import {
  ApiError,
  api,
  type InventoryItemResponse,
  type InventoryUnitCode,
  type MenuProduct,
  type ProductVariant,
  type Recipe,
  type RecipeCost,
  type WarehouseResponse,
} from "@/lib/api";
import { formatMenuMoney, formatMenuPercent, formatMenuPriceMinor, isPositiveMenuDecimal } from "@/lib/menu";

type IngredientDraft = {
  clientId: string;
  inventoryItemId: string;
  itemName: string;
  baseUnit: InventoryUnitCode;
  quantity: string;
  unit: InventoryUnitCode;
};

export default function RecipeEditorPage() {
  const { productId, variantId } = useParams<{ productId: string; variantId: string }>();
  const { accessToken } = useAuth();
  const { currentOrganization, currentLocation } = useWorkspace();
  const { canReadRecipe, canWriteRecipe, loading: permissionsLoading } = useMenuPermissions();
  const [product, setProduct] = useState<MenuProduct | null>(null);
  const [variant, setVariant] = useState<ProductVariant | null>(null);
  const [recipe, setRecipe] = useState<Recipe | null>(null);
  const [ingredients, setIngredients] = useState<IngredientDraft[]>([]);
  const [inventoryItems, setInventoryItems] = useState<InventoryItemResponse[]>([]);
  const [warehouses, setWarehouses] = useState<WarehouseResponse[]>([]);
  const [warehouseId, setWarehouseId] = useState("");
  const [cost, setCost] = useState<RecipeCost | null>(null);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [costLoading, setCostLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const loadRecipe = useCallback(async () => {
    if (!accessToken || !currentOrganization || !currentLocation) return;
    setLoading(true);
    setError("");
    try {
      const [nextProduct, nextItems, allWarehouses] = await Promise.all([
        api.getMenuProduct(productId, currentOrganization.id, accessToken),
        api.listInventoryItems(currentOrganization.id, accessToken),
        api.listInventoryWarehouses(currentOrganization.id, accessToken),
      ]);
      const nextVariant = nextProduct.variants.find((item) => item.id === variantId) ?? null;
      if (!nextVariant) throw new Error("Variant not found in this product.");
      setProduct(nextProduct);
      setVariant(nextVariant);
      setInventoryItems(nextItems.filter((item) => item.is_active));
      const localWarehouses = allWarehouses.filter((item) => item.is_active && item.location_id === currentLocation.id);
      setWarehouses(localWarehouses);
      setWarehouseId((current) => localWarehouses.some((item) => item.id === current) ? current : localWarehouses[0]?.id ?? "");
      try {
        const nextRecipe = await api.getVariantRecipe(variantId, currentOrganization.id, accessToken);
        setRecipe(nextRecipe);
        setIngredients(nextRecipe.components.sort((left, right) => left.sort_order - right.sort_order).map((component) => ({
          clientId: component.id,
          inventoryItemId: component.inventory_item_id,
          itemName: component.item_name,
          baseUnit: component.base_unit,
          quantity: component.quantity,
          unit: component.base_unit,
        })));
        setDirty(false);
      } catch (caught) {
        if (!(caught instanceof ApiError) || caught.status !== 404) throw caught;
        setRecipe(null);
        setIngredients([]);
        setDirty(false);
      }
    } catch (caught) {
      setProduct(null);
      setVariant(null);
      setError(caught instanceof Error ? caught.message : "Unable to load recipe");
    } finally {
      setLoading(false);
    }
  }, [accessToken, currentLocation, currentOrganization, productId, variantId]);

  useEffect(() => {
    let cancelled = false;
    if (permissionsLoading || !canReadRecipe) return;
    Promise.resolve().then(() => { if (!cancelled) void loadRecipe(); });
    return () => { cancelled = true; };
  }, [canReadRecipe, loadRecipe, permissionsLoading]);

  useEffect(() => {
    let cancelled = false;
    if (!canReadRecipe || !accessToken || !currentOrganization || !currentLocation || !warehouseId || !variant) return;
    Promise.resolve().then(() => {
      if (cancelled) return;
      setCostLoading(true);
      void api.getVariantCost(variant.id, warehouseId, currentOrganization.id, accessToken, currentLocation.id)
      .then((nextCost) => { if (!cancelled) setCost(nextCost); })
      .catch((caught) => {
        if (!cancelled) {
          setCost(null);
          if (!(caught instanceof ApiError) || caught.status !== 404) {
            setError(caught instanceof Error ? caught.message : "Unable to calculate recipe cost");
          }
        }
      }).finally(() => { if (!cancelled) setCostLoading(false); });
    });
    return () => { cancelled = true; };
  }, [accessToken, canReadRecipe, currentLocation, currentOrganization, variant, warehouseId]);

  const availableItems = useMemo(() => {
    const used = new Set(ingredients.map((ingredient) => ingredient.inventoryItemId));
    const needle = search.trim().toLocaleLowerCase();
    return inventoryItems.filter((item) => !used.has(item.id) && (!needle || item.name.toLocaleLowerCase().includes(needle) || item.sku?.toLocaleLowerCase().includes(needle))).slice(0, 8);
  }, [ingredients, inventoryItems, search]);
  const componentCosts = useMemo(() => {
    const byId = new Map<string, RecipeCost["components"][number]>();
    const byName = new Map<string, RecipeCost["components"][number]>();
    for (const component of cost?.components ?? []) {
      if (component.inventory_item_id) byId.set(component.inventory_item_id, component);
      byName.set(component.name, component);
    }
    return { byId, byName };
  }, [cost]);

  function addIngredient(item?: InventoryItemResponse) {
    const selected = item ?? availableItems[0];
    if (!selected) return;
    setIngredients((current) => [...current, {
      clientId: crypto.randomUUID(),
      inventoryItemId: selected.id,
      itemName: selected.name,
      baseUnit: selected.base_unit,
      quantity: "1",
      unit: selected.base_unit,
    }]);
    setCost(null);
    setDirty(true);
    setSearch("");
  }

  async function saveRecipe() {
    if (!accessToken || !currentOrganization || !variant || ingredients.length === 0) return;
    if (ingredients.some((ingredient) => !isPositiveMenuDecimal(ingredient.quantity))) {
      setError("Every ingredient quantity must be greater than zero and use no more than six decimal places.");
      return;
    }
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const nextRecipe = await api.setVariantRecipe(variant.id, {
        name: recipe?.name ?? `${product?.name ?? "Product"} / ${variant.name}`,
        yield_quantity: "1",
        components: ingredients.map((ingredient, index) => ({
          inventory_item_id: ingredient.inventoryItemId,
          quantity: ingredient.quantity,
          unit: ingredient.unit,
          sort_order: index,
        })),
      }, currentOrganization.id, accessToken);
      setRecipe(nextRecipe);
      setIngredients(nextRecipe.components.sort((left, right) => left.sort_order - right.sort_order).map((component) => ({
        clientId: component.id,
        inventoryItemId: component.inventory_item_id,
        itemName: component.item_name,
        baseUnit: component.base_unit,
        quantity: component.quantity,
        unit: component.base_unit,
      })));
      setDirty(false);
      setMessage("Recipe saved.");
      if (warehouseId && currentLocation) {
        try {
          setCost(await api.getVariantCost(variant.id, warehouseId, currentOrganization.id, accessToken, currentLocation.id));
          setMessage("Recipe saved. Costs were recalculated from the selected warehouse.");
        } catch (caught) {
          setCost(null);
          setError(caught instanceof Error ? `Recipe saved, but costs could not be refreshed: ${caught.message}` : "Recipe saved, but costs could not be refreshed.");
        }
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to save recipe");
    } finally {
      setSaving(false);
    }
  }

  if (!permissionsLoading && !canReadRecipe) return <div className="menu-state is-error"><strong>Recipe access is restricted.</strong><span>Your role does not include recipe access.</span><Link href={`/app/menu/products/${productId}`}>Back to product</Link></div>;
  if (loading || permissionsLoading) return <div className="menu-state">Loading recipe…</div>;
  if (!product || !variant) return <div className="menu-state is-error"><strong>Recipe could not be loaded.</strong><span>{error}</span><Link href={`/app/menu/products/${productId}`}>Back to product</Link></div>;

  const currency = currentOrganization?.currency_code ?? "KZT";

  return (
    <>
      <Link className="menu-back-link" href={`/app/menu/products/${product.id}`}><ArrowLeft aria-hidden="true" />{product.name}</Link>
      <header className="menu-header menu-editor-header"><div><p className="menu-breadcrumb">Menu / {product.name} / {variant.name}</p><h1>{product.name} / {variant.name}</h1></div></header>
      {message && <p className="menu-flash" role="status"><Check aria-hidden="true" />{message}</p>}
      {error && <div className="menu-state is-error" role="alert"><strong>Recipe needs attention.</strong><span>{error}</span></div>}

      <div className="recipe-layout">
        <section className="recipe-editor-card" aria-labelledby="recipe-ingredients-title">
          <div className="recipe-card-heading"><h2 id="recipe-ingredients-title">Recipe ingredients</h2><span>Yield: 1</span></div>
          {ingredients.length === 0 ? (
            <div className="recipe-empty"><strong>No ingredients yet</strong><span>Add an inventory item to build this recipe.</span></div>
          ) : (
            <div className="recipe-table-wrap" tabIndex={0} aria-label="Recipe ingredients table">
              <div className="recipe-table-head"><span>Ingredient</span><span>Quantity</span><span>Unit</span><span>Current cost</span><span className="sr-only">Remove</span></div>
              {ingredients.map((ingredient) => {
                const currentCost = componentCosts.byId.get(ingredient.inventoryItemId) ?? componentCosts.byName.get(ingredient.itemName);
                return (
                  <div className="recipe-row" key={ingredient.clientId}>
                    <strong>{ingredient.itemName}</strong>
                    <label><span className="sr-only">{ingredient.itemName} quantity</span><input aria-label={`${ingredient.itemName} quantity`} disabled={!canWriteRecipe} inputMode="decimal" value={ingredient.quantity} onChange={(event) => { setIngredients((current) => current.map((item) => item.clientId === ingredient.clientId ? { ...item, quantity: event.target.value } : item)); setCost(null); setDirty(true); }} /></label>
                    <label><span className="sr-only">{ingredient.itemName} unit</span><select aria-label={`${ingredient.itemName} unit`} disabled={!canWriteRecipe} value={ingredient.unit} onChange={(event) => { setIngredients((current) => current.map((item) => item.clientId === ingredient.clientId ? { ...item, unit: event.target.value as InventoryUnitCode } : item)); setCost(null); setDirty(true); }}>{unitsFor(ingredient.baseUnit).map((unit) => <option key={unit} value={unit}>{unit === "l" ? "L" : unit}</option>)}</select></label>
                    <span className="recipe-row-cost">{currentCost?.cost === null ? <span className="menu-incomplete"><CircleAlert aria-hidden="true" />Missing WAC</span> : currentCost ? formatMenuMoney(currentCost.cost, currency) : "—"}</span>
                    <button className="menu-icon-button" type="button" disabled={!canWriteRecipe} onClick={() => { setIngredients((current) => current.filter((item) => item.clientId !== ingredient.clientId)); setCost(null); setDirty(true); }} aria-label={`Remove ${ingredient.itemName}`}><Trash2 aria-hidden="true" /></button>
                  </div>
                );
              })}
            </div>
          )}

          {canWriteRecipe && (
            <div className="ingredient-picker">
              <div className="ingredient-search"><Search aria-hidden="true" /><input type="search" placeholder="Search ingredient to add" value={search} onChange={(event) => setSearch(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); addIngredient(); } }} /></div>
              <button className="menu-secondary-button" type="button" disabled={availableItems.length === 0} onClick={() => addIngredient()}><Plus aria-hidden="true" />Add ingredient</button>
              {search && availableItems.length > 0 && <div className="ingredient-results" role="listbox" aria-label="Inventory item results">{availableItems.map((item) => <button aria-selected="false" key={item.id} role="option" type="button" onClick={() => addIngredient(item)}><span><strong>{item.name}</strong>{item.sku && <small>{item.sku}</small>}</span><em>{item.base_unit}</em></button>)}</div>}
            </div>
          )}
          {canWriteRecipe && <div className="recipe-save-bar">{dirty && <span>Unsaved changes — cost will refresh after saving.</span>}<button className="menu-primary-button" type="button" disabled={saving || ingredients.length === 0 || ingredients.some((ingredient) => !isPositiveMenuDecimal(ingredient.quantity))} onClick={() => void saveRecipe()}>{saving ? "Saving…" : "Save recipe"}</button></div>}
        </section>

        <aside className="recipe-cost-card" aria-label="Recipe cost and margin">
          <div className="recipe-cost-metrics">
            <div className="is-primary"><span>Sale price</span><strong>{formatMenuPriceMinor(cost?.price_minor ?? variant.effective_price_minor, currency)}</strong></div>
            <div><span>Recipe cost</span><strong>{costLoading ? "…" : formatMenuMoney(cost?.recipe_cost ?? null, currency)}</strong></div>
            <div><span>Food cost</span><strong>{costLoading ? "…" : formatMenuPercent(cost?.food_cost_percent ?? null)}</strong></div>
            <div className="is-primary"><span>Gross profit</span><strong>{costLoading ? "…" : formatMenuMoney(cost?.gross_profit ?? null, currency)}</strong></div>
            <div className="is-primary"><span>Gross margin</span><strong>{costLoading ? "…" : formatMenuPercent(cost?.gross_margin_percent ?? null)}</strong></div>
          </div>
          {cost?.status === "INCOMPLETE" && <div className="recipe-cost-warning" role="status"><CircleAlert aria-hidden="true" /><div><strong>Cost incomplete</strong><p>{cost.missing_cost_items.length ? `${cost.missing_cost_items.join(", ")} ${cost.missing_cost_items.length === 1 ? "has" : "have"} no inventory cost yet.` : "One or more ingredients have no inventory cost yet."}</p></div></div>}
          <label className="recipe-warehouse"><span>Warehouse</span><select value={warehouseId} disabled={warehouses.length === 0} onChange={(event) => { setCost(null); setWarehouseId(event.target.value); }}>{warehouses.length === 0 && <option value="">No warehouse for this location</option>}{warehouses.map((warehouse) => <option key={warehouse.id} value={warehouse.id}>{currentLocation?.name} · {warehouse.name}</option>)}</select><small>WAC and margins are calculated for this warehouse.</small></label>
        </aside>
      </div>
    </>
  );
}

function unitsFor(baseUnit: InventoryUnitCode): InventoryUnitCode[] {
  if (baseUnit === "g") return ["g", "kg"];
  if (baseUnit === "ml") return ["ml", "l"];
  return ["pcs"];
}
