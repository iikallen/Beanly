"use client";

import { ChevronRight, CircleAlert, Plus, Search, Upload } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { useMenuPermissions } from "@/hooks/use-menu-permissions";
import {
  api,
  type MenuCategory,
  type MenuCostSummary,
  type MenuProduct,
  type ProductStatus,
  type WarehouseResponse,
} from "@/lib/api";
import { formatMenuMoney, formatMenuPriceMinor, formatMenuStatus, menuStatusClass, minimumDecimal, minimumMinor } from "@/lib/menu";

export default function ProductsPage() {
  const { accessToken } = useAuth();
  const { currentOrganization, currentLocation } = useWorkspace();
  const { canCreateProduct, canImport, canReadRecipe, loading: permissionsLoading } = useMenuPermissions();
  const [categories, setCategories] = useState<MenuCategory[]>([]);
  const [products, setProducts] = useState<MenuProduct[]>([]);
  const [warehouses, setWarehouses] = useState<WarehouseResponse[]>([]);
  const [warehouse, setWarehouse] = useState<WarehouseResponse | null>(null);
  const [costs, setCosts] = useState<Record<string, MenuCostSummary["variants"][number] | null>>({});
  const [query, setQuery] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [status, setStatus] = useState<ProductStatus | "">("");
  const [loading, setLoading] = useState(true);
  const [costsLoading, setCostsLoading] = useState(false);
  const [costError, setCostError] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    if (!accessToken || !currentOrganization || !currentLocation) return;
    Promise.resolve().then(() => {
      if (cancelled) return [[], []] as [MenuCategory[], MenuProduct[]];
      setLoading(true);
      setError("");
      setCosts({});
      setCostError("");
      return Promise.all([
        api.listMenuCategories(currentOrganization.id, accessToken),
        api.listMenuProducts(currentOrganization.id, accessToken, { locationId: currentLocation.id }),
      ]);
    }).then(([nextCategories, nextProducts]) => {
      if (cancelled) return;
      setCategories(nextCategories);
      setProducts(nextProducts);
    }).catch((caught) => {
      if (!cancelled) {
        setProducts([]);
        setError(caught instanceof Error ? caught.message : "Unable to load products");
      }
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });
    return () => { cancelled = true; };
  }, [accessToken, currentLocation, currentOrganization]);

  useEffect(() => {
    let cancelled = false;
    void Promise.resolve().then(async () => {
      if (cancelled) return;
      setWarehouses([]);
      setWarehouse(null);
      if (permissionsLoading || !canReadRecipe || !accessToken || !currentOrganization || !currentLocation) return;
      try {
        const allWarehouses = await api.listInventoryWarehouses(currentOrganization.id, accessToken);
        if (cancelled) return;
        const localWarehouses = allWarehouses.filter((item) => item.is_active && item.location_id === currentLocation.id);
        setWarehouses(localWarehouses);
        setWarehouse(localWarehouses[0] ?? null);
      } catch {
        if (!cancelled) setCostError("Warehouses could not be loaded for recipe costing.");
      }
    });
    return () => { cancelled = true; };
  }, [accessToken, canReadRecipe, currentLocation, currentOrganization, permissionsLoading]);

  useEffect(() => {
    let cancelled = false;
    if (!accessToken || !currentOrganization || !currentLocation || !warehouse || !canReadRecipe || products.length === 0) return;
    Promise.resolve().then(() => {
      if (cancelled) return;
      setCostsLoading(true);
      setCostError("");
      void api.getMenuCosts(warehouse.id, currentOrganization.id, accessToken, currentLocation.id)
      .then((summary) => {
        if (!cancelled) setCosts(Object.fromEntries(summary.variants.map((item) => [item.variant_id, item])));
      }).catch(() => {
        if (!cancelled) {
          setCosts({});
          setCostError("Recipe costs could not be loaded for the selected warehouse.");
        }
      }).finally(() => {
        if (!cancelled) setCostsLoading(false);
      });
    });
    return () => { cancelled = true; };
  }, [accessToken, canReadRecipe, currentLocation, currentOrganization, products, warehouse]);

  const categoryNames = useMemo(
    () => new Map(categories.map((category) => [category.id, category.name])),
    [categories],
  );
  const filteredProducts = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return products.filter((product) =>
      (!categoryId || product.category_id === categoryId) &&
      (!status || product.status === status) &&
      (!needle || product.name.toLocaleLowerCase().includes(needle) || product.description?.toLocaleLowerCase().includes(needle)),
    );
  }, [categoryId, products, query, status]);
  const groupedProducts = useMemo(() => {
    const groups = new Map<string, MenuProduct[]>();
    for (const product of filteredProducts) {
      const name = categoryNames.get(product.category_id) ?? "Uncategorized";
      groups.set(name, [...(groups.get(name) ?? []), product]);
    }
    return [...groups.entries()].sort(([left], [right]) => left.localeCompare(right));
  }, [categoryNames, filteredProducts]);

  const currency = currentOrganization?.currency_code ?? "KZT";

  return (
    <>
      <header className="menu-header">
        <div>
          <p className="menu-breadcrumb">Menu / Products</p>
          <h1>Products</h1>
          <p className="menu-header-copy">Prices, recipes, and margins for every item you sell.</p>
        </div>
        {!permissionsLoading && (canImport || canCreateProduct) && <div className="menu-header-actions">
          {canImport && <Link className="menu-secondary-button" href="/app/onboarding"><Upload aria-hidden="true" />Import</Link>}
          {canCreateProduct && <Link className="menu-primary-button" href="/app/menu/products/new"><Plus aria-hidden="true" />Add product</Link>}
        </div>}
      </header>

      <div className="menu-filters">
        <label className="menu-search">
          <span className="sr-only">Search products</span><Search aria-hidden="true" />
          <input type="search" placeholder="Search products" value={query} onChange={(event) => setQuery(event.target.value)} />
        </label>
        <label><span className="sr-only">Category</span><select value={categoryId} onChange={(event) => setCategoryId(event.target.value)}><option value="">All categories</option>{categories.filter((category) => category.is_active).map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}</select></label>
        <label><span className="sr-only">Status</span><select value={status} onChange={(event) => setStatus(event.target.value as ProductStatus | "")}><option value="">All statuses</option><option value="ACTIVE">Active</option><option value="DRAFT">Draft</option><option value="ARCHIVED">Archived</option></select></label>
      </div>

      {warehouses.length > 0 && canReadRecipe && (
        <label className="menu-list-warehouse">
          <span>Cost warehouse</span>
          <select
            value={warehouse?.id ?? ""}
            onChange={(event) => {
              setCosts({});
              setWarehouse(warehouses.find((item) => item.id === event.target.value) ?? null);
            }}
          >
            {warehouses.map((item) => <option key={item.id} value={item.id}>{currentLocation?.name} · {item.name}</option>)}
          </select>
          <small>Product costs use this warehouse’s WAC.</small>
        </label>
      )}

      {canReadRecipe && !permissionsLoading && !warehouse && !loading && !costError && (
        <div className="menu-notice"><CircleAlert aria-hidden="true" /><span><strong>Costs unavailable</strong>No active warehouse exists for {currentLocation?.name}. Recipes can still be edited.</span></div>
      )}
      {costError && canReadRecipe && <div className="menu-notice" role="alert"><CircleAlert aria-hidden="true" /><span><strong>Costs unavailable</strong>{costError}</span></div>}

      {error ? (
        <div className="menu-state is-error" role="alert"><strong>Products could not be loaded.</strong><span>{error}</span></div>
      ) : loading ? (
        <div className="menu-state" aria-live="polite">Loading products…</div>
      ) : products.length === 0 ? (
        <div className="menu-state"><strong>No products yet</strong><span>Create your first product and its default variant.</span>{canCreateProduct && <Link href="/app/menu/products/new">Add product</Link>}</div>
      ) : groupedProducts.length === 0 ? (
        <div className="menu-state"><strong>No matching products</strong><span>Try another search, category, or status.</span></div>
      ) : (
        <div className="menu-product-groups">
          {groupedProducts.map(([categoryName, categoryProducts]) => (
            <section className="menu-product-group" key={categoryName}>
              <div className="menu-group-heading"><h2>{categoryName}</h2><span>{categoryProducts.length} {categoryProducts.length === 1 ? "product" : "products"}</span></div>
              <div className="menu-product-list">
                {categoryProducts.map((product) => {
                  const activeVariants = product.variants.filter((variant) => variant.status !== "ARCHIVED");
                  const prices = activeVariants.map((variant) => costs[variant.id]?.price_minor ?? variant.effective_price_minor);
                  const completeCosts = activeVariants.map((variant) => costs[variant.id]).filter((cost): cost is MenuCostSummary["variants"][number] => cost?.status === "COMPLETE" && cost.recipe_cost !== null);
                  const hasIncomplete = activeVariants.some((variant) => costs[variant.id]?.status === "INCOMPLETE");
                  const minimumPrice = minimumMinor(prices);
                  const minimumCost = minimumDecimal(completeCosts.flatMap((item) => item.recipe_cost ? [item.recipe_cost] : []));
                  return (
                    <Link className="menu-product-row" href={`/app/menu/products/${product.id}`} key={product.id}>
                      <div className="menu-product-main"><strong>{product.name}</strong>{product.description && <span>{product.description}</span>}<small className={product.is_visible === false || product.is_available === false ? "is-location-off" : ""}>{activeVariants.length} {activeVariants.length === 1 ? "variant" : "variants"}{product.is_visible === false ? ` · Hidden at ${currentLocation?.name}` : product.is_available === false ? ` · Unavailable at ${currentLocation?.name}` : ""}</small></div>
                      <div className="menu-product-metric"><span>{activeVariants.length > 1 ? "From" : "Price"}</span><strong>{minimumPrice === null ? "—" : formatMenuPriceMinor(minimumPrice, currency)}</strong></div>
                      <div className="menu-product-metric"><span>{activeVariants.length > 1 ? "Cost from" : "Recipe cost"}</span><strong>{!permissionsLoading && !canReadRecipe ? "Restricted" : costsLoading ? "…" : minimumCost === null ? "—" : formatMenuMoney(minimumCost, currency)}</strong>{canReadRecipe && hasIncomplete && <small className="menu-incomplete"><CircleAlert aria-hidden="true" />Incomplete</small>}</div>
                      <span className={menuStatusClass(product.status)}>{formatMenuStatus(product.status)}</span>
                      <ChevronRight className="menu-row-chevron" aria-hidden="true" />
                    </Link>
                  );
                })}
              </div>
            </section>
          ))}
        </div>
      )}
    </>
  );
}
