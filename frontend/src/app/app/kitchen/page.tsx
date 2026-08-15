"use client";

import { Check, ChefHat, Clock3, Maximize2, Plus, RotateCcw, Trash2 } from "lucide-react";
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { useKitchenPermissions } from "@/hooks/use-kitchen-permissions";
import { api, type KitchenPerformance, type KitchenReadiness, type KitchenRoutingRule, type KitchenStation, type KitchenStationRole, type KitchenTicket, type MenuCategory, type MenuProduct, type SalesOrderType } from "@/lib/api";
import { kitchenAging, mergeKitchenTickets } from "@/lib/kitchen";

type View = "BOARD" | "SETUP" | "REPORTS";
const today = () => new Date().toISOString().slice(0, 10);
const actionId = () => crypto.randomUUID();

export default function KitchenPage() {
  const { accessToken } = useAuth();
  const { currentOrganization: organization, currentLocation: location } = useWorkspace();
  const permissions = useKitchenPermissions();
  const [view, setView] = useState<View>("BOARD");
  const [stations, setStations] = useState<KitchenStation[]>([]);
  const [stationId, setStationId] = useState("");
  const [tickets, setTickets] = useState<KitchenTicket[]>([]);
  const [cursor, setCursor] = useState(0);
  const [serverNow, setServerNow] = useState(0);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState("");
  const [error, setError] = useState("");
  const cursorRef = useRef(0);

  const loadStations = useCallback(async () => {
    if (!accessToken || !organization || !location) return;
    const rows = await api.listKitchenStations(location.id, organization.id, accessToken);
    setStations(rows);
    setStationId((current) => rows.some((row) => row.id === current) ? current : rows.find((row) => row.is_default)?.id ?? rows[0]?.id ?? "");
  }, [accessToken, location, organization]);

  useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(() => {
      if (cancelled) return;
      setLoading(true); setError(""); setTickets([]); setCursor(0); cursorRef.current = 0; setStationId("");
      return loadStations().catch((caught) => { if (!cancelled) setError(messageOf(caught)); }).finally(() => { if (!cancelled) setLoading(false); });
    });
    return () => { cancelled = true; };
  }, [loadStations]);

  useEffect(() => {
    if (!accessToken || !organization || !stationId || !permissions.canRead) return;
    let cancelled = false;
    let timer = 0;
    const poll = async () => {
      try {
        const board = await api.getKitchenBoard(stationId, organization.id, accessToken, cursorRef.current || undefined);
        if (cancelled) return;
        setTickets((current) => mergeKitchenTickets(current, board.tickets, cursorRef.current === 0));
        cursorRef.current = board.cursor; setCursor(board.cursor); setServerNow(new Date(board.server_time).getTime()); setError("");
      } catch (caught) { if (!cancelled) setError(messageOf(caught)); }
      if (!cancelled) timer = window.setTimeout(poll, document.hidden ? 5000 : 1000);
    };
    void poll();
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [accessToken, organization, permissions.canRead, stationId]);

  async function run(id: string, operation: () => Promise<unknown>) {
    setBusyId(id); setError("");
    try { await operation(); cursorRef.current = 0; setCursor(0); }
    catch (caught) { setError(messageOf(caught)); }
    finally { setBusyId(""); }
  }

  const station = stations.find((row) => row.id === stationId) ?? null;
  const visibleTickets = tickets.filter((ticket) => ticket.status !== "CANCELLED").slice(-40);

  if (permissions.loading || loading) return <section className="kitchen-content kitchen-state">Loading kitchen…</section>;
  if (!permissions.canRead && !permissions.canReport) return <section className="kitchen-content kitchen-state"><ChefHat /><h1>Kitchen access required</h1></section>;

  return <section className="kitchen-content">
    <header className="kitchen-header"><div><span>Live fulfillment</span><h1>Kitchen</h1></div><div className="kitchen-header-actions">
      {permissions.canRead && <select aria-label="Kitchen station" value={stationId} onChange={(event) => { setTickets([]); cursorRef.current = 0; setCursor(0); setStationId(event.target.value); }}>{stations.filter((row) => row.is_active).map((row) => <option key={row.id} value={row.id}>{row.name} · {row.role.replace("_", " + ")}</option>)}</select>}
      <button className="secondary-button" onClick={() => void document.documentElement.requestFullscreen?.()}><Maximize2 /> Full screen</button>
    </div></header>
    <nav className="kitchen-tabs" aria-label="Kitchen views"><button className={view === "BOARD" ? "is-active" : ""} onClick={() => setView("BOARD")}>Board</button>{permissions.canManage && <button className={view === "SETUP" ? "is-active" : ""} onClick={() => setView("SETUP")}>Setup</button>}{permissions.canReport && <button className={view === "REPORTS" ? "is-active" : ""} onClick={() => setView("REPORTS")}>Performance</button>}</nav>
    {error && <div className="kitchen-error" role="alert">{error}</div>}
    {view === "BOARD" && permissions.canRead && <div className="kitchen-board" aria-live="polite">
      {!station ? <KitchenEmpty title="No active station" body="A manager can create the first kitchen station in Setup." /> : visibleTickets.length === 0 ? <KitchenEmpty title="Board is clear" body={`Waiting for paid orders · sync ${cursor}`} /> : visibleTickets.map((ticket) => <TicketCard key={ticket.id} ticket={ticket} station={station} now={serverNow} timeZone={location!.timezone} canWork={permissions.canWork} canExpo={permissions.canExpo} busyId={busyId} onStart={(workId) => run(workId, () => api.startKitchenWork(workId, actionId(), organization!.id, accessToken!))} onReady={(workId) => run(workId, () => api.readyKitchenWork(workId, actionId(), organization!.id, accessToken!))} onComplete={() => run(ticket.id, () => api.completeKitchenTicket(ticket.id, actionId(), organization!.id, accessToken!))} onRecall={() => run(ticket.id, () => api.recallKitchenTicket(ticket.id, actionId(), organization!.id, accessToken!))} />)}
    </div>}
    {view === "SETUP" && permissions.canManage && <KitchenSetup stations={stations} locationId={location!.id} organizationId={organization!.id} accessToken={accessToken!} onChange={loadStations} />}
    {view === "REPORTS" && permissions.canReport && <KitchenReports locationId={location!.id} organizationId={organization!.id} accessToken={accessToken!} />}
  </section>;
}

function TicketCard({ ticket, station, now, timeZone, canWork, canExpo, busyId, onStart, onReady, onComplete, onRecall }: { ticket: KitchenTicket; station: KitchenStation; now: number; timeZone: string; canWork: boolean; canExpo: boolean; busyId: string; onStart: (id: string) => void; onReady: (id: string) => void; onComplete: () => void; onRecall: () => void }) {
  const aging = kitchenAging(ticket.fired_at, now, station.warning_after_seconds, station.late_after_seconds);
  const expo = station.role === "EXPO" || station.role === "PREP_EXPO";
  return <article className={`kitchen-ticket is-${aging.level}`}><header><div><span>#{ticket.order_number} · {ticket.order_type.replace("_", " ")}</span><strong>{ticket.status.replace("_", " ")}</strong></div><time><Clock3 />{clock(aging.elapsedSeconds)}</time></header>
    {(ticket.order_source || ticket.fulfillment_type) && <div className="kitchen-fulfillment"><strong>{[ticket.order_source, ticket.fulfillment_type].filter(Boolean).join(" · ")}</strong>{ticket.promised_at && <span className={Date.parse(ticket.promised_at) < now ? "is-late" : ""}>{Date.parse(ticket.promised_at) < now ? "Late" : "Due"} {minuteTime(ticket.promised_at, timeZone)}</span>}</div>}
    {(ticket.customer_name || ticket.table_label || ticket.guest_count) && <p className="kitchen-ticket-meta">{[ticket.customer_name, ticket.table_label, ticket.guest_count ? `${ticket.guest_count} guests` : null].filter(Boolean).join(" · ")}</p>}
    {ticket.offline_delayed && <span className="kitchen-delay">Offline delayed</span>}{ticket.note && <p className="kitchen-order-note">{ticket.note}</p>}{ticket.guest_instructions && <p className="kitchen-order-note">Instructions: {ticket.guest_instructions}</p>}
    <ul>{ticket.items.map((item) => <li key={item.id}><div><strong>{item.quantity} × {item.product_name}</strong><span>{item.variant_name}</span>{item.modifiers.map((modifier) => <small key={modifier.modifier_option_id}>+ {modifier.modifier_option_name}</small>)}{item.note && <em>{item.note}</em>}</div>{item.work_items.map((work) => <div className="kitchen-work" key={work.id}><span>{work.status}</span>{canWork && work.status === "QUEUED" && <button disabled={busyId === work.id} onClick={() => onStart(work.id)}>Start</button>}{canWork && work.status === "PREPARING" && <button disabled={busyId === work.id} onClick={() => onReady(work.id)}><Check /> Ready</button>}</div>)}</li>)}</ul>
    {expo && canExpo && <footer>{ticket.status === "COMPLETED" ? <button className="secondary-button" disabled={busyId === ticket.id} onClick={onRecall}><RotateCcw /> Recall</button> : <button className="primary-button" disabled={ticket.status !== "READY" || busyId === ticket.id} onClick={onComplete}>Complete order</button>}</footer>}
  </article>;
}

function KitchenSetup({ stations, locationId, organizationId, accessToken, onChange }: { stations: KitchenStation[]; locationId: string; organizationId: string; accessToken: string; onChange: () => Promise<void> }) {
  const [rules, setRules] = useState<KitchenRoutingRule[]>([]); const [categories, setCategories] = useState<MenuCategory[]>([]); const [products, setProducts] = useState<MenuProduct[]>([]); const [readiness, setReadiness] = useState<KitchenReadiness | null>(null); const [error, setError] = useState("");
  const [stationName, setStationName] = useState(""); const [stationCode, setStationCode] = useState(""); const [role, setRole] = useState<KitchenStationRole>("PREP");
  const [routeStationId, setRouteStationId] = useState(stations[0]?.id ?? ""); const [scope, setScope] = useState<"CATEGORY" | "VARIANT">("CATEGORY"); const [targetId, setTargetId] = useState(""); const [orderType, setOrderType] = useState<"" | SalesOrderType>("");
  const load = useCallback(async () => { try { const [nextRules, nextCategories, nextProducts, nextReadiness] = await Promise.all([api.listKitchenRouting(locationId, organizationId, accessToken), api.listMenuCategories(organizationId, accessToken), api.listMenuProducts(organizationId, accessToken, { locationId }), api.getKitchenReadiness(locationId, organizationId, accessToken)]); setRules(nextRules); setCategories(nextCategories); setProducts(nextProducts); setReadiness(nextReadiness); setRouteStationId((current) => stations.some((row) => row.id === current) ? current : stations[0]?.id ?? ""); } catch (caught) { setError(messageOf(caught)); } }, [accessToken, locationId, organizationId, stations]);
  useEffect(() => { let cancelled = false; Promise.resolve().then(() => { if (!cancelled) return load(); }); return () => { cancelled = true; }; }, [load]);
  const variants = useMemo(() => products.flatMap((product) => product.variants.map((variant) => ({ id: variant.id, name: `${product.name} · ${variant.name}` }))), [products]);
  async function createStation(event: FormEvent) { event.preventDefault(); try { await api.createKitchenStation({ location_id: locationId, name: stationName.trim(), code: stationCode.trim(), role }, organizationId, accessToken); setStationName(""); setStationCode(""); await onChange(); } catch (caught) { setError(messageOf(caught)); } }
  async function createRule(event: FormEvent) { event.preventDefault(); try { await api.createKitchenRouting({ location_id: locationId, station_id: routeStationId, scope, category_id: scope === "CATEGORY" ? targetId : null, variant_id: scope === "VARIANT" ? targetId : null, order_type: orderType || null }, organizationId, accessToken); setTargetId(""); await load(); } catch (caught) { setError(messageOf(caught)); } }
  return <div className="kitchen-setup">{error && <div className="kitchen-error">{error}</div>}<section><header><h2>Stations</h2><span>{readiness?.ready ? "Ready for orders" : "Setup needs attention"}</span></header><form onSubmit={createStation}><input aria-label="Station name" placeholder="Cold bar" value={stationName} onChange={(event) => setStationName(event.target.value)} required /><input aria-label="Station code" placeholder="cold-bar" pattern="[A-Za-z0-9_-]+" value={stationCode} onChange={(event) => setStationCode(event.target.value)} required /><select aria-label="Station role" value={role} onChange={(event) => setRole(event.target.value as KitchenStationRole)}><option value="PREP">Prep</option><option value="EXPO">Expo</option><option value="PREP_EXPO">Prep + Expo</option></select><button className="primary-button"><Plus /> Add</button></form><div className="kitchen-station-list">{stations.map((row) => <article key={row.id}><strong>{row.name}</strong><span>{row.role.replace("_", " + ")}{row.is_default ? " · Default" : ""}</span></article>)}</div></section>
    <section><header><h2>Routing</h2><span>Specific rules win; unmatched items use the default station.</span></header><form onSubmit={createRule}><select aria-label="Route station" value={routeStationId} onChange={(event) => setRouteStationId(event.target.value)} required>{stations.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}</select><select aria-label="Route scope" value={scope} onChange={(event) => { setScope(event.target.value as "CATEGORY" | "VARIANT"); setTargetId(""); }}><option value="CATEGORY">Category</option><option value="VARIANT">Variant</option></select><select aria-label="Route target" value={targetId} onChange={(event) => setTargetId(event.target.value)} required><option value="">Choose target</option>{(scope === "CATEGORY" ? categories : variants).map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}</select><select aria-label="Order type" value={orderType} onChange={(event) => setOrderType(event.target.value as "" | SalesOrderType)}><option value="">All order types</option><option value="DINE_IN">Dine in</option><option value="TAKEAWAY">Takeaway</option><option value="DELIVERY">Delivery</option></select><button className="primary-button"><Plus /> Route</button></form><div className="kitchen-rule-list">{rules.map((rule) => <article key={rule.id}><span><strong>{stations.find((row) => row.id === rule.station_id)?.name ?? "Station"}</strong>{rule.scope} · {rule.order_type?.replace("_", " ") ?? "All orders"}</span><button aria-label="Delete route" onClick={() => void api.deleteKitchenRouting(rule.id, organizationId, accessToken).then(load)}><Trash2 /></button></article>)}</div></section>
  </div>;
}

function KitchenReports({ locationId, organizationId, accessToken }: { locationId: string; organizationId: string; accessToken: string }) {
  const [dateFrom, setDateFrom] = useState(today()); const [dateTo, setDateTo] = useState(today()); const [rows, setRows] = useState<KitchenPerformance[]>([]); const [error, setError] = useState("");
  const load = useCallback(async () => { try { setRows(await api.getKitchenPerformance({ locationId, dateFrom, dateTo }, organizationId, accessToken)); setError(""); } catch (caught) { setError(messageOf(caught)); } }, [accessToken, dateFrom, dateTo, locationId, organizationId]);
  useEffect(() => { let cancelled = false; Promise.resolve().then(() => { if (!cancelled) return load(); }); return () => { cancelled = true; }; }, [load]);
  return <section className="kitchen-reports"><header><div><h2>Kitchen performance</h2><p>Completion time from fire to handoff.</p></div><div><label>From<input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} /></label><label>To<input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} /></label></div></header>{error && <div className="kitchen-error">{error}</div>}<div className="cash-report-table-wrap"><table className="cash-report-table"><thead><tr><th>Station</th><th>Completed</th><th>Average</th><th>P50</th><th>P95</th><th>Late</th></tr></thead><tbody>{rows.map((row) => <tr key={row.station_id}><td>{row.station_name}</td><td>{row.completed_count}</td><td>{clock(row.average_seconds)}</td><td>{clock(row.p50_seconds)}</td><td>{clock(row.p95_seconds)}</td><td>{row.late_percent.toFixed(1)}%</td></tr>)}</tbody></table>{rows.length === 0 && <KitchenEmpty title="No completed tickets" body="Performance appears after the first kitchen handoff." />}</div></section>;
}

function KitchenEmpty({ title, body }: { title: string; body: string }) { return <div className="kitchen-empty"><ChefHat /><strong>{title}</strong><span>{body}</span></div>; }
function clock(seconds: number) { const whole = Math.max(0, Math.floor(seconds)); return `${String(Math.floor(whole / 60)).padStart(2, "0")}:${String(whole % 60).padStart(2, "0")}`; }
function minuteTime(value: string, timeZone?: string) { return new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", timeZone }); }
function messageOf(value: unknown) { return value instanceof Error ? value.message : "Kitchen operation failed"; }
