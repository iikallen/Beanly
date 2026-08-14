"use client";

import { Cake, Check, ChevronLeft, Plus, Search, Settings, UserRound, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import {
  api,
  type Customer,
  type CustomerInput,
  type CustomerLoyalty,
  type CustomerOrder,
  type LoyaltyProgram,
  type LoyaltyTier,
  type LoyaltyTierInput,
} from "@/lib/api";
import { formatMenuPriceMinor, parseMenuPriceToMinor, priceMinorToInput } from "@/lib/menu";

type View = "customers" | "loyalty";
type CustomerDraft = { phone: string; first_name: string; last_name: string; email: string; birth_date: string; note: string; marketing_consent: boolean };

const EMPTY_CUSTOMER: CustomerDraft = { phone: "", first_name: "", last_name: "", email: "", birth_date: "", note: "", marketing_consent: false };

export default function CustomersPage() {
  const { accessToken } = useAuth();
  const { currentOrganization } = useWorkspace();
  const organizationId = currentOrganization?.id;
  const currency = currentOrganization?.currency_code ?? "KZT";
  const [permissions, setPermissions] = useState<string[]>([]);
  const [view, setView] = useState<View>("customers");
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [selected, setSelected] = useState<Customer | null>(null);
  const [orders, setOrders] = useState<CustomerOrder[]>([]);
  const [loyalty, setLoyalty] = useState<CustomerLoyalty | null>(null);
  const [program, setProgram] = useState<LoyaltyProgram | null>(null);
  const [tiers, setTiers] = useState<LoyaltyTier[]>([]);
  const [query, setQuery] = useState("");
  const [customerDraft, setCustomerDraft] = useState<CustomerDraft | null>(null);
  const [adjustment, setAdjustment] = useState({ points: "", reason: "" });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const scopeRef = useRef({ accessToken, organizationId });

  const canRead = permissions.includes("customers.read");
  const canWrite = permissions.includes("customers.write");
  const canReadLoyalty = permissions.includes("loyalty.read");
  const canAdjust = permissions.includes("loyalty.adjust");
  const canConfigure = permissions.includes("loyalty.configure");

  const load = useCallback(async (search?: string) => {
    if (!accessToken || !organizationId) { setLoading(false); return; }
    const scope = { accessToken, organizationId };
    const isCurrentScope = () => scopeRef.current.accessToken === scope.accessToken && scopeRef.current.organizationId === scope.organizationId;
    setLoading(true); setError("");
    try {
      const context = await api.getOrganizationContext(organizationId, accessToken);
      setPermissions(context.permissions);
      const readsCustomers = context.permissions.includes("customers.read");
      const readsLoyalty = context.permissions.includes("loyalty.read");
      const [customerRows, tierRows, loyaltyProgram] = await Promise.all([
        readsCustomers ? api.listCustomers(organizationId, accessToken, { search: search?.trim() || undefined }) : Promise.resolve([]),
        readsLoyalty ? api.listLoyaltyTiers(organizationId, accessToken) : Promise.resolve([]),
        readsLoyalty ? api.getLoyaltyProgram(organizationId, accessToken).catch(() => null) : Promise.resolve(null),
      ]);
      if (!isCurrentScope()) return;
      setCustomers(customerRows); setTiers(tierRows); setProgram(loyaltyProgram);
    } catch (caught) { if (isCurrentScope()) setError(messageOf(caught)); }
    finally { if (isCurrentScope()) setLoading(false); }
  }, [accessToken, organizationId]);

  useEffect(() => {
    scopeRef.current = { accessToken, organizationId };
    let cancelled = false;
    Promise.resolve().then(() => {
      if (cancelled) return;
      setPermissions([]); setCustomers([]); setSelected(null); setOrders([]); setLoyalty(null); setProgram(null); setTiers([]);
      setCustomerDraft(null); setAdjustment({ points: "", reason: "" }); setError(""); setMessage(""); setView("customers"); void load();
    });
    return () => { cancelled = true; };
  }, [accessToken, load, organizationId]);

  async function openCustomer(customer: Customer) {
    if (!accessToken || !organizationId) return;
    setSelected(customer); setOrders([]); setLoyalty(null); setBusy(true); setError("");
    try {
      const [profile, history, balance] = await Promise.all([
        api.getCustomer(customer.id, organizationId, accessToken),
        api.listCustomerOrders(customer.id, organizationId, accessToken),
        canReadLoyalty ? api.getCustomerLoyalty(customer.id, organizationId, accessToken) : Promise.resolve(null),
      ]);
      setSelected(profile); setOrders(history); setLoyalty(balance);
    } catch (caught) { setError(messageOf(caught)); }
    finally { setBusy(false); }
  }

  async function saveCustomer(draft: CustomerDraft) {
    if (!accessToken || !organizationId) return;
    setBusy(true); setError("");
    try {
      const input: CustomerInput = {
        phone: draft.phone.trim(), first_name: valueOrNull(draft.first_name), last_name: valueOrNull(draft.last_name),
        email: valueOrNull(draft.email), birth_date: valueOrNull(draft.birth_date), note: valueOrNull(draft.note),
        marketing_consent: draft.marketing_consent,
      };
      const saved = selected
        ? await api.updateCustomer(selected.id, input, organizationId, accessToken)
        : await api.createCustomer(input, organizationId, accessToken);
      setCustomerDraft(null); setMessage(selected ? "Customer updated." : "Customer created.");
      await load(query); await openCustomer(saved);
    } catch (caught) { setError(messageOf(caught)); }
    finally { setBusy(false); }
  }

  async function adjustPoints() {
    if (!accessToken || !organizationId || !selected || !adjustment.points || !adjustment.reason.trim()) return;
    setBusy(true); setError("");
    try {
      const next = await api.adjustCustomerLoyalty(selected.id, { client_adjustment_id: crypto.randomUUID(), points_delta: adjustment.points.replace(/^\+/, ""), reason: adjustment.reason.trim() }, organizationId, accessToken);
      setLoyalty(next); setAdjustment({ points: "", reason: "" }); setMessage("Points adjusted.");
      setSelected(await api.getCustomer(selected.id, organizationId, accessToken));
    } catch (caught) { setError(messageOf(caught)); }
    finally { setBusy(false); }
  }

  async function archiveCustomer() {
    if (!accessToken || !organizationId || !selected || !canWrite) return;
    if (!window.confirm(`Archive ${customerName(selected)}? The profile will no longer appear in the customer directory.`)) return;
    const customerId = selected.id;
    setBusy(true); setError("");
    try {
      await api.archiveCustomer(customerId, organizationId, accessToken);
      setCustomers((current) => current.filter((customer) => customer.id !== customerId));
      setSelected(null); setOrders([]); setLoyalty(null); setCustomerDraft(null); setMessage("Customer archived.");
    } catch (caught) { setError(messageOf(caught)); }
    finally { setBusy(false); }
  }

  if (!loading && !canRead) return <div className="menu-state"><strong>Customer access restricted</strong><span>Your role cannot view customer profiles.</span></div>;

  return (
    <>
      <header className="menu-header"><div><p className="menu-breadcrumb">Sales / CRM</p><h1>Customers</h1><p className="menu-header-copy">Customer history and loyalty without storing personal data on offline POS devices.</p></div>{view === "customers" && !selected && canWrite && <button className="menu-primary-button" type="button" onClick={() => setCustomerDraft(EMPTY_CUSTOMER)}><Plus />New customer</button>}</header>
      <div className="customer-tabs" role="tablist"><button className={view === "customers" ? "is-active" : ""} type="button" onClick={() => setView("customers")}><UserRound />Customers</button>{canReadLoyalty && <button className={view === "loyalty" ? "is-active" : ""} type="button" onClick={() => { setSelected(null); setView("loyalty"); }}><Settings />Loyalty program</button>}</div>
      {message && <p className="menu-flash" role="status"><Check />{message}</p>}
      {error && <div className="menu-state is-error" role="alert"><strong>Customer operation failed.</strong><span>{error}</span></div>}

      {view === "customers" && !selected && <>
        <form className="customer-search" onSubmit={(event) => { event.preventDefault(); void load(query); }}><Search /><input aria-label="Search customers" placeholder="Phone or name" value={query} onChange={(event) => setQuery(event.target.value)} /><button className="menu-secondary-button" disabled={loading} type="submit">Search</button></form>
        {loading ? <div className="menu-state">Loading customers…</div> : customers.length === 0 ? <div className="menu-state"><strong>No customers found</strong><span>Create a profile or search by another phone number.</span></div> : <div className="customer-table-wrap"><table><thead><tr><th>Customer</th><th>Phone</th><th>Tier</th><th>Visits</th><th>LTV</th><th>Last visit</th></tr></thead><tbody>{customers.map((customer) => <tr key={customer.id}><th scope="row"><button className="customer-open" type="button" onClick={() => void openCustomer(customer)}>{customerName(customer)}{customer.birth_date && <small>{birthdayLabel(customer.birth_date)}</small>}</button></th><td>{customer.phone}</td><td>{customer.tier?.name ?? "—"}</td><td>{customer.visit_count}</td><td>{formatMenuPriceMinor(customer.lifetime_value_minor, currency)}</td><td>{dateTime(customer.last_visit_at)}</td></tr>)}</tbody></table></div>}
      </>}

      {view === "customers" && selected && <CustomerProfile customer={selected} orders={orders} loyalty={loyalty} currency={currency} busy={busy} canWrite={canWrite} canAdjust={canAdjust} adjustment={adjustment} onAdjustment={setAdjustment} onAdjust={() => void adjustPoints()} onBack={() => { setSelected(null); setOrders([]); setLoyalty(null); }} onEdit={() => setCustomerDraft(customerToDraft(selected))} onArchive={() => void archiveCustomer()} />}
      {view === "loyalty" && canReadLoyalty && <LoyaltySettings program={program} tiers={tiers} currency={currency} canConfigure={canConfigure} busy={busy} onProgram={async (next) => { if (!accessToken || !organizationId) return; setBusy(true); setError(""); try { setProgram(await api.updateLoyaltyProgram(next, organizationId, accessToken)); setMessage("Loyalty program updated."); } catch (caught) { setError(messageOf(caught)); } finally { setBusy(false); } }} onTier={async (tierId, input) => { if (!accessToken || !organizationId) return; setBusy(true); setError(""); try { if (tierId) await api.updateLoyaltyTier(tierId, input, organizationId, accessToken); else await api.createLoyaltyTier(input, organizationId, accessToken); setTiers(await api.listLoyaltyTiers(organizationId, accessToken)); setMessage(tierId ? "Tier updated." : "Tier created."); } catch (caught) { setError(messageOf(caught)); } finally { setBusy(false); } }} />}
      {customerDraft && <CustomerModal draft={customerDraft} busy={busy} title={selected ? "Edit customer" : "New customer"} onClose={() => setCustomerDraft(null)} onSave={saveCustomer} />}
    </>
  );
}

function CustomerProfile({ customer, orders, loyalty, currency, busy, canWrite, canAdjust, adjustment, onAdjustment, onAdjust, onBack, onEdit, onArchive }: { customer: Customer; orders: CustomerOrder[]; loyalty: CustomerLoyalty | null; currency: string; busy: boolean; canWrite: boolean; canAdjust: boolean; adjustment: { points: string; reason: string }; onAdjustment: (value: { points: string; reason: string }) => void; onAdjust: () => void; onBack: () => void; onEdit: () => void; onArchive: () => void }) {
  return <div className="customer-profile"><header><button className="menu-back-link" type="button" onClick={onBack}><ChevronLeft />All customers</button><div><span className="customer-avatar">{customerName(customer).charAt(0)}</span><div><h2>{customerName(customer)}</h2><p>{customer.phone}{customer.email ? ` · ${customer.email}` : ""}</p></div></div>{canWrite && <div className="customer-profile-actions"><button className="menu-secondary-button" disabled={busy} type="button" onClick={onEdit}>Edit profile</button><button className="menu-secondary-button" disabled={busy} type="button" onClick={onArchive}>Archive customer</button></div>}</header><div className="customer-metrics"><article><span>Lifetime value</span><strong>{formatMenuPriceMinor(customer.lifetime_value_minor, currency)}</strong></article><article><span>Visits</span><strong>{customer.visit_count}</strong></article><article><span>Points</span><strong>{formatPoints(customer.loyalty_points_balance)}</strong></article><article><span>Tier</span><strong>{customer.tier?.name ?? "—"}</strong></article></div><div className="customer-profile-grid"><section className="customer-card"><h3>Profile</h3><dl><div><dt>Birthday</dt><dd>{customer.birth_date ? <><Cake />{birthdayLabel(customer.birth_date)}</> : "Not set"}</dd></div><div><dt>Last visit</dt><dd>{dateTime(customer.last_visit_at)}</dd></div><div><dt>Marketing</dt><dd>{customer.marketing_consent ? "Consent granted" : "No consent"}</dd></div><div><dt>Note</dt><dd>{customer.note ?? "—"}</dd></div></dl></section>{loyalty && <section className="customer-card"><h3>Loyalty</h3><dl><div><dt>Available</dt><dd>{formatPoints(loyalty.available_points)} points</dd></div><div><dt>Lifetime earned</dt><dd>{formatPoints(loyalty.lifetime_earned_points)}</dd></div><div><dt>Point value</dt><dd>{formatMenuPriceMinor(loyalty.point_value_minor, currency)}</dd></div><div><dt>Earn rate</dt><dd>{percent(loyalty.earn_rate_bps)}</dd></div></dl>{canAdjust && <div className="customer-adjust"><input aria-label="Points adjustment" inputMode="numeric" placeholder="+100 or -50" value={adjustment.points} onChange={(event) => onAdjustment({ ...adjustment, points: event.target.value })} /><input aria-label="Adjustment reason" maxLength={1000} placeholder="Reason" value={adjustment.reason} onChange={(event) => onAdjustment({ ...adjustment, reason: event.target.value })} /><button className="menu-secondary-button" disabled={busy || !/^[+-]?\d+$/.test(adjustment.points) || BigInt(adjustment.points || "0") === BigInt(0) || !adjustment.reason.trim()} type="button" onClick={onAdjust}>Adjust</button></div>}</section>}</div><section className="customer-card customer-wide"><h3>Order history</h3>{orders.length === 0 ? <p className="customer-empty">No paid orders yet.</p> : <div className="customer-table-wrap"><table><thead><tr><th>Order</th><th>Paid</th><th>Total</th><th>Refunded</th><th>Net</th></tr></thead><tbody>{orders.map((order) => <tr key={order.id}><th scope="row">#{order.number}</th><td>{dateTime(order.paid_at)}</td><td>{formatMenuPriceMinor(order.total_minor, currency)}</td><td>{formatMenuPriceMinor(order.refunded_minor, currency)}</td><td>{formatMenuPriceMinor(order.net_minor, currency)}</td></tr>)}</tbody></table></div>}</section>{loyalty && <section className="customer-card customer-wide"><h3>Points ledger</h3>{loyalty.entries.length === 0 ? <p className="customer-empty">No points activity yet.</p> : <div className="customer-table-wrap"><table><thead><tr><th>Date</th><th>Activity</th><th>Reason</th><th>Points</th></tr></thead><tbody>{loyalty.entries.map((entry) => <tr key={entry.id}><td>{dateTime(entry.occurred_at)}</td><td>{entry.kind.replaceAll("_", " ")}</td><td>{entry.reason ?? entry.source_type.replaceAll("_", " ")}</td><td className={BigInt(entry.points_delta) > BigInt(0) ? "is-positive" : "is-negative"}>{BigInt(entry.points_delta) > BigInt(0) ? "+" : ""}{formatPoints(entry.points_delta)}</td></tr>)}</tbody></table></div>}</section>}</div>;
}

function LoyaltySettings({ program, tiers, currency, canConfigure, busy, onProgram, onTier }: { program: LoyaltyProgram | null; tiers: LoyaltyTier[]; currency: string; canConfigure: boolean; busy: boolean; onProgram: (input: { earn_rate_bps: number; point_value_minor: string; birthday_reward_points: string; is_active: boolean }) => Promise<void>; onTier: (tierId: string | null, input: LoyaltyTierInput) => Promise<void> }) {
  const [programDraft, setProgramDraft] = useState(() => programDraftOf(program));
  const [tierDraft, setTierDraft] = useState({ id: null as string | null, name: "", threshold: "", multiplier: "100" });
  return <div className="loyalty-settings"><section className="customer-card"><h2>Program</h2>{program ? <form className="loyalty-form" onSubmit={(event) => { event.preventDefault(); const pointValue = parseMenuPriceToMinor(programDraft.pointValue); if (pointValue && /^(0|[1-9]\d*)$/.test(programDraft.birthdayPoints)) void onProgram({ earn_rate_bps: Math.round(Number(programDraft.earnRate) * 100), point_value_minor: pointValue, birthday_reward_points: programDraft.birthdayPoints, is_active: programDraft.active }); }}><label><span>Earn rate</span><div><input min="0" max="100" step="0.01" disabled={!canConfigure} type="number" value={programDraft.earnRate} onChange={(event) => setProgramDraft({ ...programDraft, earnRate: event.target.value })} /><small>% of net sale</small></div></label><label><span>Point value</span><div><input min="0.01" step="0.01" disabled={!canConfigure} type="number" value={programDraft.pointValue} onChange={(event) => setProgramDraft({ ...programDraft, pointValue: event.target.value })} /><small>{currency} per point</small></div></label><label><span>Birthday reward</span><div><input disabled={!canConfigure} inputMode="numeric" pattern="[0-9]+" value={programDraft.birthdayPoints} onChange={(event) => setProgramDraft({ ...programDraft, birthdayPoints: event.target.value })} /><small>points</small></div></label><label className="promotion-check"><input disabled={!canConfigure} type="checkbox" checked={programDraft.active} onChange={(event) => setProgramDraft({ ...programDraft, active: event.target.checked })} />Program active</label>{canConfigure && <button className="menu-primary-button" disabled={busy} type="submit">Save program</button>}</form> : <p className="customer-empty">Program is not configured.</p>}</section><section className="customer-card"><header><div><h2>Tiers</h2><p>Lifetime points choose the customer’s tier automatically.</p></div>{canConfigure && <button className="menu-secondary-button" type="button" onClick={() => setTierDraft({ id: null, name: "", threshold: "", multiplier: "100" })}><Plus />New tier</button>}</header><div className="loyalty-tier-list">{tiers.map((tier) => <button key={tier.id} type="button" disabled={!canConfigure} onClick={() => setTierDraft({ id: tier.id, name: tier.name, threshold: tier.threshold_lifetime_points, multiplier: String(tier.earn_multiplier_bps / 100) })}><strong>{tier.name}</strong><span>{formatPoints(tier.threshold_lifetime_points)} lifetime points</span><small>{percent(tier.earn_multiplier_bps)} earn multiplier</small></button>)}{tiers.length === 0 && <p className="customer-empty">No tiers yet.</p>}</div>{canConfigure && <form className="loyalty-tier-form" onSubmit={(event) => { event.preventDefault(); if (tierDraft.name.trim() && /^\d+$/.test(tierDraft.threshold)) void onTier(tierDraft.id, { name: tierDraft.name.trim(), threshold_lifetime_points: tierDraft.threshold, earn_multiplier_bps: Math.round(Number(tierDraft.multiplier) * 100) }).then(() => setTierDraft({ id: null, name: "", threshold: "", multiplier: "100" })); }}><input required maxLength={100} placeholder="Tier name" value={tierDraft.name} onChange={(event) => setTierDraft({ ...tierDraft, name: event.target.value })} /><input required inputMode="numeric" pattern="[0-9]+" placeholder="Lifetime points" value={tierDraft.threshold} onChange={(event) => setTierDraft({ ...tierDraft, threshold: event.target.value })} /><input required min="0" max="1000" step="0.01" type="number" aria-label="Earn multiplier percent" placeholder="Multiplier %" value={tierDraft.multiplier} onChange={(event) => setTierDraft({ ...tierDraft, multiplier: event.target.value })} /><button className="menu-primary-button" disabled={busy} type="submit">{tierDraft.id ? "Update tier" : "Add tier"}</button></form>}</section></div>;
}

function CustomerModal({ draft, busy, title, onClose, onSave }: { draft: CustomerDraft; busy: boolean; title: string; onClose: () => void; onSave: (draft: CustomerDraft) => Promise<void> }) {
  const [value, setValue] = useState(draft);
  return <div className="modal-backdrop" role="presentation" onMouseDown={onClose}><form className="modal-card customer-modal" role="dialog" aria-modal="true" aria-labelledby="customer-modal-title" onMouseDown={(event) => event.stopPropagation()} onSubmit={(event) => { event.preventDefault(); void onSave(value); }}><button className="modal-close" type="button" aria-label="Close" onClick={onClose}><X /></button><h2 id="customer-modal-title">{title}</h2><div className="customer-modal-grid"><label className="modal-field"><span>Phone</span><input autoFocus required maxLength={32} type="tel" value={value.phone} onChange={(event) => setValue({ ...value, phone: event.target.value })} /></label><label className="modal-field"><span>First name</span><input maxLength={100} value={value.first_name} onChange={(event) => setValue({ ...value, first_name: event.target.value })} /></label><label className="modal-field"><span>Last name</span><input maxLength={100} value={value.last_name} onChange={(event) => setValue({ ...value, last_name: event.target.value })} /></label><label className="modal-field"><span>Email</span><input maxLength={320} type="email" value={value.email} onChange={(event) => setValue({ ...value, email: event.target.value })} /></label><label className="modal-field"><span>Birthday</span><input type="date" value={value.birth_date} onChange={(event) => setValue({ ...value, birth_date: event.target.value })} /></label><label className="modal-field customer-note"><span>Note</span><textarea maxLength={4000} value={value.note} onChange={(event) => setValue({ ...value, note: event.target.value })} /></label></div><label className="promotion-check"><input type="checkbox" checked={value.marketing_consent} onChange={(event) => setValue({ ...value, marketing_consent: event.target.checked })} />Customer consented to marketing</label><div className="modal-actions"><button className="secondary-button" type="button" onClick={onClose}>Cancel</button><button className="primary-button" disabled={busy} type="submit">{busy ? "Saving…" : "Save customer"}</button></div></form></div>;
}

function customerToDraft(customer: Customer): CustomerDraft { return { phone: customer.phone, first_name: customer.first_name ?? "", last_name: customer.last_name ?? "", email: customer.email ?? "", birth_date: customer.birth_date ?? "", note: customer.note ?? "", marketing_consent: customer.marketing_consent }; }
function customerName(customer: Customer) { return [customer.first_name, customer.last_name].filter(Boolean).join(" ") || customer.phone; }
function valueOrNull(value: string) { return value.trim() || null; }
function dateTime(value: string | null) { return value ? new Intl.DateTimeFormat("en", { dateStyle: "medium" }).format(new Date(value)) : "—"; }
function birthdayLabel(value: string) { const date = new Date(`${value}T00:00:00`); return new Intl.DateTimeFormat("en", { day: "numeric", month: "short" }).format(date); }
function formatPoints(value: string) { return new Intl.NumberFormat("en").format(BigInt(value)); }
function percent(bps: number) { return `${new Intl.NumberFormat("en", { maximumFractionDigits: 2 }).format(bps / 100)}%`; }
function programDraftOf(program: LoyaltyProgram | null) { return { earnRate: program ? String(program.earn_rate_bps / 100) : "0", pointValue: program ? priceMinorToInput(program.point_value_minor) : "1", birthdayPoints: program?.birthday_reward_points ?? "0", active: program?.is_active ?? true }; }
function messageOf(error: unknown) { return error instanceof Error ? error.message : "Something went wrong. Please try again."; }
