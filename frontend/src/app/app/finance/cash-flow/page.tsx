"use client";

import { Plus } from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { useFinancePermissions } from "@/hooks/use-finance-permissions";
import { api, type CashAccount, type CashFlowActivity, type CashMovement, type CashMovementType, type FinanceCashFlow } from "@/lib/api";
import { localDateTimeNow, toApiDate } from "@/lib/inventory-operations";
import { currentMonthRange, financeApiRange, formatFinanceDate, formatFinanceMinor, formatFinanceMinorOutflow, toMinorUnits } from "@/lib/finance";

const movementTypes: CashMovementType[] = ["SUPPLIER_PAYMENT", "OWNER_CONTRIBUTION", "OWNER_WITHDRAWAL", "OTHER_INFLOW", "OTHER_OUTFLOW", "TRANSFER"];
const outflowTypes = new Set<CashMovementType>(["SUPPLIER_PAYMENT", "OWNER_WITHDRAWAL", "OTHER_OUTFLOW"]);

export default function CashFlowPage() {
  const { accessToken } = useAuth();
  const { currentOrganization, locations } = useWorkspace();
  const { canRead, canWrite, loading: permissionsLoading } = useFinancePermissions();
  const initial = currentMonthRange();
  const [dateFrom, setDateFrom] = useState(initial.dateFrom);
  const [dateTo, setDateTo] = useState(initial.dateTo);
  const [locationId, setLocationId] = useState("");
  const [report, setReport] = useState<FinanceCashFlow | null>(null);
  const [accounts, setAccounts] = useState<CashAccount[]>([]);
  const [movements, setMovements] = useState<CashMovement[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [type, setType] = useState<CashMovementType>("SUPPLIER_PAYMENT");
  const [amount, setAmount] = useState("");
  const [fromAccountId, setFromAccountId] = useState("");
  const [toAccountId, setToAccountId] = useState("");
  const [activity, setActivity] = useState<CashFlowActivity>("OPERATING");
  const [occurredAt, setOccurredAt] = useState(localDateTimeNow);
  const [description, setDescription] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      await Promise.resolve();
      if (cancelled || !accessToken || !currentOrganization || permissionsLoading || !canRead) return;
      setLoading(true);
      setError("");
      const filters = { ...financeApiRange(dateFrom, dateTo), locationId: locationId || undefined };
      try {
        const [nextReport, nextAccounts, nextMovements] = await Promise.all([
          api.getFinanceCashFlow(currentOrganization.id, accessToken, filters),
          api.listCashAccounts(currentOrganization.id, accessToken),
          api.listCashMovements(currentOrganization.id, accessToken),
        ]);
        if (!cancelled) { setReport(nextReport); setAccounts(nextAccounts); setMovements(nextMovements); }
      } catch (caught) { if (!cancelled) setError(caught instanceof Error ? caught.message : "Unable to load cash flow"); }
      finally { if (!cancelled) setLoading(false); }
    }
    void load();
    return () => { cancelled = true; };
  }, [accessToken, canRead, currentOrganization, dateFrom, dateTo, locationId, permissionsLoading, refreshKey]);

  const activeAccounts = accounts.filter((account) => account.is_active);
  const accountNames = useMemo(() => new Map(accounts.map((account) => [account.id, account.name])), [accounts]);
  const visibleMovements = movements.filter((movement) => !locationId || movement.location_id === locationId || [movement.from_account_id, movement.to_account_id].some((id) => accounts.find((account) => account.id === id)?.location_id === locationId));
  const needsFrom = type === "TRANSFER" || outflowTypes.has(type);
  const needsTo = type === "TRANSFER" || type === "OWNER_CONTRIBUTION" || type === "OTHER_INFLOW";
  const fixedActivity = type === "SUPPLIER_PAYMENT" ? "OPERATING" : type === "OWNER_CONTRIBUTION" || type === "OWNER_WITHDRAWAL" ? "FINANCING" : null;

  async function createMovement(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const amountMinor = toMinorUnits(amount);
    if (!accessToken || !currentOrganization || !amountMinor || BigInt(amountMinor) <= BigInt(0)) { setError("Enter a positive amount with no more than two decimal places."); return; }
    if ((needsFrom && !fromAccountId) || (needsTo && !toAccountId)) { setError("Choose the required cash account."); return; }
    if (type === "TRANSFER" && fromAccountId === toAccountId) { setError("Transfer accounts must be different."); return; }
    const sentFromAccountId = needsFrom ? fromAccountId : "";
    const sentToAccountId = needsTo ? toAccountId : "";
    const selectedAccounts = [sentFromAccountId, sentToAccountId].filter(Boolean).map((id) => accounts.find((account) => account.id === id)).filter((account): account is CashAccount => Boolean(account));
    const derivedLocationId = selectedAccounts.every((account) => account.location_id === selectedAccounts[0]?.location_id) ? selectedAccounts[0]?.location_id ?? null : null;
    setSaving(true); setError("");
    try {
      await api.createCashMovement({ type, amount_minor: amountMinor, from_account_id: sentFromAccountId || null, to_account_id: sentToAccountId || null, cash_flow_activity: fixedActivity ?? activity, occurred_at: toApiDate(occurredAt), description: description.trim() || null, location_id: derivedLocationId }, currentOrganization.id, accessToken);
      setAmount(""); setDescription(""); setShowForm(false); setRefreshKey((value) => value + 1);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to record cash movement"); }
    finally { setSaving(false); }
  }

  async function reverseMovement(movement: CashMovement) {
    if (!accessToken || !currentOrganization || movement.reversed_at || !window.confirm("Reverse this cash movement? Original cash entries will remain in the ledger.")) return;
    setSaving(true); setError("");
    try { await api.reverseCashMovement(movement.id, currentOrganization.id, accessToken); setRefreshKey((value) => value + 1); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to reverse cash movement"); }
    finally { setSaving(false); }
  }

  return (
    <>
      <header className="finance-header"><div><h1>Cash Flow</h1><p>Cash movement is separate from profit.</p></div><div className="finance-header-actions"><label className="finance-filter"><span>Location</span><select value={locationId} onChange={(event) => setLocationId(event.target.value)}><option value="">All locations</option>{locations.map((location) => <option key={location.id} value={location.id}>{location.name}</option>)}</select></label><div className="finance-period"><label><span>From</span><input type="date" value={dateFrom} max={dateTo} onChange={(event) => setDateFrom(event.target.value)} /></label><label><span>To</span><input type="date" value={dateTo} min={dateFrom} onChange={(event) => setDateTo(event.target.value)} /></label></div>{canWrite && <button className="purchasing-primary" type="button" onClick={() => setShowForm((value) => !value)}><Plus aria-hidden="true" /> Cash movement</button>}</div></header>
      {showForm && canWrite && <section className="finance-panel"><h2>Record cash movement</h2><p>This changes cash only. It does not create a P&amp;L expense or income.</p><form className="finance-form" onSubmit={createMovement}><div className="finance-form-grid"><label><span>Type</span><select value={type} onChange={(event) => { const value = event.target.value as CashMovementType; setType(value); setFromAccountId(""); setToAccountId(""); setActivity(value.startsWith("OWNER_") ? "FINANCING" : "OPERATING"); }}>{movementTypes.map((value) => <option key={value} value={value}>{label(value)}</option>)}</select></label><label><span>Amount ({currentOrganization?.currency_code ?? "KZT"})</span><input inputMode="decimal" value={amount} onChange={(event) => setAmount(event.target.value)} required /></label><label><span>Activity</span><select value={fixedActivity ?? activity} onChange={(event) => setActivity(event.target.value as CashFlowActivity)} disabled={fixedActivity !== null}><option value="OPERATING">Operating</option><option value="INVESTING">Investing</option><option value="FINANCING">Financing</option></select></label>{needsFrom && <label><span>From account</span><select value={fromAccountId} onChange={(event) => setFromAccountId(event.target.value)} required><option value="">Select account</option>{activeAccounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}</select></label>}{needsTo && <label><span>To account</span><select value={toAccountId} onChange={(event) => setToAccountId(event.target.value)} required><option value="">Select account</option>{activeAccounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}</select></label>}<label><span>Date</span><input type="datetime-local" value={occurredAt} onChange={(event) => setOccurredAt(event.target.value)} required /></label><label className="is-wide"><span>Note</span><textarea value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Optional details" /></label></div>{error && <div className="finance-inline-error" role="alert">{error}</div>}<div className="finance-form-actions"><button className="secondary-button" type="button" onClick={() => setShowForm(false)}>Cancel</button><button className="purchasing-primary" type="submit" disabled={saving}>{saving ? "Recording…" : "Record movement"}</button></div></form></section>}
      {!permissionsLoading && !canRead ? <div className="finance-state"><strong>Finance access required</strong><span>Your role cannot view cash flow.</span></div> : error && !showForm ? <div className="finance-state is-error" role="alert"><strong>Cash flow could not be loaded.</strong><span>{error}</span></div> : loading || !report ? <div className="finance-state" aria-live="polite">Loading cash flow…</div> : <div className="finance-flow-grid"><section className="finance-statement"><div className="finance-statement-row is-subtotal"><span>Opening cash</span><strong>{formatFinanceMinor(report.opening_cash_minor, report.currency_code)}</strong></div>{(["operating", "investing", "financing"] as const).map((key) => <div key={key}><h2 className="finance-statement-heading">{label(key)}</h2><div className="finance-statement-row"><span>Inflows</span><strong>{formatFinanceMinor(report[key].inflows_minor, report.currency_code)}</strong></div><div className="finance-statement-row is-negative"><span>Outflows</span><strong>{formatFinanceMinorOutflow(report[key].outflows_minor, report.currency_code)}</strong></div><div className="finance-statement-row is-subtotal"><span>Net {key}</span><strong>{formatFinanceMinor(report[key].net_minor, report.currency_code)}</strong></div></div>)}<div className="finance-statement-row is-total"><span>Closing cash</span><strong>{formatFinanceMinor(report.closing_cash_minor, report.currency_code)}</strong></div></section><section className="finance-panel"><h2>Net movement</h2><div className="finance-kpi is-primary"><span>Selected period</span><strong>{formatFinanceMinor(report.net_cash_movement_minor, report.currency_code)}</strong><small>Opening to closing cash</small></div></section></div>}
      <section className="finance-panel"><h2>Manual cash movements</h2>{visibleMovements.length === 0 ? <p>No manual cash movements in this scope.</p> : <div className="finance-table-wrap" tabIndex={0}><table className="finance-table"><thead><tr><th>Date</th><th>Type</th><th>Account</th><th>Amount</th><th>Status</th><th></th></tr></thead><tbody>{visibleMovements.map((movement) => <tr key={movement.id}><td>{formatFinanceDate(movement.occurred_at)}</td><td>{label(movement.type)}</td><td>{movement.type === "TRANSFER" ? `${accountNames.get(movement.from_account_id ?? "") ?? "Account"} → ${accountNames.get(movement.to_account_id ?? "") ?? "Account"}` : accountNames.get((movement.from_account_id ?? movement.to_account_id) ?? "") ?? "Account"}</td><td>{outflowTypes.has(movement.type) ? formatFinanceMinorOutflow(movement.amount_minor, movement.currency_code) : formatFinanceMinor(movement.amount_minor, movement.currency_code)}</td><td><span className={`finance-status status-${movement.reversed_at ? "reversed" : "posted"}`}>{movement.reversed_at ? "reversed" : "posted"}</span></td><td>{canWrite && !movement.reversed_at && <button className="secondary-button is-danger" type="button" onClick={() => reverseMovement(movement)} disabled={saving}>Reverse</button>}</td></tr>)}</tbody></table></div>}</section>
    </>
  );
}

function label(value: string) {
  return value.toLowerCase().replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}
