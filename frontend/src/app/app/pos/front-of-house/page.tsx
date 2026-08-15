"use client";

import { CalendarClock, ExternalLink, Settings2, TableProperties, UserRoundPlus, UsersRound } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { useFrontOfHousePermissions } from "@/hooks/use-front-of-house-permissions";
import {
  ApiError,
  api,
  type DiningFloor,
  type DiningSection,
  type DiningTable,
  type Reservation,
  type ReservationSettingsInput,
  type ReservationStatus,
  type WaitlistEntry,
} from "@/lib/api";
import { readCurrentSession } from "@/lib/offline/db";
import { localReservationDate, reservationMinute, reservationTime } from "@/lib/reservations";

type View = "TABLES" | "RESERVATIONS" | "WAITLIST";
type ReservationRange = "TODAY" | "UPCOMING";

export default function FrontOfHousePage() {
  const router = useRouter();
  const { accessToken } = useAuth();
  const { currentOrganization: organization, currentLocation: location } = useWorkspace();
  const permissions = useFrontOfHousePermissions();
  const [view, setView] = useState<View>("TABLES");
  const [floor, setFloor] = useState<DiningFloor | null>(null);
  const [reservations, setReservations] = useState<Reservation[]>([]);
  const [waitlist, setWaitlist] = useState<WaitlistEntry[]>([]);
  const [sections, setSections] = useState<DiningSection[]>([]);
  const [tables, setTables] = useState<DiningTable[]>([]);
  const [settings, setSettings] = useState<ReservationSettingsInput | null>(null);
  const [showSetup, setShowSetup] = useState(false);
  const [reservationRange, setReservationRange] = useState<ReservationRange>("TODAY");
  const [reservationStatus, setReservationStatus] = useState<ReservationStatus | "">("");
  const [walkInTableId, setWalkInTableId] = useState("");
  const [walkInParty, setWalkInParty] = useState(2);
  const [waitGuest, setWaitGuest] = useState("");
  const [waitPhone, setWaitPhone] = useState("");
  const [waitParty, setWaitParty] = useState(2);
  const [waitQuote, setWaitQuote] = useState("");
  const [sectionName, setSectionName] = useState("");
  const [tableName, setTableName] = useState("");
  const [tableSectionId, setTableSectionId] = useState("");
  const [tableCapacity, setTableCapacity] = useState(2);
  const [shiftId, setShiftId] = useState("");
  const [clockNow, setClockNow] = useState(0);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const scopeKey = `${accessToken ?? ""}\0${organization?.id ?? ""}\0${location?.id ?? ""}\0${permissions.canRead}\0${permissions.canConfigure}`;
  const activeScope = useRef(scopeKey);
  const loadRequest = useRef(0);
  const retryIds = useRef(new Map<string, string>());
  useLayoutEffect(() => { activeScope.current = scopeKey; loadRequest.current += 1; retryIds.current.clear(); }, [scopeKey]);

  const load = useCallback(async () => {
    const requestedScope = scopeKey;
    const requestId = ++loadRequest.current;
    if (!accessToken || !organization || !location || !permissions.canRead) return;
    const [nextFloor, nextReservations, nextWaitlist, setup] = await Promise.all([
      api.getDiningFloor(location.id, organization.id, accessToken),
      api.listReservations(location.id, organization.id, accessToken),
      api.listWaitlist(location.id, organization.id, accessToken),
      permissions.canConfigure ? Promise.all([
        api.listDiningSections(location.id, organization.id, accessToken),
        api.listDiningTables(location.id, organization.id, accessToken),
        api.getReservationSettings(location.id, organization.id, accessToken).catch((caught) => caught instanceof ApiError && caught.status === 404 ? null : Promise.reject(caught)),
      ]) : Promise.resolve(null),
    ]);
    if (activeScope.current !== requestedScope || loadRequest.current !== requestId) return;
    setFloor(nextFloor); setReservations(nextReservations); setWaitlist(nextWaitlist);
    if (setup) {
      setSections(setup[0]); setTables(setup[1]);
      setSettings((current) => current ?? (setup[2] ? editableSettings(setup[2]) : defaultSettings(location.id)));
      setTableSectionId((current) => current || setup[0].find((section) => section.is_active)?.id || "");
    }
  }, [accessToken, location, organization, permissions.canConfigure, permissions.canRead, scopeKey]);

  useEffect(() => {
    let cancelled = false;
    queueMicrotask(() => {
      if (cancelled) return;
      setFloor(null); setReservations([]); setWaitlist([]); setSections([]); setTables([]); setSettings(null); setBusy(""); setError("");
      void load().catch((caught) => { if (!cancelled) setError(messageOf(caught)); });
    });
    const timer = window.setInterval(() => void load().catch((caught) => { if (!cancelled) setError(messageOf(caught)); }), 5000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [load]);

  useEffect(() => {
    if (!organization || !location) return;
    void readCurrentSession().then((session) => {
      setShiftId(session?.status === "ACTIVE" && session.organization_id === organization.id && session.location_id === location.id ? session.shift_id : "");
    }).catch(() => setShiftId(""));
  }, [location, organization]);

  useEffect(() => {
    const tick = () => setClockNow(Date.now());
    queueMicrotask(tick);
    const timer = window.setInterval(tick, 30_000);
    return () => window.clearInterval(timer);
  }, []);

  async function run(key: string, operation: () => Promise<unknown>, conflict = "The table or reservation changed. Live state has been refreshed.") {
    const actionScope = scopeKey;
    setBusy(key); setError("");
    try { await operation(); if (activeScope.current === actionScope) await load(); }
    catch (caught) {
      if (activeScope.current !== actionScope) return;
      if (caught instanceof ApiError && caught.status === 409) { await load(); setError(conflict); }
      else setError(messageOf(caught));
    } finally { if (activeScope.current === actionScope) setBusy(""); }
  }

  function withReason(key: string, label: string, operation: (reason: string) => Promise<unknown>) {
    const reason = window.prompt(`${label} reason`);
    if (reason?.trim()) void run(key, () => operation(reason.trim()));
  }

  async function withRetryId<T>(key: string, operation: (id: string) => Promise<T>) {
    const existing = retryIds.current.get(key);
    const id = existing ?? crypto.randomUUID();
    if (!existing) retryIds.current.set(key, id);
    const result = await operation(id);
    retryIds.current.delete(key);
    return result;
  }

  function seatReservation(row: Reservation) {
    if (!organization || !accessToken) return;
    void run(row.id, () => withRetryId(`reservation:seat:${row.id}`, (id) => api.seatReservation(row.id, id, row.dining_table_id, organization.id, accessToken)), "That table is no longer available. Live state has been refreshed.");
  }

  function seatWaitlist(row: WaitlistEntry) {
    if (!organization || !accessToken) return;
    void run(row.id, () => withRetryId(`waitlist:seat:${row.id}`, (id) => api.seatWaitlistEntry(row.id, id, undefined, organization.id, accessToken)), "No suitable table is available now. Live state has been refreshed.");
  }

  function seatWalkIn() {
    if (!organization || !location || !accessToken || !walkInTableId) return;
    const retryKey = `walk-in:seat:${walkInTableId}:${walkInParty}`;
    void run("walk-in", async () => { await withRetryId(retryKey, (id) => api.seatWalkIn({ client_action_id: id, location_id: location.id, dining_table_id: walkInTableId, party_size: walkInParty }, organization.id, accessToken)); setWalkInTableId(""); }, "That table was just occupied. Live state has been refreshed.");
  }

  function addWaitlist() {
    if (!organization || !location || !accessToken || !waitGuest.trim()) return;
    const retryKey = `waitlist:create:${waitGuest.trim()}:${waitPhone.trim()}:${waitParty}:${waitQuote}`;
    void run("wait-new", async () => {
      await withRetryId(retryKey, (id) => api.createWaitlistEntry({ client_entry_id: id, location_id: location.id, guest_name: waitGuest.trim(), guest_phone: waitPhone.trim() || undefined, party_size: waitParty, quoted_wait_minutes: waitQuote ? Number(waitQuote) : undefined }, organization.id, accessToken));
      setWaitGuest(""); setWaitPhone(""); setWaitQuote("");
    });
  }

  function openCheck(visitId: string) {
    if (!organization || !accessToken || !shiftId) return;
    void run(`check-${visitId}`, async () => {
      const visit = await withRetryId(`visit:open-check:${visitId}`, (id) => api.openDiningVisitCheck(visitId, id, shiftId, organization.id, accessToken));
      if (!visit.sales_order_id) throw new Error("The check was not returned");
      router.push(`/app/pos?order_id=${encodeURIComponent(visit.sales_order_id)}`);
    });
  }

  const timeZone = floor?.timezone ?? location?.timezone ?? "UTC";
  const today = localReservationDate(new Date().toISOString(), timeZone);
  const visibleReservations = useMemo(() => reservations.filter((row) => {
    const rowDate = localReservationDate(row.start_at, timeZone);
    const inRange = reservationRange === "TODAY" ? rowDate === today : rowDate >= today;
    return inRange && (!reservationStatus || row.status === reservationStatus);
  }), [reservationRange, reservationStatus, reservations, timeZone, today]);
  const activeWaitlist = waitlist.filter((row) => row.status === "WAITING");
  const availableTables = floor?.sections.flatMap((section) => section.tables).filter((table) => table.state === "AVAILABLE" && table.is_active) ?? [];

  if (permissions.loading) return <section className="pos-content"><p>Loading front of house…</p></section>;
  if (!permissions.canRead) return <section className="pos-content"><div className="empty-state"><TableProperties /><h1>Front-of-house access required</h1></div></section>;
  if (!floor && !error) return <section className="pos-content"><p aria-live="polite">Loading dining room…</p></section>;

  return <section className="pos-content foh-page">
    <header className="page-heading"><div><p className="eyebrow">Front of house</p><h1>Tables & guests</h1><p>{activeWaitlist.length} waiting · {reservations.filter((row) => row.status === "BOOKED").length} booked</p></div>
      <div className="foh-heading-actions"><nav className="segmented-control" aria-label="Front-of-house views">{(["TABLES", "RESERVATIONS", "WAITLIST"] as View[]).map((item) => <button type="button" aria-current={view === item ? "page" : undefined} className={view === item ? "is-active" : ""} key={item} onClick={() => { setView(item); setShowSetup(false); }}>{titleCase(item)}</button>)}</nav>{permissions.canConfigure && <button className="secondary-button" type="button" aria-pressed={showSetup} onClick={() => setShowSetup((current) => !current)}><Settings2 /> Setup</button>}</div>
    </header>
    {error && <p className="form-error" role="alert">{error}</p>}
    {showSetup && permissions.canConfigure ? <Setup sections={sections} tables={tables} settings={settings} busy={busy} sectionName={sectionName} tableName={tableName} tableSectionId={tableSectionId} tableCapacity={tableCapacity} onSectionName={setSectionName} onTableName={setTableName} onTableSection={setTableSectionId} onTableCapacity={setTableCapacity} onSettings={setSettings} onRun={run} onCreatedSection={() => setSectionName("")} onCreatedTable={() => setTableName("")} organizationId={organization!.id} locationId={location!.id} accessToken={accessToken!} /> : view === "TABLES" ? <>
      <div className="foh-floor" aria-live="polite">{floor?.sections.map((section) => <section key={section.id}><h2>{section.name}</h2><div>{section.tables.map((table) => <article className={`foh-table-card state-${table.state.toLowerCase()}`} key={table.id}><header><strong>{table.name}</strong><span className="status-pill">{table.state}</span></header><p><UsersRound /> Capacity {table.capacity}</p>{table.reservation && <p><CalendarClock /> {table.reservation.guest_name} · {reservationTime(table.reservation.start_at, timeZone)}</p>}{table.visit && <><p>Party of {table.visit.party_size} · seated {reservationTime(table.visit.opened_at, timeZone)} · {elapsedVisit(table.visit.opened_at, clockNow)}</p><p>Check · {table.visit.sales_order_status ?? "Not opened"}</p></>}<footer>{permissions.canManage && table.state === "RESERVED" && table.reservation?.status === "BOOKED" && <button className="primary-button" disabled={busy === table.reservation.id} type="button" onClick={() => seatReservation(table.reservation!)}>Seat</button>}{table.visit && <>{table.visit.sales_order_id ? <Link className="secondary-button" href={`/app/pos?order_id=${table.visit.sales_order_id}`}><ExternalLink /> Open check</Link> : permissions.canManage && <button className="secondary-button" disabled={!shiftId || busy === `check-${table.visit.id}`} title={shiftId ? undefined : "Open a POS shift first"} type="button" onClick={() => openCheck(table.visit!.id)}>Open check</button>}{permissions.canManage && <button type="button" disabled={busy === table.visit.id} onClick={() => void run(table.visit!.id, () => withRetryId(`visit:close:${table.visit!.id}`, (id) => api.closeDiningVisit(table.visit!.id, id, organization!.id, accessToken!)))}>Close table</button>}</>}</footer></article>)}</div></section>)}{!floor?.sections.length && <div className="empty-state"><TableProperties /><h2>No tables configured</h2><p>Use Setup to add a dining section and tables.</p></div>}</div>
      {permissions.canManage && <section className="summary-card foh-walk-in"><h2><UserRoundPlus /> Seat walk-in</h2><label>Table<select value={walkInTableId} onChange={(event) => setWalkInTableId(event.target.value)}><option value="">Choose available table</option>{availableTables.map((table) => <option key={table.id} value={table.id}>{table.name} · capacity {table.capacity}</option>)}</select></label><label>Party size<input type="number" min="1" value={walkInParty} onChange={(event) => setWalkInParty(Number(event.target.value))} /></label><button className="primary-button" disabled={busy === "walk-in" || !walkInTableId || walkInParty < 1} type="button" onClick={seatWalkIn}>{busy === "walk-in" ? "Seating…" : "Seat walk-in"}</button></section>}
    </> : view === "RESERVATIONS" ? <section><div className="foh-filters"><div className="segmented-control" aria-label="Reservation date range"><button type="button" className={reservationRange === "TODAY" ? "is-active" : ""} onClick={() => setReservationRange("TODAY")}>Today</button><button type="button" className={reservationRange === "UPCOMING" ? "is-active" : ""} onClick={() => setReservationRange("UPCOMING")}>Upcoming</button></div><label>Status<select value={reservationStatus} onChange={(event) => setReservationStatus(event.target.value as ReservationStatus | "")}><option value="">All</option>{["BOOKED", "SEATED", "COMPLETED", "CANCELLED", "NO_SHOW"].map((status) => <option key={status}>{status}</option>)}</select></label></div><div className="foh-list">{visibleReservations.map((row) => <article key={row.id}><header><div><h2>{row.guest_name}</h2><p>{reservationMinute(row.start_at, timeZone)} · party of {row.party_size} · {row.table_name}</p></div><span className="status-pill">{row.status}</span></header>{row.guest_notes && <p>Guest: {row.guest_notes}</p>}{row.internal_notes && <p>Staff: {row.internal_notes}</p>}{permissions.canManage && row.status === "BOOKED" && <footer><button className="primary-button" disabled={busy === row.id} type="button" onClick={() => seatReservation(row)}>Seat</button><button type="button" disabled={busy === row.id} onClick={() => withReason(row.id, "Cancel", (reason) => withRetryId(`reservation:cancel:${row.id}`, (id) => api.cancelReservation(row.id, id, reason, organization!.id, accessToken!)))}>Cancel</button><button type="button" disabled={busy === row.id} onClick={() => withReason(row.id, "No-show", (reason) => withRetryId(`reservation:no-show:${row.id}`, (id) => api.noShowReservation(row.id, id, reason, organization!.id, accessToken!)))}>No-show</button></footer>}</article>)}{visibleReservations.length === 0 && <div className="empty-state"><CalendarClock /><h2>No matching reservations</h2></div>}</div></section> : <section><div className="summary-card foh-waitlist-form"><h2>Add walk-in to waitlist</h2><label>Name<input maxLength={201} value={waitGuest} onChange={(event) => setWaitGuest(event.target.value)} /></label><label>Phone<input maxLength={32} value={waitPhone} onChange={(event) => setWaitPhone(event.target.value)} /></label><label>Party<input type="number" min="1" value={waitParty} onChange={(event) => setWaitParty(Number(event.target.value))} /></label><label>Quoted wait (minutes)<input type="number" min="0" value={waitQuote} onChange={(event) => setWaitQuote(event.target.value)} /></label><button className="primary-button" disabled={!permissions.canManage || busy === "wait-new" || !waitGuest.trim() || waitParty < 1} type="button" onClick={addWaitlist}>Add to waitlist</button></div><div className="foh-list">{activeWaitlist.map((row, index) => <article key={row.id}><header><div><p className="eyebrow">#{index + 1}</p><h2>{row.guest_name}</h2><p>Party of {row.party_size} · waiting since {reservationTime(row.created_at, timeZone)}{row.quoted_wait_minutes != null ? ` · quoted ${row.quoted_wait_minutes} min` : ""}</p></div><span className="status-pill">{availableTables.some((table) => table.capacity >= row.party_size) ? "TABLE AVAILABLE" : "WAITING"}</span></header>{permissions.canManage && <footer><button className="primary-button" disabled={busy === row.id} type="button" onClick={() => seatWaitlist(row)}>Seat</button><button type="button" disabled={busy === row.id} onClick={() => withReason(row.id, "Cancel", (reason) => withRetryId(`waitlist:cancel:${row.id}`, (id) => api.cancelWaitlistEntry(row.id, id, reason, organization!.id, accessToken!)))}>Cancel</button></footer>}</article>)}{activeWaitlist.length === 0 && <div className="empty-state"><UsersRound /><h2>Waitlist is clear</h2></div>}</div></section>}
  </section>;
}

function Setup(props: { sections: DiningSection[]; tables: DiningTable[]; settings: ReservationSettingsInput | null; busy: string; sectionName: string; tableName: string; tableSectionId: string; tableCapacity: number; onSectionName: (value: string) => void; onTableName: (value: string) => void; onTableSection: (value: string) => void; onTableCapacity: (value: number) => void; onSettings: (value: ReservationSettingsInput) => void; onRun: (key: string, operation: () => Promise<unknown>) => Promise<void>; onCreatedSection: () => void; onCreatedTable: () => void; organizationId: string; locationId: string; accessToken: string }) {
  const activeSections = props.sections.filter((section) => section.is_active);
  return <section className="foh-setup"><div className="summary-card"><h2>Sections</h2><div className="foh-inline-form"><input aria-label="Section name" maxLength={100} placeholder="Main Hall" value={props.sectionName} onChange={(event) => props.onSectionName(event.target.value)} /><button type="button" disabled={!!props.busy || !props.sectionName.trim()} onClick={() => void props.onRun("section-new", async () => { await api.createDiningSection({ location_id: props.locationId, name: props.sectionName.trim() }, props.organizationId, props.accessToken); props.onCreatedSection(); })}>Create</button></div>{props.sections.map((section) => <div className="foh-config-row" key={section.id}><span><strong>{section.name}</strong><small>Sort {section.sort_order} · {section.is_active ? "Active" : "Inactive"}</small></span><div><button type="button" disabled={props.busy === section.id} onClick={() => { const name = window.prompt("Section name", section.name); if (name?.trim()) void props.onRun(section.id, () => api.updateDiningSection(section.id, { name: name.trim() }, props.organizationId, props.accessToken)); }}>Rename</button><button type="button" disabled={props.busy === section.id} onClick={() => { const sortOrder = Number(window.prompt("Sort order", String(section.sort_order))); if (Number.isInteger(sortOrder)) void props.onRun(section.id, () => api.updateDiningSection(section.id, { sort_order: sortOrder }, props.organizationId, props.accessToken)); }}>Sort</button><button type="button" disabled={props.busy === section.id} onClick={() => void props.onRun(section.id, () => api.updateDiningSection(section.id, { is_active: !section.is_active }, props.organizationId, props.accessToken))}>{section.is_active ? "Deactivate" : "Activate"}</button></div></div>)}</div>
    <div className="summary-card"><h2>Tables</h2><div className="foh-inline-form"><input aria-label="Table name" maxLength={50} placeholder="T1" value={props.tableName} onChange={(event) => props.onTableName(event.target.value)} /><select aria-label="Table section" value={props.tableSectionId} onChange={(event) => props.onTableSection(event.target.value)}><option value="">Choose section</option>{activeSections.map((section) => <option key={section.id} value={section.id}>{section.name}</option>)}</select><input aria-label="Table capacity" type="number" min="1" value={props.tableCapacity} onChange={(event) => props.onTableCapacity(Number(event.target.value))} /><button type="button" disabled={!!props.busy || !props.tableName.trim() || !props.tableSectionId || props.tableCapacity < 1} onClick={() => void props.onRun("table-new", async () => { await api.createDiningTable({ location_id: props.locationId, section_id: props.tableSectionId, name: props.tableName.trim(), capacity: props.tableCapacity }, props.organizationId, props.accessToken); props.onCreatedTable(); })}>Create</button></div>{props.tables.map((table) => <div className="foh-config-row" key={table.id}><span><strong>{table.name}</strong><small>{props.sections.find((section) => section.id === table.section_id)?.name} · capacity {table.capacity} · sort {table.sort_order} · {table.is_active ? "Active" : "Inactive"}</small></span><div><select aria-label={`Section for ${table.name}`} disabled={props.busy === table.id} value={table.section_id} onChange={(event) => void props.onRun(table.id, () => api.updateDiningTable(table.id, { section_id: event.target.value }, props.organizationId, props.accessToken))}>{activeSections.map((section) => <option key={section.id} value={section.id}>{section.name}</option>)}</select><button type="button" disabled={props.busy === table.id} onClick={() => { const name = window.prompt("Table name", table.name); if (name?.trim()) void props.onRun(table.id, () => api.updateDiningTable(table.id, { name: name.trim() }, props.organizationId, props.accessToken)); }}>Rename</button><button type="button" disabled={props.busy === table.id} onClick={() => { const capacity = Number(window.prompt("Capacity", String(table.capacity))); if (capacity > 0) void props.onRun(table.id, () => api.updateDiningTable(table.id, { capacity }, props.organizationId, props.accessToken)); }}>Capacity</button><button type="button" disabled={props.busy === table.id} onClick={() => { const sortOrder = Number(window.prompt("Sort order", String(table.sort_order))); if (Number.isInteger(sortOrder)) void props.onRun(table.id, () => api.updateDiningTable(table.id, { sort_order: sortOrder }, props.organizationId, props.accessToken)); }}>Sort</button><button type="button" disabled={props.busy === table.id} onClick={() => void props.onRun(table.id, () => api.updateDiningTable(table.id, { is_active: !table.is_active }, props.organizationId, props.accessToken))}>{table.is_active ? "Deactivate" : "Activate"}</button></div></div>)}</div>
    {props.settings && <div className="summary-card"><h2>Reservation policy</h2><div className="foh-policy"><label>Public slug<input value={props.settings.public_slug} onChange={(event) => props.onSettings({ ...props.settings!, public_slug: event.target.value.toLowerCase() })} /></label><label>Duration (minutes)<input type="number" min="1" value={props.settings.default_duration_minutes} onChange={(event) => props.onSettings({ ...props.settings!, default_duration_minutes: Number(event.target.value) })} /></label><label>Cleanup buffer<input type="number" min="0" value={props.settings.cleanup_buffer_minutes} onChange={(event) => props.onSettings({ ...props.settings!, cleanup_buffer_minutes: Number(event.target.value) })} /></label><label>Lead time<input type="number" min="0" value={props.settings.minimum_lead_minutes} onChange={(event) => props.onSettings({ ...props.settings!, minimum_lead_minutes: Number(event.target.value) })} /></label><label>Advance days<input type="number" min="1" value={props.settings.maximum_advance_days} onChange={(event) => props.onSettings({ ...props.settings!, maximum_advance_days: Number(event.target.value) })} /></label><label>Cancellation cutoff<input type="number" min="0" value={props.settings.guest_cancellation_cutoff_minutes} onChange={(event) => props.onSettings({ ...props.settings!, guest_cancellation_cutoff_minutes: Number(event.target.value) })} /></label><label>Maximum party<input type="number" min="1" value={props.settings.maximum_party_size} onChange={(event) => props.onSettings({ ...props.settings!, maximum_party_size: Number(event.target.value) })} /></label><label>Slot interval<input type="number" min="1" value={props.settings.slot_interval_minutes} onChange={(event) => props.onSettings({ ...props.settings!, slot_interval_minutes: Number(event.target.value) })} /></label><label className="foh-enabled"><input type="checkbox" checked={props.settings.reservations_enabled} onChange={(event) => props.onSettings({ ...props.settings!, reservations_enabled: event.target.checked })} /> Reservations enabled</label></div><h3>Booking hours</h3>{props.settings.schedules.map((row, index) => <div className="foh-schedule" key={`${row.weekday}-${index}`}><select aria-label={`Booking day ${index + 1}`} value={row.weekday} onChange={(event) => props.onSettings({ ...props.settings!, schedules: props.settings!.schedules.map((item, rowIndex) => rowIndex === index ? { ...item, weekday: Number(event.target.value) } : item) })}>{WEEKDAYS.map((day, dayIndex) => <option key={day} value={dayIndex}>{day}</option>)}</select><input aria-label={`Booking opens ${index + 1}`} type="time" value={row.opens_at_local.slice(0, 5)} onChange={(event) => props.onSettings({ ...props.settings!, schedules: props.settings!.schedules.map((item, rowIndex) => rowIndex === index ? { ...item, opens_at_local: event.target.value } : item) })} /><input aria-label={`Booking closes ${index + 1}`} type="time" value={row.closes_at_local.slice(0, 5)} onChange={(event) => props.onSettings({ ...props.settings!, schedules: props.settings!.schedules.map((item, rowIndex) => rowIndex === index ? { ...item, closes_at_local: event.target.value } : item) })} /><button type="button" onClick={() => props.onSettings({ ...props.settings!, schedules: props.settings!.schedules.filter((_, rowIndex) => rowIndex !== index) })}>Remove</button></div>)}<div className="button-row"><button type="button" onClick={() => props.onSettings({ ...props.settings!, schedules: [...props.settings!.schedules, { weekday: 0, opens_at_local: "09:00", closes_at_local: "22:00" }] })}>Add hours</button><button className="primary-button" type="button" disabled={!!props.busy || !props.settings.public_slug} onClick={() => void props.onRun("settings", () => api.saveReservationSettings(props.settings!, props.organizationId, props.accessToken))}>Save policy</button><Link href={`/reserve/${props.settings.public_slug}`} target="_blank">Open guest booking</Link></div></div>}
  </section>;
}

const editableSettings = ({ location_id, public_slug, reservations_enabled, default_duration_minutes, cleanup_buffer_minutes, minimum_lead_minutes, maximum_advance_days, guest_cancellation_cutoff_minutes, maximum_party_size, slot_interval_minutes, schedules }: ReservationSettingsInput): ReservationSettingsInput => ({ location_id, public_slug, reservations_enabled, default_duration_minutes, cleanup_buffer_minutes, minimum_lead_minutes, maximum_advance_days, guest_cancellation_cutoff_minutes, maximum_party_size, slot_interval_minutes, schedules });
const defaultSettings = (locationId: string): ReservationSettingsInput => ({ location_id: locationId, public_slug: `reserve-${locationId.slice(0, 8)}`, reservations_enabled: false, default_duration_minutes: 90, cleanup_buffer_minutes: 15, minimum_lead_minutes: 60, maximum_advance_days: 30, guest_cancellation_cutoff_minutes: 60, maximum_party_size: 12, slot_interval_minutes: 15, schedules: [] });
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const messageOf = (error: unknown) => error instanceof Error ? error.message : "Something went wrong";
const titleCase = (value: string) => value.toLowerCase().replaceAll("_", " ").replace(/^./, (first) => first.toUpperCase());
const elapsedVisit = (openedAt: string, now: number) => {
  const minutes = Math.max(0, Math.floor((now - new Date(openedAt).getTime()) / 60_000));
  return minutes < 60 ? `${minutes}m` : `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
};
