"use client";

import { ArrowLeft, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { useFinancePermissions } from "@/hooks/use-finance-permissions";
import { api, type CashAccount, type ExpenseCategory } from "@/lib/api";
import { localDateTimeNow, toApiDate } from "@/lib/inventory-operations";
import { toMinorUnits } from "@/lib/finance";

export default function NewExpensePage() {
  const { accessToken } = useAuth();
  const { currentOrganization, currentLocation, locations } = useWorkspace();
  const { canWrite, loading: permissionsLoading } = useFinancePermissions();
  const router = useRouter();
  const [categories, setCategories] = useState<ExpenseCategory[]>([]);
  const [accounts, setAccounts] = useState<CashAccount[]>([]);
  const [categoryId, setCategoryId] = useState("");
  const [locationId, setLocationId] = useState(currentLocation?.id ?? "");
  const [amount, setAmount] = useState("");
  const [cashAccountId, setCashAccountId] = useState("");
  const [occurredAt, setOccurredAt] = useState(localDateTimeNow);
  const [vendor, setVendor] = useState("");
  const [description, setDescription] = useState("");
  const [newCategory, setNewCategory] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    if (!accessToken || !currentOrganization || permissionsLoading || !canWrite) return;
    Promise.all([
      api.listExpenseCategories(currentOrganization.id, accessToken),
      api.listCashAccounts(currentOrganization.id, accessToken),
    ]).then(([nextCategories, nextAccounts]) => {
      if (cancelled) return;
      const activeCategories = nextCategories.filter((item) => item.is_active);
      setCategories(activeCategories);
      setAccounts(nextAccounts.filter((item) => item.is_active));
      setCategoryId(activeCategories[0]?.id ?? "");
    }).catch((caught) => {
      if (!cancelled) setError(caught instanceof Error ? caught.message : "Unable to prepare expense");
    }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [accessToken, canWrite, currentOrganization, permissionsLoading]);

  async function addCategory() {
    if (!accessToken || !currentOrganization || !newCategory.trim()) return;
    setSaving(true);
    setError("");
    try {
      const created = await api.createExpenseCategory({ name: newCategory.trim() }, currentOrganization.id, accessToken);
      setCategories((current) => [...current, created]);
      setCategoryId(created.id);
      setNewCategory("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to create category");
    } finally {
      setSaving(false);
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const action = (event.nativeEvent as SubmitEvent).submitter?.getAttribute("data-action");
    const amountMinor = toMinorUnits(amount);
    if (!accessToken || !currentOrganization || !amountMinor || BigInt(amountMinor) <= BigInt(0)) {
      setError("Enter a positive amount with no more than two decimal places.");
      return;
    }
    if (!categoryId) { setError("Choose or create an expense category."); return; }
    setSaving(true);
    setError("");
    try {
      const created = await api.createExpense({
        location_id: locationId || null,
        category_id: categoryId,
        amount_minor: amountMinor,
        cash_account_id: cashAccountId || null,
        vendor: vendor.trim() || null,
        occurred_at: toApiDate(occurredAt),
        description: description.trim() || null,
      }, currentOrganization.id, accessToken);
      if (action === "post") {
        try {
          await api.postExpense(created.id, currentOrganization.id, accessToken);
        } catch {
          router.push(`/app/finance/expenses/${created.id}?postFailed=1`);
          return;
        }
      }
      router.push(`/app/finance/expenses/${created.id}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to save expense");
      setSaving(false);
    }
  }

  if (!permissionsLoading && !canWrite) return <div className="finance-state"><strong>Finance write access required</strong><span>Your role cannot create expenses.</span></div>;
  if (permissionsLoading || loading) return <div className="finance-state" aria-live="polite">Preparing expense…</div>;

  const availableAccounts = accounts.filter((account) => !locationId || account.location_id === null || account.location_id === locationId);

  return (
    <>
      <Link className="purchasing-back" href="/app/finance/expenses"><ArrowLeft aria-hidden="true" /> Expenses</Link>
      <header className="finance-header"><div><h1>New expense</h1><p>Record a management expense, optionally paid from a cash account.</p></div></header>
      <section className="finance-panel">
        <form className="finance-form" onSubmit={submit}>
          <div className="finance-form-grid">
            <label><span>Category</span><select value={categoryId} onChange={(event) => setCategoryId(event.target.value)} required><option value="">Select category</option>{categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}</select></label>
            <label><span>Location</span><select value={locationId} onChange={(event) => { const next = event.target.value; setLocationId(next); const selected = accounts.find((account) => account.id === cashAccountId); if (next && selected?.location_id && selected.location_id !== next) setCashAccountId(""); }}><option value="">Central / Unallocated</option>{locations.map((location) => <option key={location.id} value={location.id}>{location.name}</option>)}</select></label>
            <label><span>Amount ({currentOrganization?.currency_code ?? "KZT"})</span><input inputMode="decimal" value={amount} onChange={(event) => setAmount(event.target.value)} placeholder="500000" required /></label>
            <label><span>Paid from</span><select value={cashAccountId} onChange={(event) => setCashAccountId(event.target.value)}><option value="">Not paid / no cash entry</option>{availableAccounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}</select></label>
            <label><span>Date</span><input type="datetime-local" value={occurredAt} onChange={(event) => setOccurredAt(event.target.value)} required /></label>
            <label><span>Vendor</span><input value={vendor} onChange={(event) => setVendor(event.target.value)} placeholder="Optional" /></label>
            <label className="is-wide"><span>Note</span><textarea value={description} onChange={(event) => setDescription(event.target.value)} placeholder="What was this expense for?" /></label>
          </div>
          <div className="operation-inline-create">
            <label><span>New category</span><input value={newCategory} onChange={(event) => setNewCategory(event.target.value)} placeholder="e.g. Repairs" /></label>
            <button type="button" onClick={addCategory} disabled={saving || !newCategory.trim()}><Plus aria-hidden="true" /> Add category</button>
          </div>
          {error && <div className="finance-inline-error" role="alert">{error}</div>}
          <div className="finance-form-actions"><button className="secondary-button" type="submit" data-action="draft" disabled={saving}>Save draft</button><button className="purchasing-primary" type="submit" data-action="post" disabled={saving}>{saving ? "Saving…" : "Post expense"}</button></div>
        </form>
      </section>
    </>
  );
}
