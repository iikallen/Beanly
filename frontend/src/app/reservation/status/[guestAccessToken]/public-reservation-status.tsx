"use client";

import { CalendarCheck, Clock3, UsersRound } from "lucide-react";
import { useEffect, useState } from "react";

import { api, type PublicReservation } from "@/lib/api";
import { reservationMinute } from "@/lib/reservations";

export function PublicReservationStatus({ guestAccessToken }: { guestAccessToken: string }) {
  const [reservation, setReservation] = useState<PublicReservation | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    let timer = 0;
    const poll = async () => {
      let terminal = false;
      try {
        const value = await api.getPublicReservation(guestAccessToken);
        terminal = ["CANCELLED", "COMPLETED", "NO_SHOW"].includes(value.status);
        if (!cancelled) { setReservation(value); setError(""); }
      } catch (caught) { if (!cancelled) setError(messageOf(caught)); }
      if (!cancelled && !terminal) timer = window.setTimeout(poll, 5000);
    };
    void poll();
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [guestAccessToken]);

  if (!reservation) return <main className="public-order-state" aria-live="polite">{error || "Loading reservation…"}</main>;
  const terminal = ["CANCELLED", "COMPLETED", "NO_SHOW"].includes(reservation.status);

  return <main className="public-reservation-status" aria-live="polite">
    <CalendarCheck aria-hidden="true" />
    <p className="eyebrow">{reservation.organization_name} · {reservation.location_name}</p>
    <h1>{statusCopy(reservation.status)}</h1>
    <section aria-label="Reservation details">
      <p><Clock3 aria-hidden="true" /><span>Date and time</span><strong>{reservationMinute(reservation.start_at, reservation.timezone)}</strong></p>
      <p><UsersRound aria-hidden="true" /><span>Party size</span><strong>{reservation.party_size}</strong></p>
      <p><span>Name</span><strong>{reservation.guest_name}</strong></p>
      {reservation.guest_notes && <p><span>Request</span><strong>{reservation.guest_notes}</strong></p>}
    </section>
    {reservation.can_cancel && <button className="danger-button" type="button" disabled={cancelling} onClick={() => { setCancelling(true); setError(""); void api.cancelPublicReservation(guestAccessToken).then(setReservation).catch((caught) => setError(messageOf(caught))).finally(() => setCancelling(false)); }}>{cancelling ? "Cancelling…" : "Cancel reservation"}</button>}
    {!reservation.can_cancel && !terminal && <small>This reservation can no longer be cancelled online. Please contact the restaurant.</small>}
    {error && <p className="form-error" role="alert">{error}</p>}
  </main>;
}

const statusCopy = (status: PublicReservation["status"]) => ({ BOOKED: "Reservation confirmed", SEATED: "You are seated", COMPLETED: "Visit completed", CANCELLED: "Reservation cancelled", NO_SHOW: "Marked as no-show" })[status];
const messageOf = (error: unknown) => error instanceof Error ? error.message : "Reservation unavailable";
