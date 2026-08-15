"use client";

import { Archive, Check, Eye, Plus, Save, Sparkles, Trash2, X } from "lucide-react";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { usePromotionPermissions } from "@/hooks/use-promotion-permissions";
import {
  api,
  type Customer,
  type LoyaltyTier,
  type MenuCategory,
  type MenuProduct,
  type Promotion,
  type PromotionApplicationMode,
  type PromotionAudience,
  type PromotionChannel,
  type PromotionDiscountKind,
  type PromotionInput,
  type PromotionPerformance,
  type PromotionPreview,
  type PromotionScope,
  type PromotionTarget,
} from "@/lib/api";
import { formatMenuPriceMinor, parseMenuPriceToMinor, priceMinorToInput } from "@/lib/menu";
import { formatDashboardMoney } from "@/lib/dashboard";

type Draft = Omit<PromotionInput, "amount_minor" | "fixed_price_minor" | "minimum_subtotal_minor" | "maximum_discount_minor"> & {
  amount_minor: string | null;
  fixed_price_minor: string | null;
  minimum_subtotal_minor: string | null;
  maximum_discount_minor: string | null;
};

type BasketLine = { id: string; variant_id: string; quantity: number; modifier_minor: string };
type AudienceDraft = Omit<PromotionAudience, "promotion_id">;

const EMPTY_TARGET: PromotionTarget = { role: "ELIGIBLE", target_type: "ALL", target_id: null, quantity: 1, sort_order: 0 };
const EMPTY_AUDIENCE: AudienceDraft = { kind: "ALL", tier_id: null, customer_ids: [] };
const EMPTY_DRAFT: Draft = {
  name: "", pos_name: "", application_mode: "AUTOMATIC", discount_kind: "PERCENT", scope: "ITEM", percent_rate: "10.0000",
  amount_minor: null, fixed_price_minor: null, priority: 0, stacking_policy: "EXCLUSIVE", include_modifier_price: false,
  minimum_subtotal_minor: null, maximum_discount_minor: null, valid_from: null, valid_to: null, all_locations: true,
  requires_override_permission: false, location_ids: [], schedules: [], targets: [EMPTY_TARGET],
  channels: ["POS"],
};

const PRESETS: Array<{ name: string; description: string; draft: Partial<Draft> }> = [
  { name: "Happy Hour", description: "Timed automatic percentage", draft: { name: "Happy Hour", pos_name: "⚡ Happy Hour -20%", application_mode: "AUTOMATIC", discount_kind: "PERCENT", scope: "ITEM", percent_rate: "20.0000", schedules: [{ weekday: 1, start_local_time: "15:00", end_local_time: "17:00" }] } },
  { name: "Coffee + Croissant", description: "Fixed combo price", draft: { name: "Coffee + Croissant", pos_name: "Coffee + Croissant", application_mode: "AUTOMATIC", discount_kind: "FIXED_PRICE", scope: "COMBO", percent_rate: null, fixed_price_minor: "2500", targets: [{ ...EMPTY_TARGET, role: "COMBO_COMPONENT", target_type: "PRODUCT" }, { ...EMPTY_TARGET, role: "COMBO_COMPONENT", target_type: "PRODUCT", sort_order: 1 }] } },
  { name: "Buy 2 Get 1", description: "Quantity-based offer", draft: { name: "Buy 2 Get 1", pos_name: "Buy 2 Get 1", application_mode: "AUTOMATIC", discount_kind: "BOGO", scope: "ITEM", percent_rate: null, targets: [{ ...EMPTY_TARGET, role: "BUY", target_type: "PRODUCT", quantity: 2 }, { ...EMPTY_TARGET, role: "GET", target_type: "PRODUCT", sort_order: 1 }] } },
  { name: "Friends & Family", description: "Cashier preset", draft: { name: "Friends & Family", pos_name: "Friends & Family 10%", application_mode: "MANUAL", discount_kind: "PERCENT", scope: "ORDER", percent_rate: "10.0000" } },
  { name: "Service Recovery", description: "Manager preset", draft: { name: "Service Recovery", pos_name: "Service Recovery", application_mode: "MANUAL", discount_kind: "FIXED_AMOUNT", scope: "ORDER", percent_rate: null, amount_minor: "500", requires_override_permission: true } },
];

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const CHANNELS: PromotionChannel[] = ["POS", "ONLINE", "QR"];

export default function PromotionsPage() {
  const { accessToken } = useAuth();
  const workspace = useWorkspace();
  const permissions = usePromotionPermissions();
  const [promotions, setPromotions] = useState<Promotion[]>([]);
  const [performance, setPerformance] = useState<PromotionPerformance[]>([]);
  const [categories, setCategories] = useState<MenuCategory[]>([]);
  const [products, setProducts] = useState<MenuProduct[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [tiers, setTiers] = useState<LoyaltyTier[]>([]);
  const [audience, setAudience] = useState<AudienceDraft>(EMPTY_AUDIENCE);
  const [audienceSearch, setAudienceSearch] = useState("");
  const [audienceLoading, setAudienceLoading] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
  const [editing, setEditing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [basket, setBasket] = useState<BasketLine[]>([]);
  const [preview, setPreview] = useState<PromotionPreview | null>(null);
  const [newCode, setNewCode] = useState("");
  const organization = workspace.currentOrganization;
  const currentLocationId = workspace.currentLocation?.id;
  const currency = organization?.currency_code ?? "KZT";

  const load = useCallback(async () => {
    if (!accessToken || !organization) return;
    setLoading(true);
    setError("");
    try {
      const today = new Date();
      const from = new Date(today);
      from.setUTCDate(from.getUTCDate() - 29);
      const [promotionRows, performanceRows, categoryRows, productRows, customerRows, tierRows] = await Promise.all([
        api.listPromotions(organization.id, accessToken),
        api.getPromotionPerformance(from.toISOString().slice(0, 10), today.toISOString().slice(0, 10), organization.id, accessToken, currentLocationId),
        api.listMenuCategories(organization.id, accessToken),
        api.listMenuProducts(organization.id, accessToken),
        api.listCustomers(organization.id, accessToken).catch(() => []),
        api.listLoyaltyTiers(organization.id, accessToken).catch(() => []),
      ]);
      setPromotions(promotionRows);
      setPerformance(performanceRows);
      setCategories(categoryRows);
      setProducts(productRows);
      setCustomers(customerRows);
      setTiers(tierRows);
    } catch (caught) { setError(messageOf(caught)); }
    finally { setLoading(false); }
  }, [accessToken, currentLocationId, organization]);

  useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(() => { if (!cancelled) void load(); });
    return () => { cancelled = true; };
  }, [load]);

  const selected = promotions.find((promotion) => promotion.id === selectedId) ?? null;
  const variants = useMemo(() => products.flatMap((product) => product.variants.map((variant) => ({ product, variant }))), [products]);

  function newPromotion(preset?: Partial<Draft>) {
    setSelectedId(null);
    setAudience(EMPTY_AUDIENCE);
    setAudienceLoading(false);
    setAudienceSearch("");
    setDraft({ ...EMPTY_DRAFT, ...preset, location_ids: preset?.location_ids ?? [], schedules: preset?.schedules?.map((row) => ({ ...row })) ?? [], targets: preset?.targets?.map((row, index) => ({ ...row, sort_order: index })) ?? [EMPTY_TARGET] });
    setBasket([]); setPreview(null); setEditing(true); setError(""); setMessage("");
  }

  function editPromotion(promotion: Promotion) {
    setSelectedId(promotion.id);
    setAudience(EMPTY_AUDIENCE);
    setAudienceLoading(true);
    if (accessToken && organization) void (async () => {
      try {
        const { kind, tier_id, customer_ids } = await api.getPromotionAudience(promotion.id, organization.id, accessToken);
        setAudience({ kind, tier_id, customer_ids });
        if (kind === "CUSTOMER") {
          const selectedCustomers = await Promise.all(customer_ids.slice(0, 50).map((id) => api.getCustomer(id, organization.id, accessToken)));
          setCustomers((current) => [...selectedCustomers, ...current.filter((customer) => !customer_ids.includes(customer.id))]);
        }
      } catch (caught) { setError(messageOf(caught)); }
      finally { setAudienceLoading(false); }
    })();
    else setAudienceLoading(false);
    setDraft({
      name: promotion.name, pos_name: promotion.pos_name, application_mode: promotion.application_mode, discount_kind: promotion.discount_kind,
      scope: promotion.scope, percent_rate: promotion.percent_rate, amount_minor: promotion.amount_minor ? priceMinorToInput(promotion.amount_minor) : null,
      fixed_price_minor: promotion.fixed_price_minor ? priceMinorToInput(promotion.fixed_price_minor) : null, priority: promotion.priority,
      stacking_policy: promotion.stacking_policy, include_modifier_price: promotion.include_modifier_price,
      minimum_subtotal_minor: promotion.minimum_subtotal_minor ? priceMinorToInput(promotion.minimum_subtotal_minor) : null,
      maximum_discount_minor: promotion.maximum_discount_minor ? priceMinorToInput(promotion.maximum_discount_minor) : null,
      valid_from: datetimeLocal(promotion.valid_from), valid_to: datetimeLocal(promotion.valid_to), all_locations: promotion.all_locations,
      requires_override_permission: promotion.requires_override_permission, location_ids: [...promotion.location_ids],
      schedules: promotion.schedules.map(({ weekday, start_local_time, end_local_time }) => ({ weekday, start_local_time: start_local_time.slice(0, 5), end_local_time: end_local_time.slice(0, 5) })),
      targets: promotion.targets.map(({ role, target_type, target_id, quantity, sort_order }) => ({ role, target_type, target_id, quantity, sort_order })),
      channels: [...promotion.channels],
    });
    setPreview(null); setEditing(true); setError(""); setMessage("");
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!accessToken || !organization || !draft.name.trim() || !draft.pos_name.trim()) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const payload: PromotionInput = {
        ...draft, name: draft.name.trim(), pos_name: draft.pos_name.trim(),
        amount_minor: moneyOrNull(draft.amount_minor), fixed_price_minor: moneyOrNull(draft.fixed_price_minor),
        minimum_subtotal_minor: moneyOrNull(draft.minimum_subtotal_minor), maximum_discount_minor: moneyOrNull(draft.maximum_discount_minor),
        valid_from: isoOrNull(draft.valid_from), valid_to: isoOrNull(draft.valid_to),
        targets: draft.targets.map((target, index) => ({ ...target, target_id: target.target_type === "ALL" ? null : target.target_id, sort_order: index })),
      };
      const saved = selectedId
        ? await api.updatePromotion(selectedId, payload, organization.id, accessToken)
        : await api.createPromotion(payload, organization.id, accessToken);
      await api.updatePromotionAudience(saved.id, audience, organization.id, accessToken);
      setSelectedId(saved.id); setMessage(selectedId ? "Promotion updated." : "Draft promotion created.");
      await load(); editPromotion(saved);
    } catch (caught) { setError(messageOf(caught)); }
    finally { setBusy(false); }
  }

  async function changeStatus(action: "activate" | "archive") {
    if (!accessToken || !organization || !selectedId) return;
    setBusy(true); setError("");
    try {
      const next = action === "activate" ? await api.activatePromotion(selectedId, organization.id, accessToken) : await api.archivePromotion(selectedId, organization.id, accessToken);
      setMessage(action === "activate" ? "Promotion activated." : "Promotion archived."); await load(); editPromotion(next);
    } catch (caught) { setError(messageOf(caught)); }
    finally { setBusy(false); }
  }

  async function runPreview() {
    if (!accessToken || !organization || !workspace.currentLocation || !selectedId || basket.length === 0) return;
    setBusy(true); setError("");
    try {
      const items = basket.map((line) => {
        const match = variants.find(({ variant }) => variant.id === line.variant_id)!;
        return { id: line.id, category_id: match.product.category_id, product_id: match.product.id, variant_id: match.variant.id, quantity: line.quantity, base_price_minor: match.variant.effective_price_minor, modifier_price_minor: moneyOrNull(line.modifier_minor) ?? "0" };
      });
      setPreview(await api.previewPromotion(selectedId, { location_id: workspace.currentLocation.id, occurred_at: new Date().toISOString(), items }, organization.id, accessToken));
    } catch (caught) { setError(messageOf(caught)); }
    finally { setBusy(false); }
  }

  async function addCode() {
    if (!accessToken || !organization || !selectedId || !newCode.trim()) return;
    setBusy(true); setError("");
    try { await api.createPromotionCode(selectedId, { code: newCode.trim() }, organization.id, accessToken); setNewCode(""); setMessage("Promo code added."); await load(); }
    catch (caught) { setError(messageOf(caught)); }
    finally { setBusy(false); }
  }

  async function removeCode(codeId: string) {
    if (!accessToken || !organization || !selectedId) return;
    setBusy(true); setError("");
    try { await api.deletePromotionCode(selectedId, codeId, organization.id, accessToken); setMessage("Promo code removed."); await load(); }
    catch (caught) { setError(messageOf(caught)); }
    finally { setBusy(false); }
  }

  async function searchAudienceCustomers() {
    if (!accessToken || !organization) return;
    setBusy(true); setError("");
    try {
      const matches = await api.listCustomers(organization.id, accessToken, { search: audienceSearch.trim() || undefined });
      setCustomers((current) => [...current.filter((customer) => audience.customer_ids.includes(customer.id)), ...matches.filter((customer) => !audience.customer_ids.includes(customer.id))]);
    }
    catch (caught) { setError(messageOf(caught)); }
    finally { setBusy(false); }
  }

  if (!permissions.loading && !permissions.canRead) return <div className="menu-state"><strong>Promotions access restricted</strong><span>Your role cannot view promotions.</span></div>;

  return (
    <>
      <header className="menu-header"><div><p className="menu-breadcrumb">Sales / Promotions</p><h1>Promotions</h1><p className="menu-header-copy">Control the final price without changing menu prices.</p></div>
        {!permissions.loading && permissions.canWrite && <button className="menu-primary-button" type="button" onClick={() => newPromotion()}><Plus />New promotion</button>}
      </header>
      {message && <p className="menu-flash" role="status"><Check />{message}</p>}
      {error && <div className="menu-state is-error" role="alert"><strong>Promotion could not be updated.</strong><span>{error}</span></div>}

      {!editing && permissions.canWrite && <section className="promotion-presets" aria-labelledby="preset-title"><div className="menu-section-heading"><div><h2 id="preset-title">Quick templates</h2><p>Templates only prefill the builder; every rule remains editable.</p></div></div><div>{PRESETS.map((preset) => <button key={preset.name} type="button" onClick={() => newPromotion(preset.draft)}><Sparkles /><strong>{preset.name}</strong><span>{preset.description}</span></button>)}</div></section>}

      {!editing && (loading ? <div className="menu-state">Loading promotions…</div> : promotions.length === 0 ? <div className="menu-state"><strong>No promotions yet</strong><span>Start from a quick template or create a blank promotion.</span></div> : <section className="promotion-list" aria-label="Promotions">{promotions.map((promotion) => <button key={promotion.id} type="button" onClick={() => editPromotion(promotion)}><span><strong>{promotion.name}</strong><small>{promotion.pos_name}</small></span><span>{kindLabel(promotion.discount_kind, promotion)}</span><span>{promotion.application_mode}</span><span className={`menu-status status-${promotion.status.toLowerCase()}`}>{promotion.status}</span></button>)}</section>)}

      {!editing && performance.length > 0 && <section className="dashboard-panel"><header><h2>Promotion performance</h2><span>Last 30 days</span></header><div className="dashboard-table-wrap"><table><thead><tr><th>Promotion</th><th>Orders</th><th>Applications</th><th>Items</th><th>Eligible gross</th><th>Discount</th><th>Net</th><th>Refunds</th></tr></thead><tbody>{performance.map((row) => <tr key={row.promotion_id}><th scope="row">{row.promotion_name}</th><td>{row.orders_count}</td><td>{row.applications_count}</td><td>{row.items_count}</td><td>{formatDashboardMoney(row.gross_eligible_amount, currency)}</td><td>−{formatDashboardMoney(row.discount_amount, currency)}</td><td>{formatDashboardMoney(row.net_revenue_amount, currency)}</td><td>−{formatDashboardMoney(row.refund_amount, currency)}</td></tr>)}</tbody></table></div></section>}

      {editing && <form className="promotion-builder" onSubmit={save}>
        <header><div><button className="menu-back-link" type="button" onClick={() => setEditing(false)}>← All promotions</button><h2>{selected ? selected.name : "New promotion"}</h2>{selected && <span className={`menu-status status-${selected.status.toLowerCase()}`}>{selected.status}</span>}</div><div>{selected?.status === "ACTIVE" && <button className="menu-danger-button" disabled={busy} type="button" onClick={() => void changeStatus("archive")}><Archive />Archive</button>}<button className="menu-primary-button" disabled={busy || audienceLoading || !permissions.canWrite || (audience.kind === "CUSTOMER" && audience.customer_ids.length === 0)} type="submit"><Save />{busy || audienceLoading ? "Saving…" : "Save draft"}</button></div></header>

        <div className="promotion-builder-grid">
          <div className="promotion-form-stack">
            <BuilderSection title="Basics"><div className="promotion-fields two"><Field label="Name"><input required maxLength={150} value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} /></Field><Field label="POS name"><input required maxLength={80} value={draft.pos_name} onChange={(event) => setDraft({ ...draft, pos_name: event.target.value })} /></Field><Select label="Apply" value={draft.application_mode} values={["AUTOMATIC", "MANUAL", "CODE"]} onChange={(value) => setDraft({ ...draft, application_mode: value as PromotionApplicationMode })} /><Select label="Scope" value={draft.scope} values={["ITEM", "ORDER", "COMBO"]} onChange={(value) => setDraft({ ...draft, scope: value as PromotionScope })} /></div><fieldset className="promotion-options"><legend>Eligible channels</legend>{CHANNELS.map((channel) => <label key={channel}><input type="checkbox" checked={draft.channels.includes(channel)} disabled={draft.channels.length === 1 && draft.channels[0] === channel} onChange={(event) => setDraft({ ...draft, channels: event.target.checked ? [...draft.channels, channel] : draft.channels.filter((value) => value !== channel) })} />{channel}</label>)}</fieldset></BuilderSection>
            <BuilderSection title="Discount"><div className="promotion-fields two"><Select label="Type" value={draft.discount_kind} values={["PERCENT", "FIXED_AMOUNT", "FIXED_PRICE", "BOGO"]} onChange={(value) => setDraft({ ...draft, discount_kind: value as PromotionDiscountKind })} />{draft.discount_kind === "PERCENT" && <Field label="Percent"><input required min="0" max="100" step="0.0001" type="number" value={draft.percent_rate ?? ""} onChange={(event) => setDraft({ ...draft, percent_rate: event.target.value })} /></Field>}{draft.discount_kind === "FIXED_AMOUNT" && <MoneyField label="Amount" value={draft.amount_minor} onChange={(value) => setDraft({ ...draft, amount_minor: value })} />}{draft.discount_kind === "FIXED_PRICE" && <MoneyField label="Fixed price" value={draft.fixed_price_minor} onChange={(value) => setDraft({ ...draft, fixed_price_minor: value })} />}<Field label="Priority"><input type="number" value={draft.priority} onChange={(event) => setDraft({ ...draft, priority: Number(event.target.value) })} /></Field><Select label="Stacking" value={draft.stacking_policy} values={["EXCLUSIVE", "STACKABLE"]} onChange={(value) => setDraft({ ...draft, stacking_policy: value as Draft["stacking_policy"] })} /><MoneyField label="Minimum subtotal" optional value={draft.minimum_subtotal_minor} onChange={(value) => setDraft({ ...draft, minimum_subtotal_minor: value })} /><MoneyField label="Maximum discount" optional value={draft.maximum_discount_minor} onChange={(value) => setDraft({ ...draft, maximum_discount_minor: value })} /></div><label className="promotion-check"><input type="checkbox" checked={draft.include_modifier_price} onChange={(event) => setDraft({ ...draft, include_modifier_price: event.target.checked })} />Include modifier price in eligible amount</label><label className="promotion-check"><input type="checkbox" checked={draft.requires_override_permission} onChange={(event) => setDraft({ ...draft, requires_override_permission: event.target.checked })} />Require discount override permission</label></BuilderSection>
            <BuilderSection title="Products"><div className="promotion-targets">{draft.targets.map((target, index) => <div key={index}><Select label="Role" value={target.role} values={["ELIGIBLE", "BUY", "GET", "COMBO_COMPONENT"]} onChange={(value) => updateTarget(index, { role: value as PromotionTarget["role"] })} /><Select label="Target" value={target.target_type} values={["ALL", "CATEGORY", "PRODUCT", "VARIANT"]} onChange={(value) => updateTarget(index, { target_type: value as PromotionTarget["target_type"], target_id: null })} />{target.target_type !== "ALL" && <Field label={target.target_type.toLowerCase()}><select required value={target.target_id ?? ""} onChange={(event) => updateTarget(index, { target_id: event.target.value })}><option value="">Select</option>{targetOptions(target.target_type, categories, products).map((option) => <option key={option.id} value={option.id}>{option.name}</option>)}</select></Field>}<Field label="Qty"><input min="1" type="number" value={target.quantity} onChange={(event) => updateTarget(index, { quantity: Number(event.target.value) })} /></Field><button aria-label="Remove target" className="menu-icon-button is-danger" disabled={draft.targets.length === 1} type="button" onClick={() => setDraft({ ...draft, targets: draft.targets.filter((_, row) => row !== index) })}><Trash2 /></button></div>)}</div><button className="menu-secondary-button" type="button" onClick={() => setDraft({ ...draft, targets: [...draft.targets, { ...EMPTY_TARGET, sort_order: draft.targets.length }] })}><Plus />Add target</button></BuilderSection>
            <BuilderSection title="Customer audience"><Select label="Eligible customers" value={audience.kind} values={["ALL", "CUSTOMER", "TIER", "BIRTHDAY"]} onChange={(value) => setAudience({ kind: value as AudienceDraft["kind"], tier_id: null, customer_ids: [] })} />{audience.kind === "TIER" && <Field label="Tier"><select required value={audience.tier_id ?? ""} onChange={(event) => setAudience({ ...audience, tier_id: event.target.value || null })}><option value="">Select tier</option>{tiers.map((tier) => <option key={tier.id} value={tier.id}>{tier.name}</option>)}</select></Field>}{audience.kind === "CUSTOMER" && <><div className="promotion-code-form"><input aria-label="Search customers" placeholder="Phone or name" value={audienceSearch} onChange={(event) => setAudienceSearch(event.target.value)} /><button className="menu-secondary-button" disabled={busy} type="button" onClick={() => void searchAudienceCustomers()}>Search</button></div><p className="promotion-audience-note">{audience.customer_ids.length} selected</p><div className="promotion-audience-list">{customers.map((customer) => <label key={customer.id}><input type="checkbox" checked={audience.customer_ids.includes(customer.id)} onChange={(event) => setAudience({ ...audience, customer_ids: event.target.checked ? [...audience.customer_ids, customer.id] : audience.customer_ids.filter((id) => id !== customer.id) })} /><span><strong>{customerName(customer)}</strong><small>{customer.phone}</small></span></label>)}{customers.length === 0 && <small>No customers found.</small>}</div></>}{audience.kind === "BIRTHDAY" && <p className="promotion-audience-note">Applied automatically on the customer’s birthday.</p>}</BuilderSection>
            <BuilderSection title="Availability"><div className="promotion-fields two"><Field label="Valid from" optional><input type="datetime-local" value={draft.valid_from ?? ""} onChange={(event) => setDraft({ ...draft, valid_from: event.target.value || null })} /></Field><Field label="Valid to" optional><input type="datetime-local" value={draft.valid_to ?? ""} onChange={(event) => setDraft({ ...draft, valid_to: event.target.value || null })} /></Field></div><label className="promotion-check"><input type="checkbox" checked={draft.all_locations} onChange={(event) => setDraft({ ...draft, all_locations: event.target.checked, location_ids: event.target.checked ? [] : draft.location_ids })} />All locations</label>{!draft.all_locations && <div className="promotion-options">{workspace.locations.map((location) => <label key={location.id}><input type="checkbox" checked={draft.location_ids.includes(location.id)} onChange={(event) => setDraft({ ...draft, location_ids: event.target.checked ? [...draft.location_ids, location.id] : draft.location_ids.filter((id) => id !== location.id) })} />{location.name}</label>)}</div>}<div className="promotion-schedules">{draft.schedules.map((schedule, index) => <div key={index}><Select label="Day" value={String(schedule.weekday)} values={WEEKDAYS.map((_, day) => String(day))} labels={WEEKDAYS} onChange={(value) => updateSchedule(index, { weekday: Number(value) })} /><Field label="Start"><input required type="time" value={schedule.start_local_time} onChange={(event) => updateSchedule(index, { start_local_time: event.target.value })} /></Field><Field label="End"><input required type="time" value={schedule.end_local_time} onChange={(event) => updateSchedule(index, { end_local_time: event.target.value })} /></Field><button aria-label="Remove schedule" className="menu-icon-button is-danger" type="button" onClick={() => setDraft({ ...draft, schedules: draft.schedules.filter((_, row) => row !== index) })}><Trash2 /></button></div>)}</div><button className="menu-secondary-button" type="button" onClick={() => setDraft({ ...draft, schedules: [...draft.schedules, { weekday: 0, start_local_time: "15:00", end_local_time: "17:00" }] })}><Plus />Add time range</button></BuilderSection>
            {selected && draft.application_mode === "CODE" && <BuilderSection title="Promo codes"><div className="promotion-code-form"><input aria-label="Promo code" maxLength={64} placeholder="BEANLY10" value={newCode} onChange={(event) => setNewCode(event.target.value.toUpperCase())} /><button className="menu-secondary-button" disabled={busy || !newCode.trim()} type="button" onClick={() => void addCode()}>Add code</button></div><div className="promotion-code-list">{selected.codes.map((code) => <span key={code.id}>{code.code}<button aria-label={`Remove ${code.code}`} disabled={busy} type="button" onClick={() => void removeCode(code.id)}><X /></button></span>)}</div></BuilderSection>}
          </div>

          <aside className="promotion-preview"><div className="menu-section-heading"><div><h2>Preview</h2><p>Build a fake basket before activation.</p></div><Eye /></div>{basket.map((line, index) => <div className="promotion-basket-line" key={line.id}><select value={line.variant_id} onChange={(event) => updateBasket(index, { variant_id: event.target.value })}><option value="">Select product</option>{variants.map(({ product, variant }) => <option key={variant.id} value={variant.id}>{product.name} · {variant.name}</option>)}</select><input aria-label="Quantity" min="1" type="number" value={line.quantity} onChange={(event) => updateBasket(index, { quantity: Number(event.target.value) })} /><input aria-label="Modifier amount" min="0" step="0.01" type="number" placeholder="Modifier" value={line.modifier_minor} onChange={(event) => updateBasket(index, { modifier_minor: event.target.value })} /><button aria-label="Remove basket item" className="menu-icon-button" type="button" onClick={() => setBasket(basket.filter((_, row) => row !== index))}><X /></button></div>)}<button className="menu-secondary-button" type="button" onClick={() => setBasket([...basket, { id: crypto.randomUUID(), variant_id: variants[0]?.variant.id ?? "", quantity: 1, modifier_minor: "" }])}><Plus />Add basket item</button><button className="menu-primary-button" disabled={busy || !selectedId || basket.length === 0 || basket.some((line) => !line.variant_id)} type="button" onClick={() => void runPreview()}><Eye />Preview price</button>{!selectedId && <p className="promotion-preview-hint">Save the draft before previewing.</p>}{preview && <dl className="promotion-preview-result"><div><dt>Gross</dt><dd>{formatMenuPriceMinor(preview.subtotal_minor, currency)}</dd></div><div><dt>{selected?.name ?? "Promotion"}</dt><dd>−{formatMenuPriceMinor(preview.discount_total_minor, currency)}</dd></div><div><dt>Final</dt><dd>{formatMenuPriceMinor(preview.total_minor, currency)}</dd></div><p>You save {formatMenuPriceMinor(preview.discount_total_minor, currency)}</p></dl>}{selected?.status === "DRAFT" && <button className="menu-primary-button" disabled={busy || !permissions.canWrite} type="button" onClick={() => void changeStatus("activate")}><Check />Activate</button>}</aside>
        </div>
      </form>}
    </>
  );

  function updateTarget(index: number, patch: Partial<PromotionTarget>) { setDraft({ ...draft, targets: draft.targets.map((target, row) => row === index ? { ...target, ...patch } : target) }); }
  function updateSchedule(index: number, patch: Partial<Draft["schedules"][number]>) { setDraft({ ...draft, schedules: draft.schedules.map((schedule, row) => row === index ? { ...schedule, ...patch } : schedule) }); }
  function updateBasket(index: number, patch: Partial<BasketLine>) { setBasket(basket.map((line, row) => row === index ? { ...line, ...patch } : line)); }
}

function BuilderSection({ title, children }: { title: string; children: React.ReactNode }) { return <section className="promotion-builder-section"><h3>{title}</h3>{children}</section>; }
function Field({ label, optional, children }: { label: string; optional?: boolean; children: React.ReactNode }) { return <label className="promotion-field"><span>{label}{optional && <small>Optional</small>}</span>{children}</label>; }
function Select({ label, value, values, labels, onChange }: { label: string; value: string; values: string[]; labels?: string[]; onChange: (value: string) => void }) { return <Field label={label}><select value={value} onChange={(event) => onChange(event.target.value)}>{values.map((option, index) => <option key={option} value={option}>{labels?.[index] ?? option.replaceAll("_", " ")}</option>)}</select></Field>; }
function MoneyField({ label, value, optional, onChange }: { label: string; value: string | null; optional?: boolean; onChange: (value: string | null) => void }) { return <Field label={label} optional={optional}><input min="0" step="0.01" type="number" required={!optional} value={value ?? ""} onChange={(event) => onChange(event.target.value || null)} /></Field>; }
function moneyOrNull(value: string | null) { return value?.trim() ? parseMenuPriceToMinor(value) : null; }
function isoOrNull(value: string | null) { return value ? new Date(value).toISOString() : null; }
function datetimeLocal(value: string | null) { return value ? new Date(value).toISOString().slice(0, 16) : null; }
function messageOf(error: unknown) { return error instanceof Error ? error.message : "Something went wrong. Please try again."; }
function customerName(customer: Customer) { return [customer.first_name, customer.last_name].filter(Boolean).join(" ") || customer.phone; }
function kindLabel(kind: PromotionDiscountKind, promotion: Promotion) { if (kind === "PERCENT") return `${promotion.percent_rate?.replace(/\.0+$/, "")}%`; if (kind === "FIXED_AMOUNT") return `−${promotion.amount_minor}`; if (kind === "FIXED_PRICE") return `Fixed ${promotion.fixed_price_minor}`; return "BOGO"; }
function targetOptions(type: PromotionTarget["target_type"], categories: MenuCategory[], products: MenuProduct[]) { if (type === "CATEGORY") return categories.map(({ id, name }) => ({ id, name })); if (type === "PRODUCT") return products.map(({ id, name }) => ({ id, name })); if (type === "VARIANT") return products.flatMap((product) => product.variants.map((variant) => ({ id: variant.id, name: `${product.name} · ${variant.name}` }))); return []; }
