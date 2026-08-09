"use client";

import { Archive, ArrowLeft, Check, CircleAlert, Plus, Save, UtensilsCrossed } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { useMenuPermissions } from "@/hooks/use-menu-permissions";
import {
  ApiError,
  api,
  type MenuCategory,
  type MenuProduct,
  type ProductVariant,
  type ProductStatus,
  type RecipeCost,
  type WarehouseResponse,
} from "@/lib/api";
import {
  formatMenuMoney,
  formatMenuPercent,
  formatMenuPriceMinor,
  formatMenuStatus,
  menuStatusClass,
  parseMenuPriceToMinor,
  priceMinorToInput,
} from "@/lib/menu";

type VariantDraft = { name: string; sku: string; price: string; locationPrice: string };

export default function ProductEditorPage() {
  const { productId } = useParams<{ productId: string }>();
  const { accessToken } = useAuth();
  const { currentOrganization, currentLocation } = useWorkspace();
  const permissions = useMenuPermissions();
  const router = useRouter();
  const [product, setProduct] = useState<MenuProduct | null>(null);
  const [categories, setCategories] = useState<MenuCategory[]>([]);
  const [warehouses, setWarehouses] = useState<WarehouseResponse[]>([]);
  const [warehouseId, setWarehouseId] = useState("");
  const [costs, setCosts] = useState<Record<string, RecipeCost | null>>({});
  const [name, setName] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [description, setDescription] = useState("");
  const [productStatus, setProductStatus] = useState<ProductStatus>("DRAFT");
  const [isAvailable, setIsAvailable] = useState(true);
  const [isVisible, setIsVisible] = useState(true);
  const [newVariant, setNewVariant] = useState<VariantDraft>({ name: "", sku: "", price: "0", locationPrice: "" });
  const [addingVariant, setAddingVariant] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const loadProduct = useCallback(async () => {
    if (!accessToken || !currentOrganization || !currentLocation) return;
    setLoading(true);
    setError("");
    setCosts({});
    try {
      const [nextProduct, nextCategories] = await Promise.all([
        api.getMenuProduct(productId, currentOrganization.id, accessToken, currentLocation.id),
        api.listMenuCategories(currentOrganization.id, accessToken),
      ]);
      setProduct(nextProduct);
      setName(nextProduct.name);
      setCategoryId(nextProduct.category_id);
      setDescription(nextProduct.description ?? "");
      setProductStatus(nextProduct.status);
      setIsAvailable(nextProduct.is_available ?? true);
      setIsVisible(nextProduct.is_visible ?? true);
      setCategories(nextCategories.filter((category) => category.is_active || category.id === nextProduct.category_id));
    } catch (caught) {
      setProduct(null);
      setError(caught instanceof Error ? caught.message : "Unable to load product");
    } finally {
      setLoading(false);
    }
  }, [accessToken, currentLocation, currentOrganization, productId]);

  useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(() => { if (!cancelled) void loadProduct(); });
    return () => { cancelled = true; };
  }, [loadProduct]);

  useEffect(() => {
    let cancelled = false;
    void Promise.resolve().then(async () => {
      if (cancelled) return;
      setWarehouses([]);
      setWarehouseId("");
      if (permissions.loading || !permissions.canReadRecipe || !accessToken || !currentOrganization || !currentLocation) return;
      try {
        const allWarehouses = await api.listInventoryWarehouses(currentOrganization.id, accessToken);
        if (cancelled) return;
        const localWarehouses = allWarehouses.filter((item) => item.is_active && item.location_id === currentLocation.id);
        setWarehouses(localWarehouses);
        setWarehouseId(localWarehouses[0]?.id ?? "");
      } catch (caught) {
        if (!cancelled) setError(caught instanceof Error ? `Warehouses could not be loaded: ${caught.message}` : "Warehouses could not be loaded.");
      }
    });
    return () => { cancelled = true; };
  }, [accessToken, currentLocation, currentOrganization, permissions.canReadRecipe, permissions.loading]);

  useEffect(() => {
    let cancelled = false;
    if (!accessToken || !currentOrganization || !currentLocation || !warehouseId || !permissions.canReadRecipe || !product) return;
    Promise.all(product.variants.map(async (variant) => {
      try {
        const cost = await api.getVariantCost(variant.id, warehouseId, currentOrganization.id, accessToken, currentLocation.id);
        return [variant.id, cost] as const;
      } catch (caught) {
        if (!(caught instanceof ApiError) || caught.status !== 404) {
          setError(caught instanceof Error ? `Recipe costs could not be loaded: ${caught.message}` : "Recipe costs could not be loaded.");
        }
        return [variant.id, null] as const;
      }
    })).then((entries) => { if (!cancelled) setCosts(Object.fromEntries(entries)); });
    return () => { cancelled = true; };
  }, [accessToken, currentLocation, currentOrganization, permissions.canReadRecipe, product, warehouseId]);

  const activeVariants = useMemo(
    () => product?.variants.filter((variant) => variant.status !== "ARCHIVED").sort((left, right) => left.sort_order - right.sort_order) ?? [],
    [product],
  );

  async function saveGeneral(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!accessToken || !currentOrganization || !currentLocation || !product || !name.trim() || !categoryId) return;
    setSaving(true);
    setError("");
    setMessage("");
    try {
      await api.updateMenuProduct(product.id, { name: name.trim(), category_id: categoryId, description: description.trim() || null, status: productStatus }, currentOrganization.id, accessToken);
      try {
        await api.setProductLocation(
          product.id,
          currentLocation.id,
          { is_available: isAvailable, is_visible: isVisible },
          currentOrganization.id,
          accessToken,
        );
      } catch (caught) {
        await loadProduct();
        throw new Error(caught instanceof Error ? `Product details were saved, but location settings were not: ${caught.message}` : "Product details were saved, but location settings were not.");
      }
      setMessage("Product details saved.");
      await loadProduct();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to save product");
    } finally {
      setSaving(false);
    }
  }

  async function createVariant(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const priceMinor = permissions.canWritePrice ? parseMenuPriceToMinor(newVariant.price) : "0";
    const locationMinor = permissions.canWritePrice && newVariant.locationPrice.trim() ? parseMenuPriceToMinor(newVariant.locationPrice) : null;
    if (!accessToken || !currentOrganization || !product || !newVariant.name.trim()) return;
    if (priceMinor === null || (permissions.canWritePrice && newVariant.locationPrice.trim() && locationMinor === null)) {
      setError("Enter valid non-negative prices with no more than two decimal places.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const created = await api.createProductVariant(product.id, {
        name: newVariant.name.trim(),
        sku: newVariant.sku.trim() || null,
        base_price_minor: priceMinor,
        sort_order: activeVariants.length,
      }, currentOrganization.id, accessToken);
      if (permissions.canWritePrice && currentLocation && locationMinor !== null) {
        try {
          await api.setVariantPrice(created.id, currentLocation.id, locationMinor, currentOrganization.id, accessToken);
        } catch (caught) {
          setAddingVariant(false);
          setNewVariant({ name: "", sku: "", price: "0", locationPrice: "" });
          await loadProduct();
          throw new Error(caught instanceof Error ? `Variant created, but its location price could not be saved: ${caught.message}` : "Variant created, but its location price could not be saved.");
        }
      }
      setAddingVariant(false);
      setNewVariant({ name: "", sku: "", price: "0", locationPrice: "" });
      setMessage("Variant added.");
      await loadProduct();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to add variant");
    } finally {
      setSaving(false);
    }
  }

  async function archiveProduct() {
    if (!accessToken || !currentOrganization || !product) return;
    if (!window.confirm(`Archive ${product.name}? It will disappear from the active menu.`)) return;
    setSaving(true);
    setError("");
    try {
      await api.archiveMenuProduct(product.id, currentOrganization.id, accessToken);
      router.push("/app/menu/products");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to archive product");
      setSaving(false);
    }
  }

  if (loading) return <div className="menu-state">Loading product…</div>;
  if (!product) return <div className="menu-state is-error"><strong>Product could not be loaded.</strong><span>{error}</span><Link href="/app/menu/products">Back to products</Link></div>;

  return (
    <>
      <Link className="menu-back-link" href="/app/menu/products"><ArrowLeft aria-hidden="true" />Products</Link>
      <header className="menu-header menu-editor-header">
        <div><p className="menu-breadcrumb">Menu / {categories.find((category) => category.id === product.category_id)?.name ?? "Products"}</p><h1>{product.name}</h1><div className="menu-title-meta"><span className={menuStatusClass(product.status)}>{formatMenuStatus(product.status)}</span><span>{activeVariants.length} {activeVariants.length === 1 ? "variant" : "variants"}</span></div></div>
        {!permissions.loading && permissions.canArchiveProduct && product.status !== "ARCHIVED" && <button className="menu-danger-button" type="button" disabled={saving} onClick={() => void archiveProduct()}><Archive aria-hidden="true" />Archive product</button>}
      </header>

      {message && <p className="menu-flash" role="status"><Check aria-hidden="true" />{message}</p>}
      {error && <div className="menu-state is-error" role="alert"><strong>Product needs attention.</strong><span>{error}</span></div>}

      <div className="menu-editor-stack">
        <form className="menu-editor-card" onSubmit={saveGeneral}>
          <section><div className="menu-section-heading"><div><h2>General</h2><p>Product information shared by every variant.</p></div></div><div className="menu-form-grid">
            <label><span>Name</span><input maxLength={200} required disabled={!permissions.canUpdateProduct} value={name} onChange={(event) => setName(event.target.value)} /></label>
            <label><span>Category</span><select disabled={!permissions.canUpdateProduct} value={categoryId} onChange={(event) => setCategoryId(event.target.value)}>{categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}</select></label>
            <label><span>Status</span><select disabled={!permissions.canUpdateProduct || product.status === "ARCHIVED"} value={productStatus} onChange={(event) => setProductStatus(event.target.value as ProductStatus)}><option value="DRAFT">Draft</option><option value="ACTIVE">Active</option>{product.status === "ARCHIVED" && <option value="ARCHIVED">Archived</option>}</select></label>
            <label className="menu-full-field"><span>Description <small>Optional</small></span><textarea maxLength={1000} disabled={!permissions.canUpdateProduct} value={description} onChange={(event) => setDescription(event.target.value)} /></label>
            <div className="menu-full-field menu-location-settings" role="group" aria-label={`${currentLocation?.name} product settings`}>
              <div><strong>{currentLocation?.name}</strong><span>Location availability is separate from the product status.</span></div>
              <label className="menu-check"><input type="checkbox" disabled={!permissions.canUpdateProduct} checked={isVisible} onChange={(event) => setIsVisible(event.target.checked)} /><span>Visible in menu</span></label>
              <label className="menu-check"><input type="checkbox" disabled={!permissions.canUpdateProduct} checked={isAvailable} onChange={(event) => setIsAvailable(event.target.checked)} /><span>Available for sale</span></label>
            </div>
          </div></section>
          {permissions.canUpdateProduct && <div className="menu-editor-actions"><button className="menu-primary-button" disabled={saving || !name.trim()} type="submit"><Save aria-hidden="true" />{saving ? "Saving…" : "Save details"}</button></div>}
        </form>

        <section className="menu-editor-card">
          <div className="menu-section-heading"><div><h2>Variants</h2><p>Each size has its own price and recipe.</p></div>{permissions.canCreateProduct && <button className="menu-secondary-button" type="button" onClick={() => setAddingVariant((current) => !current)}><Plus aria-hidden="true" />Add variant</button>}</div>
          {permissions.canReadRecipe && <label className="menu-cost-warehouse"><span>Cost warehouse</span><select value={warehouseId} disabled={warehouses.length === 0} onChange={(event) => { setCosts({}); setWarehouseId(event.target.value); }}>{warehouses.length === 0 && <option value="">No warehouse for this location</option>}{warehouses.map((item) => <option key={item.id} value={item.id}>{currentLocation?.name} · {item.name}</option>)}</select><small>Recipe costs and margins use this warehouse’s WAC.</small></label>}
          {addingVariant && <form className="menu-add-variant" onSubmit={createVariant}><label><span>Name</span><input autoFocus maxLength={100} required value={newVariant.name} onChange={(event) => setNewVariant((current) => ({ ...current, name: event.target.value }))} placeholder="350 ml" /></label><label><span>Base price</span><input disabled={!permissions.canWritePrice} inputMode="decimal" required value={newVariant.price} onChange={(event) => setNewVariant((current) => ({ ...current, price: event.target.value }))} /></label><label><span>{currentLocation?.name} price <small>Optional</small></span><input disabled={!permissions.canWritePrice} inputMode="decimal" value={newVariant.locationPrice} onChange={(event) => setNewVariant((current) => ({ ...current, locationPrice: event.target.value }))} placeholder="Uses base price" /></label><label><span>SKU <small>Optional</small></span><input maxLength={100} value={newVariant.sku} onChange={(event) => setNewVariant((current) => ({ ...current, sku: event.target.value }))} /></label><button className="menu-primary-button" disabled={saving} type="submit">Add variant</button></form>}
          <div className="menu-variant-list">
            {activeVariants.map((variant) => (
              <VariantEditor
                accessToken={accessToken ?? ""}
                canArchive={permissions.canArchiveProduct}
                canEdit={permissions.canUpdateProduct}
                canReadRecipe={permissions.canReadRecipe}
                canWriteRecipe={permissions.canWriteRecipe}
                canWritePrice={permissions.canWritePrice}
                cost={costs[variant.id]}
                costRestricted={!permissions.loading && !permissions.canReadRecipe}
                currency={currentOrganization?.currency_code ?? "KZT"}
                key={`${variant.id}:${variant.updated_at}:${variant.location_price_minor ?? "base"}`}
                locationId={currentLocation?.id ?? ""}
                locationName={currentLocation?.name ?? "Location"}
                organizationId={currentOrganization?.id ?? ""}
                productId={product.id}
                variant={variant}
                onChanged={async (nextMessage) => { setMessage(nextMessage); await loadProduct(); }}
                onError={setError}
              />
            ))}
          </div>
        </section>
      </div>
    </>
  );
}

function VariantEditor({
  variant,
  cost,
  costRestricted,
  productId,
  currency,
  locationId,
  locationName,
  organizationId,
  accessToken,
  canEdit,
  canArchive,
  canReadRecipe,
  canWriteRecipe,
  canWritePrice,
  onChanged,
  onError,
}: {
  variant: ProductVariant;
  cost: RecipeCost | null | undefined;
  costRestricted: boolean;
  productId: string;
  currency: string;
  locationId: string;
  locationName: string;
  organizationId: string;
  accessToken: string;
  canEdit: boolean;
  canArchive: boolean;
  canReadRecipe: boolean;
  canWriteRecipe: boolean;
  canWritePrice: boolean;
  onChanged: (message: string) => Promise<void>;
  onError: (message: string) => void;
}) {
  const [draft, setDraft] = useState<VariantDraft>(() => ({
    name: variant.name,
    sku: variant.sku ?? "",
    price: priceMinorToInput(variant.base_price_minor),
    locationPrice: variant.location_price_minor ? priceMinorToInput(variant.location_price_minor) : "",
  }));
  const [saving, setSaving] = useState(false);

  async function saveVariant(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const baseMinor = canWritePrice ? parseMenuPriceToMinor(draft.price) : variant.base_price_minor;
    const locationMinor = canWritePrice && draft.locationPrice.trim() ? parseMenuPriceToMinor(draft.locationPrice) : null;
    if (baseMinor === null || (canWritePrice && draft.locationPrice.trim() && locationMinor === null)) {
      onError("Enter valid non-negative prices with no more than two decimal places.");
      return;
    }
    setSaving(true);
    onError("");
    try {
      if (canEdit || canWritePrice) {
        await api.updateProductVariant(variant.id, {
          ...(canEdit ? { name: draft.name.trim(), sku: draft.sku.trim() || null } : {}),
          ...(canWritePrice ? { base_price_minor: baseMinor } : {}),
        }, organizationId, accessToken);
      }
      if (canWritePrice) {
        try {
          await api.setVariantPrice(variant.id, locationId, locationMinor, organizationId, accessToken);
        } catch (caught) {
          if (canEdit) await onChanged("Variant details saved. Location price needs attention.");
          throw new Error(caught instanceof Error ? `${canEdit ? "Variant details were saved, but its" : "The"} location price could not be saved: ${caught.message}` : "Location price could not be saved.");
        }
      }
      await onChanged(`${variant.name} saved.`);
    } catch (caught) {
      onError(caught instanceof Error ? caught.message : "Unable to save variant");
    } finally {
      setSaving(false);
    }
  }

  async function archiveVariant() {
    if (!window.confirm(`Archive ${variant.name}?`)) return;
    setSaving(true);
    onError("");
    try {
      await api.archiveProductVariant(variant.id, organizationId, accessToken);
      await onChanged(`${variant.name} archived.`);
    } catch (caught) {
      onError(caught instanceof Error ? caught.message : "Unable to archive variant");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="menu-variant-card" onSubmit={saveVariant}>
      <div className="menu-variant-topline"><div><strong>{variant.name}</strong><span>{variant.is_default ? "Default variant" : variant.sku || "No SKU"}</span></div><span className={menuStatusClass(variant.status)}>{formatMenuStatus(variant.status)}</span></div>
      <div className="menu-variant-grid"><label><span>Name</span><input maxLength={100} required disabled={!canEdit} value={draft.name} onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))} /></label><label><span>SKU <small>Optional</small></span><input maxLength={100} disabled={!canEdit} value={draft.sku} onChange={(event) => setDraft((current) => ({ ...current, sku: event.target.value }))} /></label><label><span>Base price ({currency})</span><input inputMode="decimal" disabled={!canWritePrice} value={draft.price} onChange={(event) => setDraft((current) => ({ ...current, price: event.target.value }))} /></label><label><span>{locationName} price <small>Optional override</small></span><input inputMode="decimal" disabled={!canWritePrice} value={draft.locationPrice} onChange={(event) => setDraft((current) => ({ ...current, locationPrice: event.target.value }))} placeholder={`Uses ${formatMenuPriceMinor(variant.base_price_minor, currency)}`} /></label></div>
      <div className={cost?.status === "INCOMPLETE" ? "menu-variant-cost is-incomplete" : "menu-variant-cost"}>
        <div><span>Effective price</span><strong>{formatMenuPriceMinor(cost?.price_minor ?? variant.effective_price_minor, currency)}</strong></div><div><span>Recipe cost</span><strong>{costRestricted ? "Restricted" : cost === undefined ? "…" : cost === null ? "Not set" : formatMenuMoney(cost.recipe_cost, currency)}</strong></div><div><span>Food cost</span><strong>{costRestricted ? "Restricted" : cost === undefined ? "…" : formatMenuPercent(cost?.food_cost_percent ?? null)}</strong></div><div><span>Gross margin</span><strong>{costRestricted ? "Restricted" : cost === undefined ? "…" : formatMenuPercent(cost?.gross_margin_percent ?? null)}</strong></div>
        {cost?.status === "INCOMPLETE" && <p><CircleAlert aria-hidden="true" /><span><strong>Cost incomplete</strong>{cost.missing_cost_items.length ? `${cost.missing_cost_items.join(", ")} ${cost.missing_cost_items.length === 1 ? "has" : "have"} no inventory cost yet.` : "One or more ingredients have no inventory cost yet."}</span></p>}
      </div>
      <div className="menu-variant-actions">{canReadRecipe && <Link className="menu-secondary-button" href={`/app/menu/products/${productId}/variants/${variant.id}/recipe${locationId ? `?location_id=${encodeURIComponent(locationId)}` : ""}`}><UtensilsCrossed aria-hidden="true" />{canWriteRecipe ? "Edit recipe" : "View recipe"}</Link>}{(canEdit || canWritePrice) && <button className="menu-primary-button" disabled={saving || !draft.name.trim()} type="submit"><Save aria-hidden="true" />{saving ? "Saving…" : "Save variant"}</button>}{canArchive && <button className="menu-icon-button is-danger" disabled={saving} type="button" onClick={() => void archiveVariant()} aria-label={`Archive ${variant.name}`}><Archive aria-hidden="true" /></button>}</div>
    </form>
  );
}
