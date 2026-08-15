"use client";

import { Check, Clock3, CookingPot, ReceiptText } from "lucide-react";
import { useEffect, useState } from "react";

import { api, type PublicOnlineOrder } from "@/lib/api";
import { formatMenuPriceMinor } from "@/lib/menu";

const stages = ["PENDING", "AWAITING_PAYMENT", "PAID", "PREPARING", "READY", "COMPLETED"] as const;

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
  const current = stages.indexOf(order.status as (typeof stages)[number]);
  const terminal = order.status === "REJECTED" || order.status === "CANCELLED";
  return <main className="public-status-page" aria-live="polite"><ReceiptText aria-hidden="true" /><p className="eyebrow">Order status</p><h1>{terminal ? copy(order.status) : order.status.replaceAll("_", " ")}</h1><p>{order.source === "QR" ? order.station_label || "QR order" : "Pickup"} · {formatMenuPriceMinor(order.total_minor, order.currency_code)}</p>
    {!terminal && <ol>{stages.map((stage, index) => <li aria-current={index === current ? "step" : undefined} className={index <= current ? "is-done" : ""} key={stage}>{index < current ? <Check aria-hidden="true" /> : index === current ? <CookingPot aria-hidden="true" /> : <Clock3 aria-hidden="true" />}<span>{copy(stage)}</span></li>)}</ol>}
    {terminal && <p>{order.rejection_reason || order.cancel_reason || "This order will not be prepared."}</p>}
    {order.status === "PENDING" && <button type="button" disabled={cancelling} onClick={() => { setCancelling(true); setError(""); void api.cancelPublicOnlineOrder(statusToken).then(setOrder).catch((caught) => setError(caught instanceof Error ? caught.message : "Unable to cancel")).finally(() => setCancelling(false)); }}>{cancelling ? "Cancelling…" : "Cancel order"}</button>}
    {error && <p className="form-error" role="alert">{error}</p>}
  </main>;
}

const copy = (stage: string) => ({ PENDING: "Order received", AWAITING_PAYMENT: "Accepted · payment at counter", PAID: "Paid", PREPARING: "Preparing", READY: "Ready", COMPLETED: "Completed", REJECTED: "Order rejected", CANCELLED: "Order cancelled" }[stage] ?? stage);
