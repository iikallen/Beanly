"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { useMenuPermissions } from "@/hooks/use-menu-permissions";
import { api, type MenuCategory } from "@/lib/api";
import { parseMenuPriceToMinor } from "@/lib/menu";

export default function NewProductPage() {
  const { accessToken } = useAuth();
  const { currentOrganization } = useWorkspace();
  const { canCreateProduct, canWritePrice, loading: permissionsLoading } = useMenuPermissions();
  const router = useRouter();
  const [categories, setCategories] = useState<MenuCategory[]>([]);
  const [categoryId, setCategoryId] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [variantName, setVariantName] = useState("Default");
  const [sku, setSku] = useState("");
  const [price, setPrice] = useState("0");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    if (!accessToken || !currentOrganization) return;
    api.listMenuCategories(currentOrganization.id, accessToken).then((items) => {
      if (cancelled) return;
      const active = items.filter((item) => item.is_active);
      setCategories(active);
      setCategoryId(active[0]?.id ?? "");
    }).catch((caught) => {
      if (!cancelled) setError(caught instanceof Error ? caught.message : "Unable to load categories");
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });
    return () => { cancelled = true; };
  }, [accessToken, currentOrganization]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const priceMinor = canWritePrice ? parseMenuPriceToMinor(price) : "0";
    if (!accessToken || !currentOrganization || !categoryId || !name.trim()) return;
    if (priceMinor === null) {
      setError("Enter a valid non-negative price with no more than two decimal places.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const product = await api.createMenuProduct({
        category_id: categoryId,
        name: name.trim(),
        description: description.trim() || null,
        default_variant: {
          name: variantName.trim() || "Default",
          sku: sku.trim() || null,
          base_price_minor: priceMinor,
        },
      }, currentOrganization.id, accessToken);
      router.push(`/app/menu/products/${product.id}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to create product");
    } finally {
      setSaving(false);
    }
  }

  if (!permissionsLoading && !canCreateProduct) {
    return <div className="menu-state is-error"><strong>Product creation is restricted.</strong><span>Your role does not include menu product creation.</span></div>;
  }

  return (
    <>
      <Link className="menu-back-link" href="/app/menu/products"><ArrowLeft aria-hidden="true" />Products</Link>
      <header className="menu-header menu-editor-header"><div><p className="menu-breadcrumb">Menu / Products / New</p><h1>Add product</h1><p className="menu-header-copy">Create the product and its first sellable variant.</p></div></header>
      {error && <div className="menu-state is-error" role="alert"><strong>Product could not be created.</strong><span>{error}</span></div>}
      {loading ? <div className="menu-state">Loading categories…</div> : categories.length === 0 ? (
        <div className="menu-state"><strong>A category is required</strong><span>Create a category before adding a product.</span><Link href="/app/menu/categories">Create category</Link></div>
      ) : (
        <form className="menu-editor-card" onSubmit={submit}>
          <section><div className="menu-section-heading"><div><h2>General</h2><p>The product name and menu category.</p></div></div><div className="menu-form-grid">
            <label><span>Name</span><input autoFocus maxLength={200} required value={name} onChange={(event) => setName(event.target.value)} placeholder="Cappuccino" /></label>
            <label><span>Category</span><select required value={categoryId} onChange={(event) => setCategoryId(event.target.value)}>{categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}</select></label>
            <label className="menu-full-field"><span>Description <small>Optional</small></span><textarea maxLength={1000} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Espresso with steamed milk" /></label>
          </div></section>
          <section><div className="menu-section-heading"><div><h2>First variant</h2><p>For products without sizes, keep the name “Default”.</p></div></div><div className="menu-form-grid menu-variant-fields">
            <label><span>Variant name</span><input maxLength={100} required value={variantName} onChange={(event) => setVariantName(event.target.value)} /></label>
            <label><span>Base price ({currentOrganization?.currency_code})</span><input disabled={!canWritePrice} inputMode="decimal" required value={price} onChange={(event) => setPrice(event.target.value)} />{!canWritePrice && <small>Price editing is restricted for your role.</small>}</label>
            <label><span>SKU <small>Optional</small></span><input maxLength={100} value={sku} onChange={(event) => setSku(event.target.value)} placeholder="CAP-350" /></label>
          </div></section>
          <div className="menu-editor-actions"><Link className="menu-secondary-button" href="/app/menu/products">Cancel</Link><button className="menu-primary-button" disabled={saving || !name.trim() || !categoryId} type="submit">{saving ? "Creating…" : "Create product"}</button></div>
        </form>
      )}
    </>
  );
}
