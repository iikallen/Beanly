"use client";

import {
  Archive,
  ArrowLeft,
  Check,
  CircleAlert,
  MoreHorizontal,
  Plus,
  Save,
  Trash2,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { useMenuPermissions } from "@/hooks/use-menu-permissions";
import {
  api,
  type CustomizationPreview,
  type InventoryItemResponse,
  type InventoryUnitCode,
  type MenuProduct,
  type ModifierGroup,
  type ModifierOption,
  type ModifierSelectionType,
  type ProductVariant,
  type WarehouseResponse,
} from "@/lib/api";
import {
  formatMenuMoney,
  formatMenuPercent,
  formatMenuPriceMinor,
  isNonZeroSignedMenuDecimal,
  parseMenuPriceToMinor,
  priceMinorToInput,
} from "@/lib/menu";

type ComponentDraft = {
  clientId: string;
  inventoryItemId: string;
  quantityDelta: string;
  unit: InventoryUnitCode;
};

type OptionDraft = {
  id: string | null;
  groupId: string;
  name: string;
  price: string;
  isDefault: boolean;
  isAvailable: boolean;
  locationPrice: string;
  components: ComponentDraft[];
};

type GroupDraft = {
  id: string | null;
  name: string;
  selectionType: ModifierSelectionType;
  minSelections: string;
  maxSelections: string;
};

const EMPTY_GROUP: GroupDraft = {
  id: null,
  name: "",
  selectionType: "SINGLE",
  minSelections: "0",
  maxSelections: "1",
};

export default function ModifierEditorPage() {
  const { productId, variantId } = useParams<{ productId: string; variantId: string }>();
  const { accessToken } = useAuth();
  const { currentOrganization, currentLocation } = useWorkspace();
  const permissions = useMenuPermissions();
  const [product, setProduct] = useState<MenuProduct | null>(null);
  const [variant, setVariant] = useState<ProductVariant | null>(null);
  const [groups, setGroups] = useState<ModifierGroup[]>([]);
  const [inventoryItems, setInventoryItems] = useState<InventoryItemResponse[]>([]);
  const [warehouses, setWarehouses] = useState<WarehouseResponse[]>([]);
  const [warehouseId, setWarehouseId] = useState("");
  const [groupDraft, setGroupDraft] = useState<GroupDraft | null>(null);
  const [optionDraft, setOptionDraft] = useState<OptionDraft | null>(null);
  const [componentPicker, setComponentPicker] = useState("");
  const [preview, setPreview] = useState<CustomizationPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewStale, setPreviewStale] = useState(false);
  const [previewError, setPreviewError] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const loadSequence = useRef(0);

  const loadEditor = useCallback(async (selectedOptionId?: string) => {
    if (!accessToken || !currentOrganization || !currentLocation) return;
    const sequence = ++loadSequence.current;
    setLoading(true);
    setError("");
    try {
      const [nextProduct, nextGroups, nextItems, nextWarehouses] = await Promise.all([
        api.getMenuProduct(productId, currentOrganization.id, accessToken, currentLocation.id),
        api.listModifierGroups(variantId, currentOrganization.id, accessToken, currentLocation.id),
        api.listInventoryItems(currentOrganization.id, accessToken),
        api.listInventoryWarehouses(currentOrganization.id, accessToken),
      ]);
      if (sequence !== loadSequence.current) return;
      const nextVariant = nextProduct.variants.find((item) => item.id === variantId) ?? null;
      if (!nextVariant) throw new Error("Variant not found in this product.");
      const activeGroups = nextGroups.filter((group) => group.is_active).sort((a, b) => a.sort_order - b.sort_order);
      const selected = activeGroups.flatMap((group) => group.options).find((option) => option.id === selectedOptionId && option.is_active)
        ?? activeGroups.flatMap((group) => group.options).find((option) => option.is_active)
        ?? null;
      setProduct(nextProduct);
      setVariant(nextVariant);
      setGroups(activeGroups);
      setInventoryItems(nextItems.filter((item) => item.is_active));
      const localWarehouses = nextWarehouses.filter((item) => item.is_active && item.location_id === currentLocation.id);
      setWarehouses(localWarehouses);
      setWarehouseId((current) => localWarehouses.some((item) => item.id === current) ? current : localWarehouses[0]?.id ?? "");
      setOptionDraft(selected ? optionToDraft(selected, nextItems) : null);
      setPreview(null);
      setPreviewStale(false);
      setPreviewError("");
      setComponentPicker("");
    } catch (caught) {
      if (sequence !== loadSequence.current) return;
      setProduct(null);
      setVariant(null);
      setError(caught instanceof Error ? caught.message : "Unable to load modifiers");
    } finally {
      if (sequence === loadSequence.current) setLoading(false);
    }
  }, [accessToken, currentLocation, currentOrganization, productId, variantId]);

  useEffect(() => {
    let cancelled = false;
    if (permissions.loading || !permissions.canWriteModifier) return;
    Promise.resolve().then(() => { if (!cancelled) void loadEditor(); });
    return () => { cancelled = true; loadSequence.current += 1; };
  }, [loadEditor, permissions.canWriteModifier, permissions.loading]);

  const activeOptions = useMemo(
    () => groups.flatMap((group) => group.options.filter((option) => option.is_active).sort((a, b) => a.sort_order - b.sort_order)),
    [groups],
  );
  const usedItems = useMemo(() => new Set(optionDraft?.components.map((component) => component.inventoryItemId) ?? []), [optionDraft]);
  const availableItems = useMemo(() => inventoryItems.filter((item) => !usedItems.has(item.id)), [inventoryItems, usedItems]);
  const currency = currentOrganization?.currency_code ?? "KZT";

  useEffect(() => {
    let cancelled = false;
    if (previewStale || !optionDraft?.id || !warehouseId || !accessToken || !currentOrganization || !currentLocation) return;
    const selectedOptionIds = buildPreviewSelection(groups, optionDraft.id);
    if (!selectedOptionIds) return;
    void Promise.resolve().then(() => {
      if (cancelled) return;
      setPreviewLoading(true);
      setPreviewError("");
      void api.previewCustomization(
        variantId,
        selectedOptionIds,
        warehouseId,
        currentLocation.id,
        currentOrganization.id,
        accessToken,
      ).then((nextPreview) => {
        if (!cancelled) setPreview(nextPreview);
      }).catch((caught) => {
        if (!cancelled) {
          setPreview(null);
          setPreviewError(caught instanceof Error ? caught.message : "Unable to calculate customization preview.");
        }
      }).finally(() => {
        if (!cancelled) setPreviewLoading(false);
      });
    });
    return () => { cancelled = true; };
  }, [accessToken, currentLocation, currentOrganization, groups, optionDraft?.id, previewStale, variantId, warehouseId]);

  function selectOption(option: ModifierOption) {
    if (previewStale && !window.confirm("Discard unsaved option changes?")) return;
    setMessage("");
    setError("");
    setOptionDraft(optionToDraft(option, inventoryItems));
    setPreview(null);
    setPreviewStale(false);
    setPreviewError("");
    setComponentPicker("");
  }

  function beginOption(group: ModifierGroup) {
    setOptionDraft({
      id: null,
      groupId: group.id,
      name: "",
      price: "0",
      isDefault: false,
      isAvailable: true,
      locationPrice: "",
      components: [],
    });
    setComponentPicker("");
    setPreview(null);
    setPreviewStale(true);
    setPreviewError("");
  }

  function changeOption(next: OptionDraft) {
    setOptionDraft(next);
    setPreview(null);
    setPreviewStale(true);
    setPreviewError("");
  }

  async function saveGroup(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!groupDraft || !accessToken || !currentOrganization) return;
    const minSelections = Number(groupDraft.minSelections);
    const maxSelections = Number(groupDraft.maxSelections);
    if (!groupDraft.name.trim() || !Number.isInteger(minSelections) || !Number.isInteger(maxSelections) || minSelections < 0 || maxSelections < 1 || minSelections > maxSelections || (groupDraft.selectionType === "SINGLE" && maxSelections !== 1)) {
      setError("Use a name and valid selection limits. Single-choice groups must have a maximum of 1.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const input = {
        name: groupDraft.name.trim(),
        selection_type: groupDraft.selectionType,
        min_selections: minSelections,
        max_selections: maxSelections,
        sort_order: groupDraft.id ? groups.find((group) => group.id === groupDraft.id)?.sort_order ?? 0 : groups.length,
      };
      if (groupDraft.id) {
        await api.updateModifierGroup(groupDraft.id, input, currentOrganization.id, accessToken);
      } else {
        await api.createModifierGroup(variantId, input, currentOrganization.id, accessToken);
      }
      setGroupDraft(null);
      setMessage(groupDraft.id ? "Modifier group saved." : "Modifier group added.");
      await loadEditor(optionDraft?.id ?? undefined);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to save modifier group");
    } finally {
      setSaving(false);
    }
  }

  async function archiveGroup(group: ModifierGroup) {
    if (!accessToken || !currentOrganization || !window.confirm(`Archive ${group.name} and hide its options?`)) return;
    setSaving(true);
    setError("");
    try {
      await api.archiveModifierGroup(group.id, currentOrganization.id, accessToken);
      setMessage(`${group.name} archived.`);
      await loadEditor();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to archive modifier group");
    } finally {
      setSaving(false);
    }
  }

  async function saveOption(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!optionDraft || !accessToken || !currentOrganization || !currentLocation) return;
    const basePriceMinor = parseMenuPriceToMinor(optionDraft.price);
    const locationPriceMinor = optionDraft.locationPrice.trim() ? parseMenuPriceToMinor(optionDraft.locationPrice) : null;
    if (!optionDraft.name.trim() || basePriceMinor === null || (optionDraft.locationPrice.trim() && locationPriceMinor === null)) {
      setError("Use a name and valid non-negative prices with no more than two decimal places.");
      return;
    }
    if (optionDraft.components.some((component) => !isNonZeroSignedMenuDecimal(component.quantityDelta))) {
      setError("Every inventory change must be non-zero and use no more than six decimal places.");
      return;
    }
    setSaving(true);
    setError("");
    setMessage("");
    let savedOptionId = optionDraft.id;
    try {
      const group = groups.find((item) => item.id === optionDraft.groupId);
      const original = activeOptions.find((item) => item.id === optionDraft.id);
      const saved = optionDraft.id
        ? await api.updateModifierOption(optionDraft.id, {
            name: optionDraft.name.trim(),
            base_price_delta_minor: basePriceMinor,
            is_default: optionDraft.isDefault,
          }, currentOrganization.id, accessToken)
        : await api.createModifierOption(optionDraft.groupId, {
            name: optionDraft.name.trim(),
            base_price_delta_minor: basePriceMinor,
            is_default: optionDraft.isDefault,
            sort_order: group?.options.filter((item) => item.is_active).length ?? 0,
          }, currentOrganization.id, accessToken);
      savedOptionId = saved.id;
      await api.setModifierComponents(saved.id, optionDraft.components.map((component, index) => ({
        inventory_item_id: component.inventoryItemId,
        quantity_delta: component.quantityDelta.trim(),
        unit: component.unit,
        sort_order: index,
      })), currentOrganization.id, accessToken);
      if (locationPriceMinor !== null) {
        await api.setModifierLocationPrice(saved.id, currentLocation.id, locationPriceMinor, currentOrganization.id, accessToken);
      } else if (original?.location_price_delta_minor !== null && original?.location_price_delta_minor !== undefined) {
        await api.deleteModifierLocationPrice(saved.id, currentLocation.id, currentOrganization.id, accessToken);
      }
      await api.setModifierLocationAvailability(saved.id, currentLocation.id, optionDraft.isAvailable, currentOrganization.id, accessToken);
      setMessage(`${optionDraft.name.trim()} saved.`);
      await loadEditor(saved.id);
    } catch (caught) {
      const reason = caught instanceof Error ? caught.message : "Unable to save modifier option";
      await loadEditor(savedOptionId ?? undefined);
      setError(`Save did not complete. Server state was reloaded. ${reason}`);
    } finally {
      setSaving(false);
    }
  }

  async function archiveOption() {
    if (!optionDraft?.id || !accessToken || !currentOrganization || !window.confirm(`Archive ${optionDraft.name}?`)) return;
    setSaving(true);
    setError("");
    try {
      await api.archiveModifierOption(optionDraft.id, currentOrganization.id, accessToken);
      setMessage(`${optionDraft.name} archived.`);
      await loadEditor();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to archive modifier option");
    } finally {
      setSaving(false);
    }
  }

  function addComponent() {
    const item = inventoryItems.find((candidate) => candidate.id === componentPicker);
    if (!item || !optionDraft) return;
    changeOption({
      ...optionDraft,
      components: [...optionDraft.components, {
        clientId: crypto.randomUUID(),
        inventoryItemId: item.id,
        quantityDelta: "1",
        unit: item.base_unit,
      }],
    });
    setComponentPicker("");
  }

  if (!permissions.loading && !permissions.canWriteModifier) return <div className="menu-state is-error"><strong>Modifier editing is restricted.</strong><span>Your role does not include modifier management.</span><Link href={`/app/menu/products/${productId}`}>Back to product</Link></div>;
  if (loading || permissions.loading) return <div className="menu-state">Loading modifiers…</div>;
  if (!product || !variant) return <div className="menu-state is-error"><strong>Modifiers could not be loaded.</strong><span>{error}</span><Link href={`/app/menu/products/${productId}`}>Back to product</Link></div>;

  return (
    <>
      <Link className="menu-back-link" href={`/app/menu/products/${product.id}`}><ArrowLeft aria-hidden="true" />{product.name}</Link>
      <header className="menu-header menu-editor-header">
        <div>
          <p className="menu-breadcrumb">Menu / {product.name} / {variant.name} / Modifiers</p>
          <h1>Modifiers</h1>
          <p className="menu-header-copy">Configure customer choices, price changes and recipe effects.</p>
        </div>
      </header>

      {message && <p className="menu-flash" role="status"><Check aria-hidden="true" />{message}</p>}
      {error && <div className="menu-state is-error modifier-alert" role="alert"><strong>Modifiers need attention.</strong><span>{error}</span></div>}

      <div className="modifier-layout">
        <div className="modifier-groups" aria-label="Modifier groups">
          {groupDraft && permissions.canWriteModifier && (
            <form className="modifier-group-form" onSubmit={saveGroup}>
              <div className="menu-section-heading"><div><h2>{groupDraft.id ? "Edit modifier group" : "New modifier group"}</h2><p>Define how many options a customer can choose.</p></div></div>
              <div className="modifier-group-form-grid">
                <label><span>Name</span><input autoFocus maxLength={150} required value={groupDraft.name} onChange={(event) => setGroupDraft({ ...groupDraft, name: event.target.value })} /></label>
                <label><span>Selection type</span><select value={groupDraft.selectionType} onChange={(event) => setGroupDraft({ ...groupDraft, selectionType: event.target.value as ModifierSelectionType, maxSelections: event.target.value === "SINGLE" ? "1" : groupDraft.maxSelections })}><option value="SINGLE">Single</option><option value="MULTIPLE">Multiple</option></select></label>
                <label><span>Minimum</span><input inputMode="numeric" min="0" step="1" value={groupDraft.minSelections} onChange={(event) => setGroupDraft({ ...groupDraft, minSelections: event.target.value })} /></label>
                <label><span>Maximum</span><input disabled={groupDraft.selectionType === "SINGLE"} inputMode="numeric" min="1" step="1" value={groupDraft.maxSelections} onChange={(event) => setGroupDraft({ ...groupDraft, maxSelections: event.target.value })} /></label>
              </div>
              <div className="modifier-form-actions"><button className="menu-secondary-button" type="button" onClick={() => setGroupDraft(null)}>Cancel</button><button className="menu-primary-button" disabled={saving} type="submit"><Save aria-hidden="true" />Save group</button></div>
            </form>
          )}

          {groups.length === 0 && !groupDraft && <div className="menu-state"><strong>No modifier groups yet.</strong><span>Add a group for choices such as milk, extras or preparation.</span></div>}

          {groups.map((group) => {
            const options = group.options.filter((option) => option.is_active).sort((a, b) => a.sort_order - b.sort_order);
            return (
              <section className="modifier-group-card" key={group.id} aria-labelledby={`modifier-group-${group.id}`}>
                <header className="modifier-group-heading">
                  <div><h2 id={`modifier-group-${group.id}`}>{group.name}</h2><span className="modifier-type">{group.selection_type === "SINGLE" ? "Single" : "Multiple"}</span><span>{selectionCopy(group)}</span></div>
                  {permissions.canWriteModifier && <div className="modifier-group-actions"><button className="menu-icon-button" type="button" onClick={() => setGroupDraft({ id: group.id, name: group.name, selectionType: group.selection_type, minSelections: String(group.min_selections), maxSelections: String(group.max_selections) })} aria-label={`Edit ${group.name}`}><MoreHorizontal aria-hidden="true" /></button><button className="menu-icon-button is-danger" disabled={saving} type="button" onClick={() => void archiveGroup(group)} aria-label={`Archive ${group.name}`}><Archive aria-hidden="true" /></button></div>}
                </header>
                <div className="modifier-option-table" role="list">
                  <div className="modifier-option-head" aria-hidden="true"><span>Option</span><span>Price delta</span><span>Available</span><span /></div>
                  {options.map((option) => (
                    <div className={optionDraft?.id === option.id ? "modifier-option-row is-selected" : "modifier-option-row"} role="listitem" key={option.id}>
                      <button className="modifier-option-main" type="button" onClick={() => selectOption(option)} aria-label={`${permissions.canWriteModifier ? "Edit" : "View"} ${option.name}`}><strong>{option.name}{option.is_default && <small>Default</small>}</strong><span>{componentSummary(option, inventoryItems)}</span></button>
                      <strong>{signedPrice(option.effective_price_delta_minor, currency)}</strong>
                      <span className={option.is_available ? "modifier-availability" : "modifier-availability is-off"}><i aria-hidden="true" />{option.is_available ? "This location" : "Unavailable"}</span>
                      <button className="menu-icon-button" type="button" onClick={() => selectOption(option)} aria-label={`${permissions.canWriteModifier ? "Edit" : "View"} ${option.name}`}><MoreHorizontal aria-hidden="true" /></button>
                    </div>
                  ))}
                </div>
                {permissions.canWriteModifier && <button className="modifier-add-button" type="button" onClick={() => beginOption(group)}><Plus aria-hidden="true" />Add option</button>}
              </section>
            );
          })}

          {permissions.canWriteModifier && !groupDraft && <button className="modifier-add-group" type="button" onClick={() => setGroupDraft({ ...EMPTY_GROUP })}><Plus aria-hidden="true" />Add modifier group</button>}
        </div>

        <aside className="modifier-inspector" aria-label="Modifier option editor">
          {!optionDraft ? <div className="modifier-inspector-empty"><strong>Select an option</strong><span>Its price, inventory effect and location settings will appear here.</span></div> : (
            <form onSubmit={saveOption}>
              <header className="modifier-inspector-heading"><button className="menu-icon-button" type="button" onClick={() => { if (!previewStale || window.confirm("Discard unsaved option changes?")) { setOptionDraft(null); setPreviewStale(false); } }} aria-label="Close option editor"><ArrowLeft aria-hidden="true" /></button><h2>{optionDraft.name || "New option"}</h2>{permissions.canWriteModifier && optionDraft.id && <button className="menu-icon-button is-danger" type="button" disabled={saving} onClick={() => void archiveOption()} aria-label={`Archive ${optionDraft.name}`}><Archive aria-hidden="true" /></button>}</header>

              <section className="modifier-inspector-section">
                <label className="modifier-field modifier-full-field"><span>Name</span><input maxLength={150} required disabled={!permissions.canWriteModifier} value={optionDraft.name} onChange={(event) => changeOption({ ...optionDraft, name: event.target.value })} /></label>
                <div className="modifier-option-fields">
                  <label className="modifier-field"><span>Base price delta</span><div className="modifier-money-input"><input inputMode="decimal" disabled={!permissions.canWriteModifier} value={optionDraft.price} onChange={(event) => changeOption({ ...optionDraft, price: event.target.value })} /><span>{currency === "KZT" ? "₸" : currency}</span></div></label>
                  <label className="modifier-check"><span>Default</span><input type="checkbox" disabled={!permissions.canWriteModifier} checked={optionDraft.isDefault} onChange={(event) => changeOption({ ...optionDraft, isDefault: event.target.checked })} /></label>
                </div>
              </section>

              <section className="modifier-inspector-section">
                <h3>Inventory effects</h3>
                {optionDraft.components.length === 0 && <p className="modifier-empty-copy">No recipe change. This option affects price or preparation only.</p>}
                <div className="modifier-component-list">
                  {optionDraft.components.map((component) => {
                    const item = inventoryItems.find((candidate) => candidate.id === component.inventoryItemId);
                    return <div className="modifier-component-row" key={component.clientId}><strong>{item?.name ?? "Inventory item"}</strong><label><span className="sr-only">{item?.name} change</span><input aria-label={`${item?.name ?? "Ingredient"} quantity change`} disabled={!permissions.canWriteModifier} inputMode="decimal" value={component.quantityDelta} onChange={(event) => changeOption({ ...optionDraft, components: optionDraft.components.map((current) => current.clientId === component.clientId ? { ...current, quantityDelta: event.target.value } : current) })} /></label><label><span className="sr-only">{item?.name} unit</span><select aria-label={`${item?.name ?? "Ingredient"} unit`} disabled={!permissions.canWriteModifier} value={component.unit} onChange={(event) => changeOption({ ...optionDraft, components: optionDraft.components.map((current) => current.clientId === component.clientId ? { ...current, unit: event.target.value as InventoryUnitCode } : current) })}>{unitsFor(item?.base_unit ?? component.unit).map((unit) => <option value={unit} key={unit}>{unit === "l" ? "L" : unit}</option>)}</select></label>{permissions.canWriteModifier && <button className="menu-icon-button is-danger" type="button" onClick={() => changeOption({ ...optionDraft, components: optionDraft.components.filter((current) => current.clientId !== component.clientId) })} aria-label={`Remove ${item?.name ?? "inventory item"}`}><Trash2 aria-hidden="true" /></button>}</div>;
                  })}
                </div>
                {permissions.canWriteModifier && <div className="modifier-component-picker"><label><span className="sr-only">Inventory item</span><select value={componentPicker} onChange={(event) => setComponentPicker(event.target.value)}><option value="">Choose inventory item</option>{availableItems.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.base_unit}</option>)}</select></label><button className="menu-secondary-button" type="button" disabled={!componentPicker} onClick={addComponent}><Plus aria-hidden="true" />Add ingredient</button></div>}
              </section>

              <section className="modifier-inspector-section">
                <h3>Location override</h3>
                <div className="modifier-location-row"><div><strong>{currentLocation?.name}</strong><span>{warehouses.find((warehouse) => warehouse.id === warehouseId)?.name ?? "No warehouse"}</span></div><label className="modifier-field"><span>Price delta</span><div className="modifier-money-input"><input inputMode="decimal" disabled={!permissions.canWriteModifier} placeholder="Uses base" value={optionDraft.locationPrice} onChange={(event) => changeOption({ ...optionDraft, locationPrice: event.target.value })} /><span>{currency === "KZT" ? "₸" : currency}</span></div></label><label className="modifier-check"><span>Available</span><input type="checkbox" disabled={!permissions.canWriteModifier} checked={optionDraft.isAvailable} onChange={(event) => changeOption({ ...optionDraft, isAvailable: event.target.checked })} /></label></div>
              </section>

              <section className="modifier-inspector-section modifier-preview">
                <div className="modifier-preview-heading"><h3>Live preview <small>(per item)</small></h3><label><span>Warehouse</span><select value={warehouseId} disabled={warehouses.length === 0} onChange={(event) => { setPreview(null); setWarehouseId(event.target.value); }}>{warehouses.length === 0 && <option value="">No warehouse</option>}{warehouses.map((warehouse) => <option value={warehouse.id} key={warehouse.id}>{warehouse.name}</option>)}</select></label></div>
                <div className="modifier-preview-metrics"><div><span>Final price</span><strong>{previewLoading ? "…" : preview ? formatMenuPriceMinor(preview.final_price_minor, currency) : "—"}</strong></div><div><span>Modifier price</span><strong>{previewLoading ? "…" : preview ? formatMenuPriceMinor(preview.modifier_price_minor, currency) : "—"}</strong></div><div><span>Modifier cost</span><strong>{previewLoading ? "…" : preview ? formatMenuMoney(preview.modifier_cost_delta, currency) : "—"}</strong></div><div><span>Food cost</span><strong>{previewLoading ? "…" : preview ? formatMenuPercent(preview.food_cost_percent) : "—"}</strong></div><div><span>Gross profit</span><strong>{previewLoading ? "…" : preview ? formatMenuMoney(preview.gross_profit, currency) : "—"}</strong></div><div><span>Gross margin</span><strong>{previewLoading ? "…" : preview ? formatMenuPercent(preview.gross_margin_percent) : "—"}</strong></div></div>
                {preview?.status === "INCOMPLETE" && <p className="modifier-preview-warning"><CircleAlert aria-hidden="true" />Cost incomplete{preview.missing_cost_items.length ? `: ${preview.missing_cost_items.join(", ")}` : "."}</p>}
                {previewError && <p className="modifier-preview-warning" role="alert"><CircleAlert aria-hidden="true" />{previewError}</p>}
                {previewStale && optionDraft.id && <p className="modifier-preview-note">Save changes to refresh the authoritative preview.</p>}
              </section>

              {permissions.canWriteModifier && <div className="modifier-save-bar"><button className="menu-primary-button" type="submit" disabled={saving || !optionDraft.name.trim()}><Save aria-hidden="true" />{saving ? "Saving…" : "Save option"}</button></div>}
            </form>
          )}
        </aside>
      </div>
    </>
  );
}

function optionToDraft(option: ModifierOption, inventoryItems: InventoryItemResponse[]): OptionDraft {
  return {
    id: option.id,
    groupId: option.modifier_group_id,
    name: option.name,
    price: priceMinorToInput(option.base_price_delta_minor),
    isDefault: option.is_default,
    isAvailable: option.is_available,
    locationPrice: option.location_price_delta_minor === null ? "" : priceMinorToInput(option.location_price_delta_minor),
    components: option.components.map((component) => ({
      clientId: component.id ?? `${component.inventory_item_id}:${component.sort_order}`,
      inventoryItemId: component.inventory_item_id,
      quantityDelta: component.quantity_delta,
      unit: component.base_unit ?? inventoryItems.find((item) => item.id === component.inventory_item_id)?.base_unit ?? "g",
    })),
  };
}

function selectionCopy(group: ModifierGroup) {
  if (group.min_selections === group.max_selections) return group.min_selections === 1 ? "Choose 1" : `Choose ${group.min_selections}`;
  if (group.min_selections === 0) return `Choose up to ${group.max_selections}`;
  return `Choose ${group.min_selections}–${group.max_selections}`;
}

function componentSummary(option: ModifierOption, items: InventoryItemResponse[]) {
  if (option.components.length === 0) return "No recipe change";
  return option.components.map((component) => {
    const item = items.find((candidate) => candidate.id === component.inventory_item_id);
    const sign = component.quantity_delta.startsWith("-") ? "" : "+";
    return `${sign}${component.quantity_delta} ${item?.base_unit ?? ""} ${item?.name ?? "item"}`;
  }).join(" · ");
}

function signedPrice(value: string, currency: string) {
  return BigInt(value) === BigInt(0) ? formatMenuPriceMinor(value, currency) : `+${formatMenuPriceMinor(value, currency)}`;
}

function buildPreviewSelection(groups: ModifierGroup[], selectedOptionId: string) {
  const selected: string[] = [];
  for (const group of groups) {
    const options = group.options.filter((option) => option.is_active && option.is_available);
    const target = options.find((option) => option.id === selectedOptionId);
    const groupSelection = target ? [target] : options.filter((option) => option.is_default).slice(0, group.max_selections);
    for (const option of options) {
      if (groupSelection.length >= group.min_selections) break;
      if (!groupSelection.some((current) => current.id === option.id)) groupSelection.push(option);
    }
    if (groupSelection.length < group.min_selections || groupSelection.length > group.max_selections) return null;
    selected.push(...groupSelection.map((option) => option.id));
  }
  return selected;
}

function unitsFor(baseUnit: InventoryUnitCode): InventoryUnitCode[] {
  if (baseUnit === "g") return ["g", "kg"];
  if (baseUnit === "ml") return ["ml", "l"];
  return ["pcs"];
}
