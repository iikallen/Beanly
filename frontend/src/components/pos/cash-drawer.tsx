"use client";

import { RefreshCcw, WalletCards, X } from "lucide-react";
import { useEffect, useState } from "react";

import {
  ApiError,
  api,
  type CashDrawer,
  type CashDrawerSummary,
  type FiscalShiftStatusResponse,
  type RegisterShift,
} from "@/lib/api";
import { formatMenuPriceMinor, parseMenuPriceToMinor } from "@/lib/menu";

type Props = {
  accessToken: string;
  organizationId: string;
  shift: RegisterShift;
  drawer: CashDrawer | null;
  currency: string;
  permissions: string[];
  pendingOperations: number;
  hasOpenOrders: boolean;
  online: boolean;
  busy: boolean;
  onCloseStarted: () => Promise<void>;
  onDrawer: (drawer: CashDrawer) => void;
  onClosed: () => void;
};

type CloseStep = "SYNC" | "ORDERS" | "COUNT" | "APPROVAL" | "FISCAL" | "CLOSED";

export function CashDrawerControls(props: Props) {
  const { drawer, permissions } = props;
  const canAdjust = permissions.includes("cash.drawer.adjust");
  const canClose = permissions.includes("cash.drawer.close");
  const canApprove = permissions.includes("cash.drawer.approve_variance");
  const canViewExpected = permissions.includes("cash.drawer.view_expected");
  const [movement, setMovement] = useState<"pay-in" | "pay-out" | null>(null);
  const [movementAmount, setMovementAmount] = useState("");
  const [movementReason, setMovementReason] = useState("");
  const [movementNote, setMovementNote] = useState("");
  const [closeOpen, setCloseOpen] = useState(false);
  const [step, setStep] = useState<CloseStep>("SYNC");
  const [summary, setSummary] = useState<CashDrawerSummary | null>(null);
  const [fiscal, setFiscal] = useState<FiscalShiftStatusResponse | null>(null);
  const [actual, setActual] = useState("");
  const [closeNote, setCloseNote] = useState("");
  const [approvalReason, setApprovalReason] = useState("");
  const [requestId, setRequestId] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (!closeOpen || !drawer || drawer.status !== "CLOSING") return;
    let cancelled = false;
    Promise.all([
      api.getCashDrawerSummary(drawer.id, props.organizationId, props.accessToken),
      api.getFiscalShiftStatus(props.shift.id, props.organizationId, props.accessToken),
    ]).then(([nextSummary, nextFiscal]) => {
      if (cancelled) return;
      setSummary(nextSummary);
      setFiscal(nextFiscal);
      setStep(nextSummary.drawer.status === "CLOSED" ? "CLOSED" : nextFiscal.status === "NOT_REQUIRED" ? "APPROVAL" : "FISCAL");
    }).catch((caught) => { if (!cancelled) setMessage(messageOf(caught)); });
    return () => { cancelled = true; };
  }, [closeOpen, drawer, props.accessToken, props.organizationId, props.shift.id]);

  function openClose() {
    setCloseOpen(true);
    setMessage("");
    setRequestId(drawer?.client_close_id ?? crypto.randomUUID());
    setStep(drawer?.status === "CLOSING" ? "FISCAL" : "SYNC");
  }

  async function submitMovement() {
    const amount = parseMenuPriceToMinor(movementAmount);
    if (!drawer || !movement || !amount || BigInt(amount) <= BigInt(0) || !movementReason.trim()) return;
    if (movement === "pay-out" && !movementReason.trim()) return;
    setSaving(true); setMessage("");
    try {
      await api.createCashDrawerMovement(drawer.id, movement, {
        client_movement_id: crypto.randomUUID(), amount_minor: amount, reason: movementReason.trim(), note: movementNote.trim() || undefined,
      }, props.organizationId, props.accessToken);
      props.onDrawer(await api.getCashDrawer(drawer.id, props.organizationId, props.accessToken));
      setMovement(null); setMovementAmount(""); setMovementReason(""); setMovementNote("");
    } catch (caught) { setMessage(messageOf(caught)); }
    finally { setSaving(false); }
  }

  async function submitClose() {
    const actualMinor = parseMenuPriceToMinor(actual);
    if (!drawer || !actualMinor) return;
    setSaving(true); setMessage("");
    try {
      const next = await api.closeCashDrawer(drawer.id, {
        client_close_id: requestId, actual_cash_minor: actualMinor, note: closeNote.trim() || undefined,
        pending_offline_operations: props.pendingOperations,
      }, props.organizationId, props.accessToken);
      await props.onCloseStarted();
      acceptSummary(next);
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === "CASH_VARIANCE_APPROVAL_REQUIRED") {
        const next = await api.getCashDrawerSummary(drawer.id, props.organizationId, props.accessToken);
        await props.onCloseStarted();
        setSummary(next); props.onDrawer(next.drawer); setStep("APPROVAL");
        setMessage(canApprove ? "Variance requires a manager reason and approval." : "Variance requires manager approval.");
      } else if (caught instanceof ApiError && caught.code === "SHIFT_CLOSE_SYNC_PENDING") {
        setStep("SYNC"); setMessage("Server sync is still pending. Synchronize every operation before closing.");
      } else if (caught instanceof ApiError && ["FISCAL_SHIFT_CLOSE_UNKNOWN", "FISCAL_SHIFT_RECONCILIATION_REQUIRED", "FISCAL_SHIFT_CLOSE_FAILED"].includes(caught.code ?? "")) {
        const [nextSummary, nextFiscal] = await Promise.all([
          api.getCashDrawerSummary(drawer.id, props.organizationId, props.accessToken),
          api.getFiscalShiftStatus(props.shift.id, props.organizationId, props.accessToken),
        ]);
        await props.onCloseStarted();
        setSummary(nextSummary); setFiscal(nextFiscal); props.onDrawer(nextSummary.drawer); setStep("FISCAL");
      } else if (caught instanceof ApiError && caught.code === "CASH_CLOSE_IDEMPOTENCY_CONFLICT") {
        const current = await api.getCashDrawer(drawer.id, props.organizationId, props.accessToken);
        props.onDrawer(current);
        if (current.status === "CLOSING" && current.client_close_id) {
          const [nextSummary, nextFiscal] = await Promise.all([
            api.getCashDrawerSummary(drawer.id, props.organizationId, props.accessToken),
            api.getFiscalShiftStatus(props.shift.id, props.organizationId, props.accessToken),
          ]);
          await props.onCloseStarted();
          setRequestId(current.client_close_id); setSummary(nextSummary); setFiscal(nextFiscal);
          setStep(nextFiscal.status === "NOT_REQUIRED" ? "APPROVAL" : "FISCAL");
          setMessage("This close is already in progress. Resume its existing result.");
        } else setMessage(messageOf(caught));
      } else setMessage(messageOf(caught));
    } finally { setSaving(false); }
  }

  async function approveVariance() {
    if (!drawer || !approvalReason.trim()) return;
    setSaving(true); setMessage("");
    try { acceptSummary(await api.approveCashVariance(drawer.id, approvalReason.trim(), props.organizationId, props.accessToken)); }
    catch (caught) { setMessage(messageOf(caught)); }
    finally { setSaving(false); }
  }

  function acceptSummary(next: CashDrawerSummary) {
    setSummary(next); props.onDrawer(next.drawer);
    if (next.drawer.status === "CLOSED") setStep("CLOSED");
    else setStep("FISCAL");
  }

  async function refreshFiscal() {
    if (!drawer) return;
    setSaving(true); setMessage("");
    try {
      const [nextFiscal, nextSummary] = await Promise.all([
        api.getFiscalShiftStatus(props.shift.id, props.organizationId, props.accessToken),
        api.getCashDrawerSummary(drawer.id, props.organizationId, props.accessToken),
      ]);
      setFiscal(nextFiscal); acceptSummary(nextSummary);
    } catch (caught) { setMessage(messageOf(caught)); }
    finally { setSaving(false); }
  }

  async function requestXReport() {
    setSaving(true); setMessage("");
    try { setFiscal(await api.requestFiscalXReport(props.shift.id, props.organizationId, props.accessToken)); }
    catch (caught) { setMessage(messageOf(caught)); }
    finally { setSaving(false); }
  }

  async function reconcileFiscal() {
    if (!drawer) return;
    setSaving(true); setMessage("");
    try {
      const nextFiscal = await api.reconcileFiscalShift(props.shift.id, props.organizationId, props.accessToken);
      const nextSummary = await api.getCashDrawerSummary(drawer.id, props.organizationId, props.accessToken);
      setFiscal(nextFiscal); acceptSummary(nextSummary);
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === "FISCAL_SHIFT_RECONCILIATION_REQUIRED") setMessage("Provider result is still unresolved. No new Z-report was sent.");
      else setMessage(messageOf(caught));
    } finally { setSaving(false); }
  }

  if (!drawer) return <span className="pos-drawer-loading">Loading drawer…</span>;
  const checksReady = props.online && props.pendingOperations === 0 && !props.hasOpenOrders;
  const actualMinor = parseMenuPriceToMinor(actual);
  const fiscalUnknown = fiscal?.status === "UNKNOWN" || fiscal?.status === "RECONCILIATION_REQUIRED";

  return <>
    <span className={`pos-drawer-state status-${drawer.status.toLowerCase()}`}><WalletCards aria-hidden="true" />Drawer {drawer.status.toLowerCase()}</span>
    {drawer.status === "OPEN" && canAdjust && <>
      <button className="secondary-button" type="button" onClick={() => setMovement("pay-in")}>Pay in</button>
      <button className="secondary-button" type="button" onClick={() => setMovement("pay-out")}>Pay out</button>
    </>}
    {drawer.status === "OPEN" && canViewExpected && <button className="secondary-button" disabled={saving} type="button" onClick={() => void requestXReport()}>X report</button>}
    {fiscal?.job_type === "FISCAL_SHIFT_X_REPORT" && <span className="pos-x-report">X report {fiscal.status.toLowerCase()}</span>}
    {canClose && <button className="secondary-button" disabled={props.busy || !props.online} type="button" onClick={openClose}>{drawer.status === "CLOSING" ? "Resume close" : "Close shift"}</button>}

    {movement && <div className="modal-backdrop" role="presentation"><section aria-labelledby="cash-movement-title" aria-modal="true" className="modal-card cash-modal" role="dialog">
      <button className="modal-close" aria-label="Close" type="button" onClick={() => setMovement(null)}><X /></button>
      <h2 id="cash-movement-title">{movement === "pay-in" ? "Pay in" : "Pay out"}</h2>
      <label className="modal-field"><span>Amount</span><input autoFocus inputMode="decimal" value={movementAmount} onChange={(event) => setMovementAmount(event.target.value)} /></label>
      <label className="modal-field"><span>Reason</span><input required value={movementReason} onChange={(event) => setMovementReason(event.target.value)} /></label>
      <label className="modal-field"><span>Note</span><input value={movementNote} onChange={(event) => setMovementNote(event.target.value)} /></label>
      {message && <p className="form-message error" role="alert">{message}</p>}
      <div className="modal-actions"><button className="secondary-button" type="button" onClick={() => setMovement(null)}>Cancel</button><button className="primary-button" disabled={saving || !parseMenuPriceToMinor(movementAmount) || !movementReason.trim()} type="button" onClick={() => void submitMovement()}>{saving ? "Saving…" : "Record"}</button></div>
    </section></div>}

    {closeOpen && <div className="modal-backdrop" role="presentation"><section aria-labelledby="cash-close-title" aria-modal="true" className="modal-card cash-close-modal" role="dialog">
      {step !== "CLOSED" && <button className="modal-close" aria-label="Close" type="button" onClick={() => setCloseOpen(false)}><X /></button>}
      <h2 id="cash-close-title">Close shift</h2>
      <ol className="cash-close-steps" aria-label="Close progress">
        {["Sync check", "Open orders", "Count cash", "Variance approval", "Fiscal close", "Closed"].map((label, index) => <li className={index <= closeIndex(step) ? "is-active" : ""} key={label}>{label}</li>)}
      </ol>
      {step === "SYNC" && <div className="cash-close-panel"><h3>Synchronize POS</h3><p>{props.pendingOperations ? `Syncing ${props.pendingOperations} operations…` : props.online ? "All local operations are synchronized." : "Reconnect POS before closing."}</p><button className="primary-button" disabled={!checksReady} type="button" onClick={() => setStep("ORDERS")}>Continue</button></div>}
      {step === "ORDERS" && <div className="cash-close-panel"><h3>Open orders check</h3><p>{props.hasOpenOrders ? "Resolve every open order before close." : "No open orders remain."}</p><button className="primary-button" disabled={props.hasOpenOrders} type="button" onClick={() => setStep("COUNT")}>Count cash</button></div>}
      {step === "COUNT" && <div className="cash-close-panel"><h3>Count cash</h3><p>Enter the physical cash count. The expected amount stays hidden during a blind close.</p><label className="modal-field"><span>Actual cash</span><input autoFocus inputMode="decimal" value={actual} onChange={(event) => setActual(event.target.value)} /></label><label className="modal-field"><span>Note</span><input value={closeNote} onChange={(event) => setCloseNote(event.target.value)} /></label><button className="primary-button" disabled={saving || !actualMinor || !props.online || props.pendingOperations > 0 || props.hasOpenOrders} type="button" onClick={() => void submitClose()}>{saving ? "Starting close…" : "Submit count"}</button></div>}
      {step === "APPROVAL" && <div className="cash-close-panel"><h3>Variance approval</h3>{summary?.expected_visible && canViewExpected ? <CashSummary summary={summary} currency={props.currency} /> : <p>The count was recorded. Expected cash and variance remain hidden from this role.</p>}{canApprove ? <><label className="modal-field"><span>Manager reason</span><input value={approvalReason} onChange={(event) => setApprovalReason(event.target.value)} /></label><button className="primary-button" disabled={saving || !approvalReason.trim()} type="button" onClick={() => void approveVariance()}>{saving ? "Approving…" : "Approve variance"}</button></> : <p className="cash-close-warning">A manager with variance approval permission must resume this close.</p>}</div>}
      {step === "FISCAL" && <div className="cash-close-panel"><h3>Fiscal close</h3><p>{fiscalUnknown ? "Fiscal result is unknown. Do not retry the Z-report; provider reconciliation is required." : fiscal?.status === "FAILED" ? "Fiscal close failed. The shift remains closing." : `Z-report ${fiscal?.status.toLowerCase() ?? "is being confirmed"}.`}</p>{fiscalUnknown && <p className="cash-close-warning">The drawer remains CLOSING until reconciliation confirms the provider result.</p>}<div className="cash-fiscal-actions"><button className="secondary-button" disabled={saving} type="button" onClick={() => void refreshFiscal()}><RefreshCcw className={saving ? "is-spinning" : ""} />Refresh status</button>{fiscalUnknown && canApprove && <button className="primary-button" disabled={saving} type="button" onClick={() => void reconcileFiscal()}>Reconcile provider</button>}</div></div>}
      {step === "CLOSED" && <div className="cash-close-panel is-complete"><h3>Shift closed</h3>{summary?.expected_visible && canViewExpected && <CashSummary summary={summary} currency={props.currency} />}<button className="primary-button" type="button" onClick={props.onClosed}>Done</button></div>}
      {message && <p className="form-message error" role="alert">{message}</p>}
    </section></div>}
  </>;
}

function CashSummary({ summary, currency }: { summary: CashDrawerSummary; currency: string }) {
  return <dl className="cash-summary">
    <div><dt>Starting</dt><dd>{formatMenuPriceMinor(summary.starting_cash_minor ?? "0", currency)}</dd></div>
    <div><dt>Cash sales</dt><dd>{formatMenuPriceMinor(summary.cash_payments_minor ?? "0", currency)}</dd></div>
    <div><dt>Cash refunds</dt><dd>{formatMenuPriceMinor(summary.cash_refunds_minor ?? "0", currency)}</dd></div>
    <div><dt>Pay in</dt><dd>{formatMenuPriceMinor(summary.pay_in_minor ?? "0", currency)}</dd></div>
    <div><dt>Pay out</dt><dd>{formatMenuPriceMinor(summary.pay_out_minor ?? "0", currency)}</dd></div>
    <div><dt>Expected</dt><dd>{formatMenuPriceMinor(summary.expected_cash_minor ?? "0", currency)}</dd></div>
    <div><dt>Actual</dt><dd>{formatMenuPriceMinor(summary.actual_cash_minor ?? "0", currency)}</dd></div>
    <div><dt>Variance</dt><dd>{formatMenuPriceMinor(summary.variance_minor ?? "0", currency)}</dd></div>
  </dl>;
}

function closeIndex(step: CloseStep) { return ["SYNC", "ORDERS", "COUNT", "APPROVAL", "FISCAL", "CLOSED"].indexOf(step); }
function messageOf(error: unknown) { return error instanceof Error ? error.message : "Cash operation failed."; }
