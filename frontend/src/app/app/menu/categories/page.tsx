"use client";

import { Archive, Check, Pencil, Plus, RotateCcw, X } from "lucide-react";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { useMenuPermissions } from "@/hooks/use-menu-permissions";
import { api, type MenuCategory } from "@/lib/api";

type CategoryDraft = { name: string; sortOrder: string };

const EMPTY_DRAFT: CategoryDraft = { name: "", sortOrder: "0" };

export default function CategoriesPage() {
  const { accessToken } = useAuth();
  const { currentOrganization } = useWorkspace();
  const { canArchiveProduct, canCreateProduct, canUpdateProduct, loading: permissionsLoading } = useMenuPermissions();
  const [categories, setCategories] = useState<MenuCategory[]>([]);
  const [draft, setDraft] = useState<CategoryDraft>(EMPTY_DRAFT);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const loadCategories = useCallback(async () => {
    if (!accessToken || !currentOrganization) return;
    setLoading(true);
    setError("");
    try {
      setCategories(await api.listMenuCategories(currentOrganization.id, accessToken));
    } catch (caught) {
      setCategories([]);
      setError(caught instanceof Error ? caught.message : "Unable to load categories");
    } finally {
      setLoading(false);
    }
  }, [accessToken, currentOrganization]);

  useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(() => { if (!cancelled) void loadCategories(); });
    return () => { cancelled = true; };
  }, [loadCategories]);

  const sortedCategories = useMemo(
    () => [...categories].sort((left, right) => left.sort_order - right.sort_order || left.name.localeCompare(right.name)),
    [categories],
  );

  function closeForm() {
    setShowForm(false);
    setEditingId(null);
    setDraft(EMPTY_DRAFT);
    setError("");
  }

  async function submitCategory(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!accessToken || !currentOrganization || !draft.name.trim()) return;
    setSaving(true);
    setError("");
    setMessage("");
    try {
      if (editingId) {
        await api.updateMenuCategory(
          editingId,
          { name: draft.name.trim(), sort_order: Number(draft.sortOrder) || 0 },
          currentOrganization.id,
          accessToken,
        );
        setMessage("Category updated.");
      } else {
        await api.createMenuCategory(
          { name: draft.name.trim(), sort_order: Number(draft.sortOrder) || 0 },
          currentOrganization.id,
          accessToken,
        );
        setMessage("Category created.");
      }
      closeForm();
      await loadCategories();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to save category");
    } finally {
      setSaving(false);
    }
  }

  async function setCategoryActive(category: MenuCategory, active: boolean) {
    if (!accessToken || !currentOrganization) return;
    setError("");
    setMessage("");
    try {
      if (active) {
        await api.updateMenuCategory(
          category.id,
          { is_active: true },
          currentOrganization.id,
          accessToken,
        );
        setMessage(`${category.name} restored.`);
      } else {
        await api.archiveMenuCategory(category.id, currentOrganization.id, accessToken);
        setMessage(`${category.name} archived.`);
      }
      await loadCategories();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to update category");
    }
  }

  return (
    <>
      <header className="menu-header">
        <div>
          <p className="menu-breadcrumb">Menu / Categories</p>
          <h1>Categories</h1>
          <p className="menu-header-copy">Organize products into a clear, searchable menu.</p>
        </div>
        {!permissionsLoading && canCreateProduct && (
          <button
            className="menu-primary-button"
            type="button"
            onClick={() => {
              setEditingId(null);
              setDraft({ name: "", sortOrder: String(categories.length) });
              setShowForm(true);
              setError("");
            }}
          >
            <Plus aria-hidden="true" />
            Add category
          </button>
        )}
      </header>

      {message && <p className="menu-flash" role="status"><Check aria-hidden="true" />{message}</p>}
      {error && <div className="menu-state is-error" role="alert"><strong>Categories could not be updated.</strong><span>{error}</span></div>}

      {showForm && (
        <section className="menu-inline-form" aria-labelledby="category-form-title">
          <div className="menu-section-heading">
            <h2 id="category-form-title">{editingId ? "Edit category" : "New category"}</h2>
            <button className="menu-icon-button" type="button" onClick={closeForm} aria-label="Close category form"><X aria-hidden="true" /></button>
          </div>
          <form className="menu-category-form" onSubmit={submitCategory}>
            <label>
              <span>Name</span>
              <input autoFocus maxLength={150} required value={draft.name} onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))} />
            </label>
            <label>
              <span>Sort order</span>
              <input min="0" step="1" type="number" value={draft.sortOrder} onChange={(event) => setDraft((current) => ({ ...current, sortOrder: event.target.value }))} />
            </label>
            <button className="menu-primary-button" disabled={saving || !draft.name.trim()} type="submit">{saving ? "Saving…" : "Save category"}</button>
          </form>
        </section>
      )}

      {loading ? (
        <div className="menu-state" aria-live="polite">Loading categories…</div>
      ) : sortedCategories.length === 0 ? (
        <div className="menu-state"><strong>No categories yet</strong><span>Add Coffee, Tea, Bakery, or another section to start your menu.</span></div>
      ) : (
        <section className="category-list" aria-label="Menu categories">
          <div className="category-list-head"><span>Category</span><span>Order</span><span>Status</span><span className="sr-only">Actions</span></div>
          {sortedCategories.map((category) => (
            <article className={!category.is_active ? "category-row is-archived" : "category-row"} key={category.id}>
              <strong>{category.name}</strong>
              <span>{category.sort_order}</span>
              <span className={category.is_active ? "menu-status status-active" : "menu-status status-archived"}>{category.is_active ? "Active" : "Archived"}</span>
              {!permissionsLoading && (canUpdateProduct || canArchiveProduct) && (
                <div className="category-row-actions">
                  {canUpdateProduct && <button
                    className="menu-icon-button"
                    type="button"
                    aria-label={`Edit ${category.name}`}
                    onClick={() => {
                      setEditingId(category.id);
                      setDraft({ name: category.name, sortOrder: String(category.sort_order) });
                      setShowForm(true);
                      setError("");
                    }}
                  ><Pencil aria-hidden="true" /></button>}
                  {((category.is_active && canArchiveProduct) || (!category.is_active && canUpdateProduct)) && <button
                    className="menu-icon-button"
                    type="button"
                    aria-label={`${category.is_active ? "Archive" : "Restore"} ${category.name}`}
                    onClick={() => void setCategoryActive(category, !category.is_active)}
                  >{category.is_active ? <Archive aria-hidden="true" /> : <RotateCcw aria-hidden="true" />}</button>}
                </div>
              )}
            </article>
          ))}
        </section>
      )}
    </>
  );
}
