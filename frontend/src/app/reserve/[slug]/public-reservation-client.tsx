"use client";

import { CalendarDays, Clock3, UsersRound } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, api, type PublicReservationLocation, type ReservationAvailability } from "@/lib/api";
import { localReservationDate, reservationTime } from "@/lib/reservations";

export function PublicReservationClient({ slug }: { slug: string }) {
  const router = useRouter();
  const clientReservationId = useRef(crypto.randomUUID());
  const availabilityRequest = useRef(0);
  const [location, setLocation] = useState<PublicReservationLocation | null>(null);
  const [availability, setAvailability] = useState<ReservationAvailability | null>(null);
  const [date, setDate] = useState("");
  const [partySize, setPartySize] = useState(2);
  const [startAt, setStartAt] = useState("");
  const [guestName, setGuestName] = useState("");
  const [guestPhone, setGuestPhone] = useState("");
  const [guestEmail, setGuestEmail] = useState("");
  const [guestNotes, setGuestNotes] = useState("");
  const [loading, setLoading] = useState(true);
  const [checking, setChecking] = useState(false);
  const [booking, setBooking] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    void api.getPublicReservations(slug)
      .then((value) => {
        if (cancelled) return;
        setLocation(value);
        setDate(localReservationDate(new Date().toISOString(), value.timezone));
      })
      .catch((caught) => { if (!cancelled) setError(messageOf(caught)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [slug]);

  const refreshAvailability = useCallback(async () => {
    if (!date || !location?.reservations_enabled || partySize < 1 || partySize > location.maximum_party_size) return;
    const requestId = ++availabilityRequest.current;
    setChecking(true); setError(""); setStartAt("");
    try { const value = await api.getPublicReservationAvailability(slug, date, partySize); if (availabilityRequest.current === requestId) setAvailability(value); }
    catch (caught) { if (availabilityRequest.current === requestId) { setAvailability(null); setError(messageOf(caught)); } }
    finally { if (availabilityRequest.current === requestId) setChecking(false); }
  }, [date, location, partySize, slug]);

  useEffect(() => {
    if (!date || !location) return;
    queueMicrotask(() => void refreshAvailability());
  }, [date, location, partySize, refreshAvailability]);

  async function book() {
    if (!startAt || !guestName.trim()) return;
    setBooking(true); setError("");
    try {
      const reservation = await api.createPublicReservation(slug, {
        client_reservation_id: clientReservationId.current,
        start_at: startAt,
        party_size: partySize,
        guest_name: guestName.trim(),
        guest_phone: guestPhone.trim() || undefined,
        guest_email: guestEmail.trim() || undefined,
        guest_notes: guestNotes.trim() || undefined,
      });
      router.push(`/reservation/status/${encodeURIComponent(reservation.guest_access_token)}`);
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409 && caught.code === "SLOT_UNAVAILABLE") {
        clientReservationId.current = crypto.randomUUID();
        await refreshAvailability();
        setError("That time was just booked. Availability has been refreshed; choose another time.");
      } else setError(messageOf(caught));
    } finally { setBooking(false); }
  }

  if (loading) return <main className="public-order-state" aria-live="polite">Loading reservation times…</main>;
  if (!location) return <main className="public-order-state"><CalendarDays /><h1>Reservations unavailable</h1><p role="alert">{error}</p></main>;
  const minDate = localReservationDate(new Date().toISOString(), location.timezone);
  const maxDate = addDays(minDate, location.maximum_advance_days);

  return <main className="public-reservation-page">
    <header><CalendarDays aria-hidden="true" /><div><p className="eyebrow">{location.organization_name}</p><h1>{location.location_name}</h1><span>{location.reservations_enabled ? "Choose an available time" : "Reservations are currently closed"}</span></div></header>
    <section aria-labelledby="reservation-details"><h2 id="reservation-details">Your visit</h2>
      <div className="public-reservation-fields">
        <label>Date<input type="date" min={minDate} max={maxDate} disabled={!location.reservations_enabled} value={date} onChange={(event) => setDate(event.target.value)} /></label>
        <label>Party size<input type="number" min="1" max={location.maximum_party_size} disabled={!location.reservations_enabled} value={partySize} onChange={(event) => { setPartySize(Number(event.target.value)); setStartAt(""); setAvailability(null); }} /></label>
      </div>
      <fieldset disabled={checking || !location.reservations_enabled}><legend>Available times</legend>
        {checking ? <p aria-live="polite">Checking availability…</p> : availability?.slots.length ? <div className="reservation-time-grid">{availability.slots.map((slot) => <button type="button" aria-pressed={startAt === slot.start_at} className={startAt === slot.start_at ? "is-active" : ""} key={slot.start_at} onClick={() => setStartAt(slot.start_at)}>{reservationTime(slot.start_at, availability.timezone)}</button>)}</div> : <p>No availability for this date and party size.</p>}
      </fieldset>
    </section>
    <section aria-labelledby="guest-details"><h2 id="guest-details">Guest details</h2>
      <label>Name<input required autoComplete="name" maxLength={201} value={guestName} onChange={(event) => setGuestName(event.target.value)} /></label>
      <label>Phone<input autoComplete="tel" inputMode="tel" maxLength={32} value={guestPhone} onChange={(event) => setGuestPhone(event.target.value)} /></label>
      <label>Email<input autoComplete="email" type="email" maxLength={320} value={guestEmail} onChange={(event) => setGuestEmail(event.target.value)} /></label>
      <label>Request (optional)<textarea maxLength={1000} value={guestNotes} onChange={(event) => setGuestNotes(event.target.value)} /></label>
      <button className="primary-button" type="button" disabled={booking || !location.reservations_enabled || partySize < 1 || partySize > location.maximum_party_size || !startAt || !guestName.trim()} onClick={() => void book()}>{booking ? "Confirming…" : "Confirm reservation"}</button>
      {error && <p className="form-error" role="alert">{error}</p>}
      <small><Clock3 aria-hidden="true" /> Times are confirmed by the restaurant.</small>
    </section>
    <aside><UsersRound aria-hidden="true" /><p>Party of {partySize}</p>{startAt && <strong>{reservationTime(startAt, location.timezone)}</strong>}</aside>
  </main>;
}

const addDays = (date: string, days: number) => {
  const value = new Date(`${date}T12:00:00Z`);
  value.setUTCDate(value.getUTCDate() + days);
  return value.toISOString().slice(0, 10);
};
const messageOf = (error: unknown) => error instanceof Error ? error.message : "Something went wrong";
