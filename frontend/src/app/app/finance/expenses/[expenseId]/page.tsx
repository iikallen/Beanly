"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { useFinancePermissions } from "@/hooks/use-finance-permissions";
import { api, type CashAccount, type Expense, type ExpenseCategory } from "@/lib/api";
import { formatFinanceDate, formatFinanceMinor } from "@/lib/finance";

export default function ExpenseDetailPage() {
  const { expenseId } = useParams<{ expenseId: string }>();
  const { accessToken } = useAuth();
  const { currentOrganization, locations } = useWorkspace();
  const { canRead, canWrite, loading: permissionsLoading } = useFinancePermissions();
  const [expense, setExpense] = useState<Expense | null>(null);
  const [categories, setCategories] = useState<ExpenseCategory[]>([]);
  const [accounts, setAccounts] = useState<CashAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [postFailed, setPostFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(() => {
      if (!cancelled) setPostFailed(new URLSearchParams(window.location.search).get("postFailed") === "1");
    });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    if (!accessToken || !currentOrganization || permissionsLoading || !canRead) return;
    Promise.all([
      api.getExpense(expenseId, currentOrganization.id, accessToken),
      api.listExpenseCategories(currentOrganization.id, accessToken),
      api.listCashAccounts(currentOrganization.id, accessToken),
    ]).then(([nextExpense, nextCategories, nextAccounts]) => {
      if (!cancelled) { setExpense(nextExpense); setCategories(nextCategories); setAccounts(nextAccounts); }
    }).catch((caught) => {
      if (!cancelled) setError(caught instanceof Error ? caught.message : "Unable to load expense");
    }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [accessToken, canRead, currentOrganization, expenseId, permissionsLoading]);

  const categoryNames = useMemo(() => new Map(categories.map((item) => [item.id, item.name])), [categories]);
  const accountNames = useMemo(() => new Map(accounts.map((item) => [item.id, item.name])), [accounts]);
  const locationNames = useMemo(() => new Map(locations.map((item) => [item.id, item.name])), [locations]);

  async function changeStatus(action: "post" | "reverse") {
    if (!accessToken || !currentOrganization || !expense) return;
    if (action === "reverse" && !window.confirm("Reverse this posted expense? Ledger records will remain in the audit trail.")) return;
    setSaving(true);
    setError("");
    try {
      const next = action === "post"
        ? await api.postExpense(expense.id, currentOrganization.id, accessToken)
        : await api.reverseExpense(expense.id, currentOrganization.id, accessToken);
      setExpense(next);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : `Unable to ${action} expense`);
    } finally {
      setSaving(false);
    }
  }

  if (!permissionsLoading && !canRead) return <div className="finance-state"><strong>Finance access required</strong><span>Your role cannot view expenses.</span></div>;
  if (permissionsLoading || loading) return <div className="finance-state" aria-live="polite">Loading expense…</div>;
  if (error && !expense) return <div className="finance-state is-error" role="alert"><strong>Expense could not be loaded.</strong><span>{error}</span></div>;
  if (!expense) return <div className="finance-state"><strong>Expense not found</strong></div>;

  return (
    <>
      <Link className="purchasing-back" href="/app/finance/expenses"><ArrowLeft aria-hidden="true" /> Expenses</Link>
      <header className="finance-header">
        <div><h1>{expense.number}</h1><p>{categoryNames.get(expense.category_id) ?? "Expense"} · {formatFinanceDate(expense.occurred_at)}</p></div>
        {canWrite && <div className="finance-header-actions">
          {expense.status === "DRAFT" && <button className="purchasing-primary" type="button" onClick={() => changeStatus("post")} disabled={saving}>{saving ? "Posting…" : "Post expense"}</button>}
          {expense.status === "POSTED" && <button className="secondary-button is-danger" type="button" onClick={() => changeStatus("reverse")} disabled={saving}>{saving ? "Reversing…" : "Reverse"}</button>}
        </div>}
      </header>
      {postFailed && expense.status === "DRAFT" && <div className="finance-quality-warning" role="status"><div><strong>Draft saved.</strong><p>Posting did not complete. Review the expense and try Post expense again.</p></div></div>}
      {error && <div className="finance-inline-error" role="alert">{error}</div>}
      <dl className="operation-summary">
        <div><dt>Status</dt><dd><span className={`finance-status status-${expense.status.toLowerCase()}`}>{expense.status.toLowerCase()}</span></dd></div>
        <div><dt>Amount</dt><dd>{formatFinanceMinor(expense.amount_minor, expense.currency_code)}</dd></div>
        <div><dt>Location</dt><dd>{expense.location_id ? locationNames.get(expense.location_id) ?? "Location" : "Central / Unallocated"}</dd></div>
        <div><dt>Paid from</dt><dd>{expense.cash_account_id ? accountNames.get(expense.cash_account_id) ?? "Cash account" : "Not recorded"}</dd></div>
        <div><dt>Vendor</dt><dd>{expense.vendor ?? "—"}</dd></div>
        <div><dt>Posted</dt><dd>{expense.posted_at ? formatFinanceDate(expense.posted_at) : "—"}</dd></div>
      </dl>
      <section className="finance-panel"><h2>Note</h2><p>{expense.description || "No note."}</p></section>
    </>
  );
}
