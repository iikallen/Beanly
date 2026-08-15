"use client";

import { Check, Clock3, CookingPot, ReceiptText } from "lucide-react";
import { useEffect, useState } from "react";

import { api, type PublicOnlineOrder } from "@/lib/api";
import { formatMenuPriceMinor } from "@/lib/menu";

const stages = ["Order received", "Accepted", "Payment required", "Preparing", "Ready", "Completed"] as const;

export function PublicOrderStatus({ statusToken }: { statusToken: string }) {
  const [order, setOrder] = useState<PublicOnlineOrder | null>(null);
  const [error, setError] = useState("");
  const [cancelling, setCancelling] = useState(false);
  useEffect(() => {
    let cancelled = false;
    let timer = 0;
    const poll = async () => {
      let terminal = false;
      try { const next = await api.getPublicOnlineOrder(statusToken); terminal = ["COMPLETED", "REJECTED", "CANCELLED"].includes(next.status); if (!cancelled) { setOrder(next); setError(""); } }
      catch (caught) { if (!cancelled) setError(caught instanceof Error ? caught.message : "Order unavailable"); }
      if (!cancelled && !terminal) timer = window.setTimeout(poll, 4000);
    };
    void poll();
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [statusToken]);

  if (!order) return <main className="public-order-state" aria-live="polite">{error || "Loading order…"}</main>;
  const current = ({ PENDING: 0, AWAITING_PAYMENT: 2, PAID: 2, PREPARING: 3, READY: 4, COMPLETED: 5 } as Record<string, number>)[order.status] ?? -1;
  const currentStep = order.status === "PAID" ? -1 : current;
  const terminal = order.status === "REJECTED" || order.status === "CANCELLED";
  return <main className="public-status-page" aria-live="polite"><ReceiptText aria-hidden="true" /><p className="eyebrow">Order #{order.source === "QR" ? "Q" : "O"}-{order.order_number}</p><h1>{copy(order.status)}</h1><p>{order.source === "QR" ? order.station_label || "QR order" : titleCase(order.fulfillment_type)} · {order.fulfillment_timing === "ASAP" ? "ASAP" : `Scheduled ${minuteDateTime(order.requested_at!)}`}</p>
    <section className="public-status-details" aria-label="Fulfillment details"><p><span>Promised</span><strong>{minuteDateTime(order.promised_at)}</strong></p>{order.delivery_zone && <p><span>Delivery zone</span><strong>{order.delivery_zone.name}</strong></p>}{order.delivery_address && <p><span>Address</span><strong>{order.delivery_address}</strong></p>}{order.guest_instructions && <p><span>Instructions</span><strong>{order.guest_instructions}</strong></p>}<p><span>Subtotal</span><strong>{formatMenuPriceMinor(order.subtotal_minor, order.currency_code)}</strong></p>{order.discount_minor !== "0" && <p><span>Discount</span><strong>−{formatMenuPriceMinor(order.discount_minor, order.currency_code)}</strong></p>}{order.fulfillment_fee_minor !== "0" && <p><span>Delivery fee</span><strong>{formatMenuPriceMinor(order.fulfillment_fee_minor, order.currency_code)}</strong></p>}<p><span>Total</span><strong>{formatMenuPriceMinor(order.total_minor, order.currency_code)}</strong></p></section>
    {!terminal && <ol>{stages.map((stage, index) => <li aria-current={index === currentStep ? "step" : undefined} className={index <= current ? "is-done" : ""} key={stage}>{index < current || currentStep === -1 && index <= current ? <Check aria-hidden="true" /> : index === currentStep ? <CookingPot aria-hidden="true" /> : <Clock3 aria-hidden="true" />}<span>{stage}</span></li>)}</ol>}
    {terminal && <p>{order.rejection_reason || order.cancel_reason || "This order will not be prepared."}</p>}
    {order.can_cancel && <button type="button" disabled={cancelling} onClick={() => { setCancelling(true); setError(""); void api.cancelPublicOnlineOrder(statusToken).then(setOrder).catch((caught) => setError(caught instanceof Error ? caught.message : "Unable to cancel")).finally(() => setCancelling(false)); }}>{cancelling ? "Cancelling…" : "Cancel order"}</button>}
    {!order.can_cancel && order.cancellation_deadline && !terminal && <small>Cancellation closed at {minuteDateTime(order.cancellation_deadline)}.</small>}
    {error && <p className="form-error" role="alert">{error}</p>}
  </main>;
}

const copy = (stage: string) => ({ PENDING: "Order received", AWAITING_PAYMENT: "Payment required", PAID: "Payment received", PREPARING: "Preparing", READY: "Ready", COMPLETED: "Completed", REJECTED: "Order rejected", CANCELLED: "Order cancelled" }[stage] ?? stage);
const minuteDateTime = (value: string) => new Date(value).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
const titleCase = (value: string) => value.toLowerCase().replaceAll("_", " ").replace(/^./, (first) => first.toUpperCase());
