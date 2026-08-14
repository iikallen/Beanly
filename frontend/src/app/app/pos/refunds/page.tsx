"use client";

import { ArrowLeft, Check, RotateCcw, X } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { useNetworkStatus } from "@/hooks/use-network-status";
import {
  ApiError,
  api,
  type Payment,
  type Refund,
  type RefundPreview,
  type RefundPreviewRequest,
  type RefundReason,
  type SalesOrder,
} from "@/lib/api";
import { formatMenuPriceMinor, parseMenuPriceToMinor, priceMinorToInput } from "@/lib/menu";
import { trapDialogFocus } from "@/lib/dialog";
import { allocateRefundPayment, refundAttempt, refundDraftTotal, refundedItemQuantity } from "@/lib/refunds";

const REASONS: Array<[RefundReason, string]> = [
  ["QUALITY_ISSUE", "Quality issue"],
  ["WRONG_ITEM", "Wrong item"],
  ["ORDER_ERROR", "Order error"],
  ["CUSTOMER_RETURN", "Customer return"],
  ["DUPLICATE_PAYMENT", "Duplicate payment"],
  ["GOODWILL", "Goodwill"],
  ["OTHER", "Other"],
];

export default function RefundHistoryPage() {
  const { accessToken } = useAuth();
  const { currentOrganization, currentLocation } = useWorkspace();
  const network = useNetworkStatus();
  const [orders, setOrders] = useState<SalesOrder[]>([]);
  const [payments, setPayments] = useState<Payment[]>([]);
  const [refunds, setRefunds] = useState<Refund[]>([]);
  const [permissions, setPermissions] = useState<string[]>([]);
  const [loadedScope, setLoadedScope] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedPaymentId, setSelectedPaymentId] = useState("");
  const [quantities, setQuantities] = useState<Record<string, number>>({});
  const [restocks, setRestocks] = useState<Record<string, number>>({});
  const [paymentAmounts, setPaymentAmounts] = useState<Record<string, string>>({});
  const [externalConfirmed, setExternalConfirmed] = useState<Record<string, boolean>>({});
  const [references, setReferences] = useState<Record<string, string>>({});
  const [reason, setReason] = useState<RefundReason>("QUALITY_ISSUE");
  const [note, setNote] = useState("");
  const [preview, setPreview] = useState<RefundPreview | null>(null);
  const [completed, setCompleted] = useState<Refund | null>(null);
  const [busy, setBusy] = useState(false);
  const pendingRefund = useRef<{ id: string; payload: string } | null>(null);
  const requestId = useRef(0);
  const returnFocus = useRef<HTMLElement | null>(null);

  const organizationId = currentOrganization?.id;
  const locationId = currentLocation?.id;
  const scopeKey = `${organizationId ?? ""}:${locationId ?? ""}`;
  const activeScope = useRef(scopeKey);
  const scopeMatches = loadedScope === scopeKey;
  const canRead = scopeMatches && permissions.includes("sales.read") && permissions.includes("payments.read");
  const canRefund = scopeMatches && permissions.includes("sales.refund") && permissions.includes("payments.refund");

  useEffect(() => { activeScope.current = scopeKey; }, [scopeKey]);

  const load = useCallback(async () => {
    const activeRequestId = ++requestId.current;
    if (!accessToken || !organizationId || !locationId || network.status !== "ONLINE") {
      setPermissions([]);
      setLoadedScope("");
      setOrders([]);
      setPayments([]);
      setRefunds([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    setBusy(false);
    setSelectedPaymentId("");
    setError("");
    setLoadedScope("");
    setOrders([]);
    setPayments([]);
    setRefunds([]);
    try {
      const context = await api.getOrganizationContext(organizationId, accessToken);
      if (requestId.current !== activeRequestId) return;
      setPermissions(context.permissions);
      setLoadedScope(scopeKey);
      if (!context.permissions.includes("sales.read") || !context.permissions.includes("payments.read")) {
        setOrders([]);
        setPayments([]);
        setRefunds([]);
        return;
      }
      const [nextOrders, nextPayments, nextRefunds] = await Promise.all([
        api.listSalesOrders(organizationId, accessToken, { locationId, status: "PAID" }),
        api.listPayments(organizationId, accessToken, { locationId }),
        api.listRefunds(organizationId, accessToken, { locationId }),
      ]);
      if (requestId.current !== activeRequestId) return;
      setOrders(nextOrders);
      setPayments(nextPayments);
      setRefunds(nextRefunds);
    } catch (caught) {
      if (requestId.current === activeRequestId) setError(messageOf(caught));
    } finally {
      if (requestId.current === activeRequestId) setLoading(false);
    }
  }, [accessToken, locationId, network.status, organizationId, scopeKey]);

  useEffect(() => { queueMicrotask(() => { void load(); }); }, [load]);

  const rows = useMemo(() => (scopeMatches ? payments : [])
    .map((payment) => ({ payment, order: orders.find((order) => order.id === payment.order_id) }))
    .filter((row): row is { payment: Payment; order: SalesOrder } => Boolean(row.order))
    .sort((left, right) => right.payment.completed_at.localeCompare(left.payment.completed_at)), [orders, payments, scopeMatches]);
  const selectedPayment = payments.find((payment) => payment.id === selectedPaymentId) ?? null;
  const selectedOrder = selectedPayment ? orders.find((order) => order.id === selectedPayment.order_id) ?? null : null;
  const selectedRefunds = selectedPayment ? refunds.filter((refund) => refund.payment_id === selectedPayment.id) : [];
  const estimatedTotal = selectedOrder ? refundDraftTotal(selectedOrder, quantities, selectedRefunds) : BigInt(0);
  const paymentSum = selectedPayment?.lines.reduce((sum, line) => {
    const minor = parseMenuPriceToMinor(paymentAmounts[line.id] ?? "0");
    return sum + BigInt(minor ?? "0");
  }, BigInt(0)) ?? BigInt(0);

  function openRefund(payment: Payment, order: SalesOrder) {
    returnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const orderRefunds = refunds.filter((refund) => refund.payment_id === payment.id);
    const nextQuantities = Object.fromEntries(order.items.map((item) => [item.id, 0]));
    setSelectedPaymentId(payment.id);
    setQuantities(nextQuantities);
    setRestocks(nextQuantities);
    setPaymentAmounts(Object.fromEntries(payment.lines.map((line) => [line.id, "0"])));
    setExternalConfirmed({});
    setReferences({});
    setReason("QUALITY_ISSUE");
    setNote("");
    setPreview(null);
    setCompleted(null);
    pendingRefund.current = null;
    if (orderRefunds.some((refund) => refund.status === "PENDING")) setError("This payment already has a pending refund.");
  }

  function closeRefund() {
    if (busy) return;
    setSelectedPaymentId("");
    setPreview(null);
    setCompleted(null);
    setError("");
    queueMicrotask(() => returnFocus.current?.focus());
  }

  function changeQuantity(itemId: string, value: number) {
    if (!selectedOrder || !selectedPayment) return;
    const item = selectedOrder.items.find((candidate) => candidate.id === itemId);
    if (!item) return;
    const available = item.quantity - refundedItemQuantity(selectedRefunds, item.id);
    const quantity = Math.max(0, Math.min(available, value));
    const next = { ...quantities, [itemId]: quantity };
    const total = refundDraftTotal(selectedOrder, next, selectedRefunds);
    const allocation = allocateRefundPayment(total, selectedPayment, selectedRefunds);
    setQuantities(next);
    setRestocks((current) => ({ ...current, [itemId]: Math.min(current[itemId] ?? 0, quantity) }));
    setPaymentAmounts(Object.fromEntries(allocation.map(({ line, amount }) => [line.id, priceMinorToInput(String(amount))])));
  }

  function buildRequest(confirmExternal: boolean): RefundPreviewRequest | null {
    if (!selectedPayment || !selectedOrder || estimatedTotal <= BigInt(0) || paymentSum !== estimatedTotal) return null;
    const lines = selectedOrder.items
      .filter((item) => (quantities[item.id] ?? 0) > 0)
      .map((item) => ({
        order_item_id: item.id,
        quantity: quantities[item.id],
        restock_quantity: Math.min(restocks[item.id] ?? 0, quantities[item.id]),
      }));
    const payment_lines = selectedPayment.lines.flatMap((line) => {
      const amount = parseMenuPriceToMinor(paymentAmounts[line.id] ?? "0");
      if (!amount || BigInt(amount) === BigInt(0)) return [];
      return [{
        original_payment_line_id: line.id,
        amount_minor: amount,
        external_refund_confirmed: confirmExternal ? Boolean(externalConfirmed[line.id]) : false,
        reference: references[line.id]?.trim() || null,
      }];
    });
    return { payment_id: selectedPayment.id, reason, note: note.trim() || null, lines, payment_lines };
  }

  async function reviewRefund() {
    if (!accessToken || !organizationId || network.status !== "ONLINE") return;
    const requestScope = scopeKey;
    const request = buildRequest(false);
    if (!request) {
      setError(paymentSum !== estimatedTotal ? "Refund methods must equal the refund total." : "Select at least one item.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const value = await api.previewRefund(request, organizationId, accessToken);
      if (activeScope.current === requestScope) setPreview(value);
    } catch (caught) {
      if (activeScope.current === requestScope) setError(refundError(caught));
    } finally {
      if (activeScope.current === requestScope) setBusy(false);
    }
  }

  async function completeRefund() {
    if (!accessToken || !organizationId || network.status !== "ONLINE" || !preview) return;
    const requestScope = scopeKey;
    const request = buildRequest(true);
    if (!request) return;
    const unconfirmed = selectedPayment?.lines.some((line) => {
      const amount = parseMenuPriceToMinor(paymentAmounts[line.id] ?? "0");
      return amount && BigInt(amount) > BigInt(0) && line.method !== "CASH" && !externalConfirmed[line.id];
    });
    if (unconfirmed) {
      setError("Confirm every card or external refund before completion.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const payload = JSON.stringify(request);
      pendingRefund.current = refundAttempt(pendingRefund.current, payload, () => crypto.randomUUID());
      const value = await api.createRefund({ ...request, client_refund_id: pendingRefund.current.id }, organizationId, accessToken);
      if (activeScope.current !== requestScope) return;
      pendingRefund.current = null;
      setCompleted(value);
      setRefunds((current) => [value, ...current.filter((refund) => refund.id !== value.id)]);
    } catch (caught) {
      if (activeScope.current === requestScope) setError(refundError(caught));
    } finally {
      if (activeScope.current === requestScope) setBusy(false);
    }
  }

  if (network.status === "CHECKING") return <section className="pos-refunds"><div className="pos-refund-state">Checking connection…</div></section>;
  if (network.status === "OFFLINE") return <section className="pos-refunds"><Link className="menu-back-link" href="/app/pos"><ArrowLeft aria-hidden="true" />POS</Link><div className="pos-refund-state is-warning"><strong>Refunds require an internet connection.</strong><span>Offline sales remain available. Reconnect to review or complete a refund.</span></div></section>;
  if (loading) return <section className="pos-refunds"><div className="pos-refund-state">Loading order history…</div></section>;
  if (!scopeMatches) return <section className="pos-refunds"><Link className="menu-back-link" href="/app/pos"><ArrowLeft aria-hidden="true" />POS</Link><div className="pos-refund-state" role="alert"><strong>Order history could not be loaded</strong><span>{error || "An online sign-in is required."}</span>{accessToken && <button className="secondary-button" type="button" onClick={() => void load()}>Try again</button>}</div></section>;

  return (
    <section className="pos-refunds">
      <Link className="menu-back-link" href="/app/pos"><ArrowLeft aria-hidden="true" />POS</Link>
      <header className="pos-refunds-header"><div><span className="pos-eyebrow">Online only</span><h1>Order history</h1><p>Completed sales and immutable refund records.</p></div><button className="secondary-button" type="button" onClick={() => void load()}>Refresh</button></header>
      {error && !selectedPayment && <div className="pos-global-error" role="alert">{error}</div>}
      {!canRead && !loading ? (
        <div className="pos-refund-state"><strong>Refund history access required</strong><span>Your role cannot view completed payments.</span></div>
      ) : rows.length === 0 ? (
        <div className="pos-refund-state"><strong>No paid orders yet</strong><span>Completed orders for this location will appear here.</span></div>
      ) : (
        <div className="pos-history-list">
          {rows.map(({ payment, order }) => {
            const orderRefunds = refunds.filter((refund) => refund.payment_id === payment.id);
            const refunded = orderRefunds.filter((refund) => refund.status === "COMPLETED").reduce((sum, refund) => sum + BigInt(refund.total_amount_minor), BigInt(0));
            const hasRefundableItem = order.items.some((item) => refundedItemQuantity(orderRefunds, item.id) < item.quantity);
            return (
              <article className="pos-history-card" key={payment.id}>
                <div className="pos-history-main"><div><span className="pos-eyebrow">Order #{order.number}</span><h2>{formatMenuPriceMinor(order.total_minor, order.currency_code)}</h2><time dateTime={payment.completed_at}>{formatDate(payment.completed_at)}</time></div><dl><div><dt>Original</dt><dd>{formatMenuPriceMinor(order.total_minor, order.currency_code)}</dd></div><div><dt>Refunded</dt><dd>−{formatMenuPriceMinor(String(refunded), order.currency_code)}</dd></div><div><dt>Net</dt><dd>{formatMenuPriceMinor(String(BigInt(order.total_minor) - refunded), order.currency_code)}</dd></div></dl></div>
                <ul className="pos-history-items">{order.items.map((item) => <li key={item.id}><span>{item.product_name}{item.variant_name ? ` · ${item.variant_name}` : ""} ×{item.quantity}</span><strong>{formatMenuPriceMinor(item.line_total_minor, order.currency_code)}</strong></li>)}</ul>
                {orderRefunds.length > 0 && <div className="pos-refund-records"><strong>Refunds</strong>{orderRefunds.map((refund) => <div key={refund.id}><span>{refund.id.slice(0, 8).toUpperCase()} · {reasonLabel(refund.reason)}</span><span>{formatMenuPriceMinor(refund.total_amount_minor, refund.currency_code)} · {titleCase(refund.status)} · <FiscalReceipt refund={refund} /></span></div>)}</div>}
                <div className="pos-history-actions"><button className="primary-button" disabled={!canRefund || !hasRefundableItem || refunded >= BigInt(payment.amount_minor)} title={!canRefund ? "Your role cannot complete refunds." : !hasRefundableItem || refunded >= BigInt(payment.amount_minor) ? "Payment is fully refunded." : undefined} type="button" onClick={() => openRefund(payment, order)}><RotateCcw aria-hidden="true" />Refund</button></div>
              </article>
            );
          })}
        </div>
      )}

      {selectedPayment && selectedOrder && (
        <div className="modal-backdrop" role="presentation">
          <section className="modal-card pos-refund-modal" role="dialog" aria-modal="true" aria-busy={busy} aria-labelledby="refund-title" onKeyDown={(event) => { if (event.key === "Escape") closeRefund(); else trapDialogFocus(event); }}>
            <button autoFocus className="modal-close" disabled={busy} type="button" aria-label="Close refund" onClick={closeRefund}><X /></button>
            {completed ? (
              <div className="pos-payment-success" role="status"><span className="pos-payment-check" aria-hidden="true"><Check /></span><span className="pos-eyebrow">Refund completed</span><h2 id="refund-title">Order #{selectedOrder.number}</h2><strong>{formatMenuPriceMinor(completed.total_amount_minor, completed.currency_code)}</strong><p>The original sale was not changed. <FiscalReceipt refund={completed} /></p><div className="modal-actions"><button className="primary-button" type="button" onClick={closeRefund}>Done</button></div></div>
            ) : preview ? (
              <RefundConfirmation preview={preview} payment={selectedPayment} restocks={restocks} paymentAmounts={paymentAmounts} externalConfirmed={externalConfirmed} references={references} busy={busy} error={error} onConfirmed={(id, checked) => setExternalConfirmed((current) => ({ ...current, [id]: checked }))} onReference={(id, value) => setReferences((current) => ({ ...current, [id]: value }))} onBack={() => { setPreview(null); setError(""); }} onComplete={() => void completeRefund()} />
            ) : (
              <>
                <span className="pos-eyebrow">Order #{selectedOrder.number}</span><h2 id="refund-title">Refund items</h2><p className="pos-refund-copy">Select quantities. Returning stock is separate from returning money.</p>
                <div className="pos-refund-lines">{selectedOrder.items.map((item) => {
                  const available = item.quantity - refundedItemQuantity(selectedRefunds, item.id);
                  const quantity = quantities[item.id] ?? 0;
                  return <fieldset key={item.id} disabled={available === 0 || busy}><legend><span>{item.product_name} · {item.variant_name}</span><strong>{formatMenuPriceMinor(item.unit_price_minor, selectedOrder.currency_code)}</strong></legend><label><span>Refund quantity <small>{available} available</small></span><input aria-label={`${item.product_name} refund quantity`} type="number" min={0} max={available} step={1} value={quantity} onChange={(event) => changeQuantity(item.id, Number(event.target.value))} /></label><label><span>Return to stock <small>0 for prepared or discarded items</small></span><input aria-label={`${item.product_name} restock quantity`} type="number" min={0} max={quantity} step={1} disabled={quantity === 0} value={restocks[item.id] ?? 0} onChange={(event) => setRestocks((current) => ({ ...current, [item.id]: Math.max(0, Math.min(quantity, Number(event.target.value))) }))} /></label></fieldset>;
                })}</div>
                <div className="pos-refund-total"><span>Refund</span><strong>{formatMenuPriceMinor(String(estimatedTotal), selectedOrder.currency_code)}</strong></div>
                <fieldset className="pos-refund-methods"><legend>Refund method</legend>{allocateRefundPayment(estimatedTotal, selectedPayment, selectedRefunds).map(({ line, available }) => <label key={line.id}><span>{titleCase(line.method)} <small>{formatMenuPriceMinor(String(available), selectedPayment.currency_code)} available</small></span><input inputMode="decimal" value={paymentAmounts[line.id] ?? "0"} onChange={(event) => setPaymentAmounts((current) => ({ ...current, [line.id]: event.target.value }))} /></label>)}<p className={paymentSum === estimatedTotal ? "is-balanced" : ""} aria-live="polite">Allocated {formatMenuPriceMinor(String(paymentSum), selectedPayment.currency_code)} of {formatMenuPriceMinor(String(estimatedTotal), selectedPayment.currency_code)}</p></fieldset>
                <label className="modal-field"><span>Reason</span><select value={reason} onChange={(event) => setReason(event.target.value as RefundReason)}>{REASONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
                <label className="modal-field"><span>Note <small>Optional</small></span><textarea maxLength={2000} placeholder="What happened?" value={note} onChange={(event) => setNote(event.target.value)} /></label>
                {error && <p className="form-message error" role="alert">{error}</p>}
                <div className="modal-actions"><button className="secondary-button" disabled={busy} type="button" onClick={closeRefund}>Cancel</button><button className="primary-button" disabled={busy || estimatedTotal === BigInt(0) || paymentSum !== estimatedTotal} type="button" onClick={() => void reviewRefund()}>{busy ? "Checking…" : "Review refund"}</button></div>
              </>
            )}
          </section>
        </div>
      )}
    </section>
  );
}

function RefundConfirmation({ preview, payment, restocks, paymentAmounts, externalConfirmed, references, busy, error, onConfirmed, onReference, onBack, onComplete }: { preview: RefundPreview; payment: Payment; restocks: Record<string, number>; paymentAmounts: Record<string, string>; externalConfirmed: Record<string, boolean>; references: Record<string, string>; busy: boolean; error: string; onConfirmed: (id: string, checked: boolean) => void; onReference: (id: string, value: string) => void; onBack: () => void; onComplete: () => void }) {
  const externalLines = payment.lines.filter((line) => BigInt(parseMenuPriceToMinor(paymentAmounts[line.id] ?? "0") ?? "0") > BigInt(0) && line.method !== "CASH");
  const gross = preview.lines.reduce((sum, line) => sum + BigInt(line.unit_refund_minor) * BigInt(line.quantity), BigInt(0));
  const discount = gross - BigInt(preview.total_amount_minor);
  const inventory = Object.values(restocks).some((quantity) => quantity > 0) ? "Selected items will be restored" : "Not restored";
  return <><span className="pos-eyebrow">Authoritative preview</span><h2 id="refund-title">Refund {formatMenuPriceMinor(preview.total_amount_minor, preview.currency_code)}?</h2><div className="pos-refund-confirmation"><div><span>Gross</span><strong>{formatMenuPriceMinor(String(gross), preview.currency_code)}</strong></div><div><span>Discount</span><strong>−{formatMenuPriceMinor(String(discount), preview.currency_code)}</strong></div><div><span>Net refund</span><strong>{formatMenuPriceMinor(preview.total_amount_minor, preview.currency_code)}</strong></div><div><span>Money will be returned by</span><strong>{preview.payment_lines.filter((line) => BigInt(line.amount_minor) > BigInt(0)).map((line) => `${line.method} · ${formatMenuPriceMinor(line.amount_minor, preview.currency_code)}`).join(" + ")}</strong></div><div><span>Inventory</span><strong>{inventory}</strong></div><div><span>Fiscal</span><strong>Return receipt will be created</strong></div></div>{externalLines.map((line) => <div className="pos-external-confirm" key={line.id}><label><input type="checkbox" checked={Boolean(externalConfirmed[line.id])} onChange={(event) => onConfirmed(line.id, event.target.checked)} /><span>I confirm the {line.method.toLowerCase()} refund was completed outside Beanly.</span></label><label className="modal-field"><span>Terminal receipt or reference <small>Optional</small></span><input maxLength={200} value={references[line.id] ?? ""} onChange={(event) => onReference(line.id, event.target.value)} /></label></div>)}<p className="pos-refund-immutable">This action cannot be undone. The original paid order remains unchanged.</p>{error && <p className="form-message error" role="alert">{error}</p>}<div className="modal-actions"><button className="secondary-button" disabled={busy} type="button" onClick={onBack}>Back</button><button className="danger-button" disabled={busy || externalLines.some((line) => !externalConfirmed[line.id])} type="button" onClick={onComplete}>{busy ? "Refunding…" : "Complete refund"}</button></div></>;
}

function refundError(error: unknown) {
  if (!(error instanceof ApiError)) return messageOf(error);
  const messages: Record<string, string> = {
    REFUND_QUANTITY_EXCEEDED: "Another refund used some of this item quantity. Reload and review availability.",
    REFUND_PAYMENT_AMOUNT_EXCEEDED: "Another refund used some of this payment. Reload and review availability.",
    EXTERNAL_REFUND_NOT_CONFIRMED: "Confirm every card or external refund before completion.",
    REFUND_TOTAL_MISMATCH: "Refund methods must equal the authoritative refund total.",
    ORDER_NOT_REFUNDABLE: "Only a paid order can be refunded.",
  };
  return error.code && messages[error.code] ? messages[error.code] : error.message;
}

function FiscalReceipt({ refund }: { refund: Refund }) {
  if (refund.fiscal_status === "SUCCESS") {
    const label = `Fiscal return issued${refund.fiscal_external_number ? ` · ${refund.fiscal_external_number}` : ""}`;
    return refund.fiscal_external_url ? <a href={refund.fiscal_external_url} target="_blank" rel="noreferrer">{label}</a> : label;
  }
  if (refund.fiscal_status === "PENDING") return "Fiscal return pending";
  if (refund.fiscal_status === "PROCESSING") return "Fiscal return in progress";
  if (refund.fiscal_status === "RETRYING") return "Fiscal return retrying";
  if (refund.fiscal_status === "DEAD") return "Fiscal return needs attention";
  return "Fiscal integration not configured";
}

function reasonLabel(value: RefundReason) { return REASONS.find(([reason]) => reason === value)?.[1] ?? titleCase(value); }
function titleCase(value: string) { return value.toLowerCase().replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase()); }
function formatDate(value: string) { return new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)); }
function messageOf(error: unknown) { return error instanceof Error ? error.message : "Something went wrong. Please try again."; }
