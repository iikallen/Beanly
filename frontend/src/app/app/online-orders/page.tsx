"use client";

import { Clock3, ExternalLink, PauseCircle, PlayCircle, RadioTower, XCircle } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { useOnlineOrderingPermissions } from "@/hooks/use-online-ordering-permissions";
import { ApiError, api, type OnlineOrder, type OnlineOrderingReadiness, type OnlineOrderingSettings, type OnlineOrderingSettingsInput, type OnlineOrderingStation, type OnlineOrderingStationKind, type PosRegister } from "@/lib/api";
import { formatMenuPriceMinor } from "@/lib/menu";

type View = "ORDERS" | "SETUP";

export default function OnlineOrdersPage() {
  const { accessToken } = useAuth();
  const { currentOrganization: organization, currentLocation: location } = useWorkspace();
  const permissions = useOnlineOrderingPermissions();
  const [view, setView] = useState<View>("ORDERS");
  const [orders, setOrders] = useState<OnlineOrder[]>([]);
  const [settings, setSettings] = useState<OnlineOrderingSettings | null>(null);
  const [settingsDraft, setSettingsDraft] = useState<OnlineOrderingSettingsInput | null>(null);
  const [stations, setStations] = useState<OnlineOrderingStation[]>([]);
  const [stationTokens, setStationTokens] = useState<Record<string, string>>({});
  const [registers, setRegisters] = useState<PosRegister[]>([]);
  const [stationKind, setStationKind] = useState<OnlineOrderingStationKind>("TABLE");
  const [stationLabel, setStationLabel] = useState("");
  const [pauseReason, setPauseReason] = useState("Kitchen overloaded");
  const [readiness, setReadiness] = useState<OnlineOrderingReadiness | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const scopeKey = `${accessToken ?? ""}\0${organization?.id ?? ""}\0${location?.id ?? ""}\0${permissions.canRead}\0${permissions.canConfigure}`;
  const activeScope = useRef(scopeKey);
  const loadRequest = useRef(0);
  useLayoutEffect(() => { activeScope.current = scopeKey; loadRequest.current += 1; }, [scopeKey]);

  const load = useCallback(async () => {
    const requestedScope = scopeKey;
    if (activeScope.current !== requestedScope) return;
    const requestId = ++loadRequest.current;
    if (!accessToken || !organization || !location || !permissions.canRead) return;
    const [rows, setup] = await Promise.all([
      api.listOnlineOrders({ locationId: location.id }, organization.id, accessToken),
      permissions.canConfigure ? Promise.all([
        api.getOnlineOrderingSettings(location.id, organization.id, accessToken).catch((caught) => { if (caught instanceof ApiError && caught.status === 404) return null; throw caught; }),
        api.listOnlineOrderingStations(location.id, organization.id, accessToken),
        api.getOnlineOrderingReadiness(location.id, organization.id, accessToken),
        api.listPosRegisters(location.id, organization.id, accessToken),
      ]) : Promise.resolve(null),
    ]);
    if (activeScope.current !== requestedScope || loadRequest.current !== requestId) return;
    setOrders(rows);
    if (setup) {
      const [nextSettings, nextStations, nextReadiness, nextRegisters] = setup;
      setSettings(nextSettings); setStations(nextStations); setReadiness(nextReadiness); setRegisters(nextRegisters.filter((register) => register.is_active));
      setSettingsDraft((current) => current ?? (nextSettings ? editableSettings(nextSettings) : defaultSettings(location.id)));
    }
  }, [accessToken, location, organization, permissions.canConfigure, permissions.canRead, scopeKey]);

  useEffect(() => {
    let cancelled = false;
    queueMicrotask(() => {
      if (cancelled) return;
      setOrders([]); setSettings(null); setSettingsDraft(null); setStations([]); setStationTokens({}); setRegisters([]); setReadiness(null); setBusy(""); setError("");
      void load().catch((caught) => { if (!cancelled) setError(messageOf(caught)); });
    });
    const timer = window.setInterval(() => { void load().catch((caught) => { if (!cancelled) setError(messageOf(caught)); }); }, 5000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [load]);

  async function run(key: string, operation: () => Promise<unknown>) {
    const actionScope = scopeKey;
    setBusy(key); setError("");
    try { await operation(); if (activeScope.current === actionScope) await load(); }
    catch (caught) { if (activeScope.current === actionScope) setError(messageOf(caught)); }
    finally { if (activeScope.current === actionScope) setBusy(""); }
  }

  function applySettings(value: OnlineOrderingSettings) {
    if (activeScope.current !== scopeKey) return;
    setSettings(value); setSettingsDraft(editableSettings(value));
  }

  function saveSettings() {
    if (!settingsDraft || !organization || !accessToken) return;
    void run("settings", async () => {
      const saved = await api.saveOnlineOrderingSettings(settingsDraft, organization.id, accessToken);
      applySettings(saved);
    });
  }

  function createStation() {
    if (!stationLabel.trim() || !location || !organization || !accessToken) return;
    void run("station-new", async () => {
      const created = await api.createOnlineOrderingStation({ location_id: location.id, kind: stationKind, label: stationLabel.trim() }, organization.id, accessToken);
      if (activeScope.current !== scopeKey) return;
      if (created.public_token) setStationTokens((current) => ({ ...current, [created.id]: created.public_token! }));
      setStationLabel("");
    });
  }

  function rotateStation(stationId: string) {
    if (!organization || !accessToken) return;
    void run(stationId, async () => {
      const rotated = await api.rotateOnlineOrderingStation(stationId, organization.id, accessToken);
      if (activeScope.current !== scopeKey) return;
      if (rotated.public_token) setStationTokens((current) => ({ ...current, [stationId]: rotated.public_token! }));
    });
  }

  function toggleStation(station: OnlineOrderingStation) {
    if (!organization || !accessToken) return;
    void run(station.id, async () => {
      const updated = await api.updateOnlineOrderingStation(station.id, { is_active: !station.is_active }, organization.id, accessToken);
      if (activeScope.current !== scopeKey) return;
      if (!updated.is_active) setStationTokens((current) => { const next = { ...current }; delete next[station.id]; return next; });
    });
  }

  function withReason(key: string, label: string, operation: (reason: string) => Promise<unknown>) {
    const reason = window.prompt(`${label} reason`);
    if (!reason?.trim()) return;
    void run(key, () => operation(reason.trim()));
  }

  const pending = useMemo(() => orders.filter((order) => order.status === "PENDING").length, [orders]);
  if (permissions.loading) return <p>Loading online orders…</p>;
  if (!permissions.canRead) return <div className="empty-state"><RadioTower /><h1>Online order access required</h1></div>;

  return <div className="online-admin">
    <header className="page-heading"><div><p className="eyebrow">First-party ordering</p><h1>Online orders</h1><p>{pending} pending</p></div>
      <nav className="segmented-control" aria-label="Online ordering views"><button type="button" aria-current={view === "ORDERS" ? "page" : undefined} className={view === "ORDERS" ? "is-active" : ""} onClick={() => setView("ORDERS")}>Orders</button>{permissions.canConfigure && <button type="button" aria-current={view === "SETUP" ? "page" : undefined} className={view === "SETUP" ? "is-active" : ""} onClick={() => setView("SETUP")}>Setup</button>}</nav>
    </header>
    {error && <p className="form-error" role="alert">{error}</p>}
    {view === "ORDERS" ? <div className="online-order-grid" aria-live="polite">
      {orders.length === 0 && <div className="empty-state"><Clock3 /><h2>No online orders yet</h2><p>New pickup and QR orders appear here.</p></div>}
      {orders.map((order) => <article className="online-order-card" key={order.id}>
        <header><div><strong>#{order.source === "QR" ? "Q" : "O"}-{order.order_number}</strong><small>{minuteTime(order.created_at, location?.timezone)} · {Math.floor(order.age_seconds / 60)}m old</small></div><span className={`status-pill status-${order.status.toLowerCase()}`}>{order.status.replaceAll("_", " ")}</span></header>
        <div className="online-fulfillment-row"><span className="status-pill">{titleCase(order.fulfillment_type)}</span><span className="status-pill">{order.fulfillment_timing === "ASAP" ? "ASAP" : "Scheduled"} · {dueLabel(order.promised_at, location?.timezone)}</span></div>
        <h2>{order.guest_name || "Guest"}</h2>{order.guest_phone && <p>{order.guest_phone}</p>}
        {order.delivery_zone && <p><strong>{order.delivery_zone.name}</strong> · {order.delivery_address}</p>}{order.guest_instructions && <p>Instructions: {order.guest_instructions}</p>}
        <ul>{order.items.map((item, index) => <li key={`${item.product_name}-${index}`}><span>{item.quantity} × {item.product_name}{item.variant_name ? ` · ${item.variant_name}` : ""}</span><strong>{formatMenuPriceMinor(item.total_minor, order.currency_code)}</strong></li>)}</ul>
        <footer><strong>{formatMenuPriceMinor(order.total_minor, order.currency_code)}</strong><div>
          {permissions.canManage && order.status === "PENDING" && <><button type="button" disabled={busy === order.id} onClick={() => withReason(order.id, "Reject", (reason) => api.rejectOnlineOrder(order.id, crypto.randomUUID(), reason, organization!.id, accessToken!))}><XCircle aria-hidden="true" /> Reject</button><button type="button" className="primary-button" disabled={busy === order.id} onClick={() => void run(order.id, () => api.acceptOnlineOrder(order.id, crypto.randomUUID(), organization!.id, accessToken!))}>Accept</button></>}
          {order.status === "AWAITING_PAYMENT" && <Link className="primary-button" href={`/app/pos?order_id=${order.sales_order_id}`}><ExternalLink /> Open in POS</Link>}
          {permissions.canManage && order.status === "PREPARING" && <button type="button" className="primary-button" disabled={busy === order.id} onClick={() => void run(order.id, () => api.readyOnlineOrder(order.id, crypto.randomUUID(), organization!.id, accessToken!))}>Ready</button>}
          {permissions.canManage && order.status === "READY" && <button type="button" className="primary-button" disabled={busy === order.id} onClick={() => void run(order.id, () => api.completeOnlineOrder(order.id, crypto.randomUUID(), organization!.id, accessToken!))}>Complete</button>}
          {permissions.canManage && order.can_cancel && order.status !== "PENDING" && <button type="button" disabled={busy === order.id} onClick={() => withReason(order.id, "Cancel", (reason) => api.cancelOnlineOrder(order.id, crypto.randomUUID(), reason, organization!.id, accessToken!))}>Cancel</button>}
        </div></footer>
      </article>)}
    </div> : <section className="online-setup">
      <div className="summary-card"><h2>{readiness?.ready ? "Online ordering is live" : "Online ordering needs attention"}</h2><p>{readiness?.reasons.join(" · ") || "Ready to receive guest orders."}</p>{settings && <div className="button-row">{settings.accepting_orders ? <><label>Pause reason<select value={pauseReason} onChange={(event) => setPauseReason(event.target.value)}><option>Kitchen overloaded</option><option>Closing soon</option><option>Outage</option></select></label><button type="button" disabled={!!busy} onClick={() => void run("pause-15", async () => applySettings(await api.pauseOnlineOrdering(location!.id, pauseReason, 15, organization!.id, accessToken!)))}><PauseCircle aria-hidden="true" /> Pause 15 min</button><button type="button" disabled={!!busy} onClick={() => void run("pause-30", async () => applySettings(await api.pauseOnlineOrdering(location!.id, pauseReason, 30, organization!.id, accessToken!)))}>Pause 30 min</button><button type="button" disabled={!!busy} onClick={() => void run("pause", async () => applySettings(await api.pauseOnlineOrdering(location!.id, pauseReason, null, organization!.id, accessToken!)))}>Until resumed</button><button type="button" disabled={!!busy} onClick={() => void run("close-today", async () => applySettings(await api.pauseOnlineOrdering(location!.id, "Closed today", null, organization!.id, accessToken!, true)))}>Close today</button></> : <button type="button" disabled={!!busy} onClick={() => void run("resume", async () => applySettings(await api.resumeOnlineOrdering(location!.id, organization!.id, accessToken!)))}><PlayCircle aria-hidden="true" /> Resume</button>}<Link href={`/order/${settings.public_slug}`} rel="noopener noreferrer" target="_blank">Open storefront</Link></div>}</div>
      {settingsDraft && <div className="summary-card"><h2>Storefront settings</h2><div className="online-setup-form"><label><span>Public slug</span><input required pattern="[a-z0-9][a-z0-9-]{1,98}[a-z0-9]" value={settingsDraft.public_slug} onChange={(event) => setSettingsDraft({ ...settingsDraft, public_slug: event.target.value.toLowerCase() })} /></label><label><span>Register</span><select value={settingsDraft.register_id ?? ""} onChange={(event) => setSettingsDraft({ ...settingsDraft, register_id: event.target.value || null })}><option value="">Select register</option>{registers.map((register) => <option key={register.id} value={register.id}>{register.name}</option>)}</select></label><label><span>Minimum order</span><input inputMode="numeric" pattern="[0-9]+" value={settingsDraft.minimum_order_minor} onChange={(event) => setSettingsDraft({ ...settingsDraft, minimum_order_minor: event.target.value })} /></label><label><span>Maximum order</span><input inputMode="numeric" pattern="[0-9]*" placeholder="No maximum" value={settingsDraft.maximum_order_minor ?? ""} onChange={(event) => setSettingsDraft({ ...settingsDraft, maximum_order_minor: event.target.value || null })} /></label></div><div className="online-setting-checks"><label><input type="checkbox" checked={settingsDraft.enabled} onChange={(event) => setSettingsDraft({ ...settingsDraft, enabled: event.target.checked })} />Enabled</label><label><input type="checkbox" checked={settingsDraft.pickup_enabled} onChange={(event) => setSettingsDraft({ ...settingsDraft, pickup_enabled: event.target.checked })} />Pickup</label><label><input type="checkbox" checked={settingsDraft.qr_dine_in_enabled} onChange={(event) => setSettingsDraft({ ...settingsDraft, qr_dine_in_enabled: event.target.checked })} />QR dine-in</label><label><input type="checkbox" checked={settingsDraft.qr_auto_accept} onChange={(event) => setSettingsDraft({ ...settingsDraft, qr_auto_accept: event.target.checked })} />Auto-accept QR</label><label><input type="checkbox" checked={settingsDraft.guest_name_required} onChange={(event) => setSettingsDraft({ ...settingsDraft, guest_name_required: event.target.checked })} />Require guest name</label><label><input type="checkbox" checked={settingsDraft.guest_phone_required_pickup} onChange={(event) => setSettingsDraft({ ...settingsDraft, guest_phone_required_pickup: event.target.checked })} />Require pickup phone</label></div><h3>Ordering hours</h3><div className="online-schedules">{settingsDraft.schedules.map((schedule, index) => <div key={`${schedule.weekday}-${index}`}><select aria-label={`Day ${index + 1}`} value={schedule.weekday} onChange={(event) => setSettingsDraft({ ...settingsDraft, schedules: settingsDraft.schedules.map((row, rowIndex) => rowIndex === index ? { ...row, weekday: Number(event.target.value) } : row) })}>{WEEKDAYS.map((day, dayIndex) => <option key={day} value={dayIndex}>{day}</option>)}</select><input aria-label={`Opening time ${index + 1}`} required type="time" value={schedule.opens_at_local.slice(0, 5)} onChange={(event) => setSettingsDraft({ ...settingsDraft, schedules: settingsDraft.schedules.map((row, rowIndex) => rowIndex === index ? { ...row, opens_at_local: event.target.value } : row) })} /><input aria-label={`Closing time ${index + 1}`} required type="time" value={schedule.closes_at_local.slice(0, 5)} onChange={(event) => setSettingsDraft({ ...settingsDraft, schedules: settingsDraft.schedules.map((row, rowIndex) => rowIndex === index ? { ...row, closes_at_local: event.target.value } : row) })} /><button type="button" aria-label={`Remove hours ${index + 1}`} onClick={() => setSettingsDraft({ ...settingsDraft, schedules: settingsDraft.schedules.filter((_, rowIndex) => rowIndex !== index) })}>Remove</button></div>)}</div><button type="button" onClick={() => setSettingsDraft({ ...settingsDraft, schedules: [...settingsDraft.schedules, { weekday: weekdayNow(), opens_at_local: "08:00", closes_at_local: "22:00" }] })}>Add hours</button><button type="button" className="primary-button" disabled={!!busy || !settingsDraft.public_slug || !settingsDraft.minimum_order_minor} onClick={saveSettings}>{busy === "settings" ? "Saving…" : "Save settings"}</button></div>}
      <div className="summary-card"><h2>QR stations</h2><div className="online-station-form"><select aria-label="Station kind" value={stationKind} onChange={(event) => setStationKind(event.target.value as OnlineOrderingStationKind)}><option value="TABLE">Table</option><option value="COUNTER">Counter</option><option value="PICKUP_SPOT">Pickup spot</option></select><input aria-label="Station label" maxLength={100} placeholder="Table 7" value={stationLabel} onChange={(event) => setStationLabel(event.target.value)} /><button type="button" disabled={!!busy || !stationLabel.trim()} onClick={createStation}>{busy === "station-new" ? "Creating…" : "Create station"}</button></div>{stations.map((station) => { const token = station.public_token ?? stationTokens[station.id]; return <div className="online-station-row" key={station.id}><span><strong>{station.label}</strong><small>{station.kind.replaceAll("_", " ")} · {station.is_active ? "Active" : "Inactive"}</small></span><div>{station.is_active && token && settings ? <Link href={`/order/${settings.public_slug}?station=${encodeURIComponent(token)}`} rel="noopener noreferrer" target="_blank">Open QR link</Link> : null}<button type="button" disabled={busy === station.id || !station.is_active} onClick={() => rotateStation(station.id)}>Rotate token</button><button type="button" disabled={busy === station.id} onClick={() => toggleStation(station)}>{station.is_active ? "Revoke" : "Activate"}</button></div></div>; })}<small>Tokens are shown only when created or rotated.</small></div>
    </section>}
  </div>;
}

const editableSettings = (value: OnlineOrderingSettings): OnlineOrderingSettingsInput => ({ location_id: value.location_id, public_slug: value.public_slug, enabled: value.enabled, pickup_enabled: value.pickup_enabled, delivery_enabled: value.delivery_enabled, qr_dine_in_enabled: value.qr_dine_in_enabled, qr_auto_accept: value.qr_auto_accept, register_id: value.register_id, accepting_orders: value.accepting_orders, minimum_order_minor: value.minimum_order_minor, maximum_order_minor: value.maximum_order_minor, guest_name_required: value.guest_name_required, guest_phone_required_pickup: value.guest_phone_required_pickup, preparation_minutes: value.preparation_minutes, slot_interval_minutes: value.slot_interval_minutes, slot_capacity: value.slot_capacity, max_advance_minutes: value.max_advance_minutes, cancellation_cutoff_minutes: value.cancellation_cutoff_minutes, delivery_minimum_order_minor: value.delivery_minimum_order_minor, default_fulfillment_type: value.default_fulfillment_type, schedules: value.schedules });
const defaultSettings = (locationId: string): OnlineOrderingSettingsInput => ({ location_id: locationId, public_slug: `location-${locationId.slice(0, 8)}`, enabled: false, pickup_enabled: true, delivery_enabled: false, qr_dine_in_enabled: true, qr_auto_accept: false, register_id: null, accepting_orders: true, minimum_order_minor: "0", maximum_order_minor: null, guest_name_required: false, guest_phone_required_pickup: true, preparation_minutes: 15, slot_interval_minutes: 15, slot_capacity: 20, max_advance_minutes: 10080, cancellation_cutoff_minutes: 0, delivery_minimum_order_minor: "0", default_fulfillment_type: "PICKUP", schedules: [] });
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const weekdayNow = () => (new Date().getDay() + 6) % 7;
const messageOf = (error: unknown) => error instanceof Error ? error.message : "Something went wrong";
const minuteTime = (value: string, timeZone?: string) => new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", timeZone });
const dueLabel = (value: string, timeZone?: string) => `Due ${minuteTime(value, timeZone)}`;
const titleCase = (value: string) => value.toLowerCase().replaceAll("_", " ").replace(/^./, (first) => first.toUpperCase());
