"use client";

import { Plus } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { useFinancePermissions } from "@/hooks/use-finance-permissions";
import { api, type CashAccount, type CashAccountType } from "@/lib/api";
import { formatFinanceMinor, toSignedMinorUnits } from "@/lib/finance";

const accountTypes: CashAccountType[] = ["CASH", "BANK", "CARD_CLEARING", "OTHER"];

export default function AccountsPage() {
  const { accessToken } = useAuth();
  const { currentOrganization, locations } = useWorkspace();
  const { canRead, canWrite, loading: permissionsLoading } = useFinancePermissions();
  const [accounts, setAccounts] = useState<CashAccount[]>([]);
  const [name, setName] = useState("");
  const [type, setType] = useState<CashAccountType>("BANK");
  const [locationId, setLocationId] = useState("");
  const [openingBalance, setOpeningBalance] = useState("0");
  const [showForm, setShowForm] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      await Promise.resolve();
      if (cancelled || !accessToken || !currentOrganization || permissionsLoading || !canRead) return;
      setLoading(true);
      try {
        const next = await api.listCashAccounts(currentOrganization.id, accessToken);
        if (!cancelled) setAccounts(next);
      } catch (caught) {
        if (!cancelled) setError(caught instanceof Error ? caught.message : "Unable to load accounts");
      } finally { if (!cancelled) setLoading(false); }
    }
    void load();
    return () => { cancelled = true; };
  }, [accessToken, canRead, currentOrganization, permissionsLoading]);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const openingMinor = toSignedMinorUnits(openingBalance);
    if (!accessToken || !currentOrganization || !name.trim() || openingMinor === null) {
      setError("Enter an account name and a valid opening balance.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const created = await api.createCashAccount({ name: name.trim(), type, location_id: locationId || null, opening_balance_minor: openingMinor }, currentOrganization.id, accessToken);
      setAccounts((current) => [...current, created]);
      setName(""); setOpeningBalance("0"); setLocationId(""); setShowForm(false);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to create account"); }
    finally { setSaving(false); }
  }

  async function deactivate(account: CashAccount) {
    if (!accessToken || !currentOrganization || account.system_key || !window.confirm(`Deactivate ${account.name}?`)) return;
    setSaving(true);
    setError("");
    try {
      const updated = await api.deactivateCashAccount(account.id, currentOrganization.id, accessToken);
      setAccounts((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to deactivate account"); }
    finally { setSaving(false); }
  }

  return (
    <>
      <header className="finance-header">
        <div><h1>Cash Accounts</h1><p>Balances are derived from the immutable cash ledger.</p></div>
        {canWrite && <button className="purchasing-primary" type="button" onClick={() => setShowForm((value) => !value)}><Plus aria-hidden="true" /> New account</button>}
      </header>
      {showForm && canWrite && <section className="finance-panel"><h2>New cash account</h2><form className="finance-form" onSubmit={create}><div className="finance-form-grid">
        <label><span>Name</span><input value={name} onChange={(event) => setName(event.target.value)} placeholder="Bank" required /></label>
        <label><span>Type</span><select value={type} onChange={(event) => setType(event.target.value as CashAccountType)}>{accountTypes.map((value) => <option key={value} value={value}>{label(value)}</option>)}</select></label>
        <label><span>Location</span><select value={locationId} onChange={(event) => setLocationId(event.target.value)}><option value="">Organization-wide</option>{locations.map((location) => <option key={location.id} value={location.id}>{location.name}</option>)}</select></label>
        <label><span>Opening balance ({currentOrganization?.currency_code ?? "KZT"})</span><input inputMode="decimal" value={openingBalance} onChange={(event) => setOpeningBalance(event.target.value)} required /></label>
      </div>{error && <div className="finance-inline-error" role="alert">{error}</div>}<div className="finance-form-actions"><button className="secondary-button" type="button" onClick={() => setShowForm(false)}>Cancel</button><button className="purchasing-primary" type="submit" disabled={saving}>{saving ? "Creating…" : "Create account"}</button></div></form></section>}
      {!showForm && error && <div className="finance-inline-error" role="alert">{error}</div>}
      {!permissionsLoading && !canRead ? (
        <div className="finance-state"><strong>Finance access required</strong><span>Your role cannot view cash accounts.</span></div>
      ) : loading ? (
        <div className="finance-state" aria-live="polite">Loading accounts…</div>
      ) : accounts.length === 0 ? (
        <div className="finance-state"><strong>No cash accounts yet</strong><span>Payment accounts appear automatically after the first completed payment.</span></div>
      ) : (
        <div className="finance-account-grid">{accounts.map((account) => <article className={`finance-account-card${account.is_active ? "" : " is-inactive"}`} key={account.id}><header><div><h2>{account.name}</h2><p>{label(account.type)} · {account.location_id ? locations.find((item) => item.id === account.location_id)?.name ?? "Location" : "Organization-wide"}</p></div>{account.system_key && <span className="finance-status status-posted">System</span>}</header><strong>{formatFinanceMinor(account.balance_minor, account.currency_code)}</strong>{canWrite && account.is_active && !account.system_key && <button className="secondary-button is-danger" type="button" onClick={() => deactivate(account)} disabled={saving}>Deactivate</button>}</article>)}</div>
      )}
    </>
  );
}

function label(value: string) {
  return value.toLowerCase().replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}
