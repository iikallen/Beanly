"use client";

import { Plus } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { useFinancePermissions } from "@/hooks/use-finance-permissions";
import { api, type Expense, type ExpenseCategory } from "@/lib/api";
import { formatFinanceDate, formatFinanceMinor } from "@/lib/finance";

export default function ExpensesPage() {
  const { accessToken } = useAuth();
  const { currentOrganization, locations } = useWorkspace();
  const { canRead, canWrite, loading: permissionsLoading } = useFinancePermissions();
  const [expenses, setExpenses] = useState<Expense[]>([]);
  const [categories, setCategories] = useState<ExpenseCategory[]>([]);
  const [status, setStatus] = useState("");
  const [locationId, setLocationId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      await Promise.resolve();
      if (cancelled || !accessToken || !currentOrganization || permissionsLoading || !canRead) return;
      setLoading(true);
      try {
        const [nextExpenses, nextCategories] = await Promise.all([
          api.listExpenses(currentOrganization.id, accessToken),
          api.listExpenseCategories(currentOrganization.id, accessToken),
        ]);
        if (!cancelled) { setExpenses(nextExpenses); setCategories(nextCategories); }
      } catch (caught) {
        if (!cancelled) setError(caught instanceof Error ? caught.message : "Unable to load expenses");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => { cancelled = true; };
  }, [accessToken, canRead, currentOrganization, permissionsLoading]);

  const categoryNames = useMemo(() => new Map(categories.map((item) => [item.id, item.name])), [categories]);
  const locationNames = useMemo(() => new Map(locations.map((item) => [item.id, item.name])), [locations]);
  const visible = expenses.filter((expense) =>
    (!status || expense.status === status) &&
    (!locationId || (locationId === "unallocated" ? !expense.location_id : expense.location_id === locationId)),
  );

  return (
    <>
      <header className="finance-header">
        <div><h1>Expenses</h1><p>Operating costs that affect management P&amp;L.</p></div>
        {canWrite && <Link className="purchasing-primary" href="/app/finance/expenses/new"><Plus aria-hidden="true" /> Add expense</Link>}
      </header>
      <div className="finance-header-actions finance-list-filters">
        <label className="finance-filter"><span>Location</span><select value={locationId} onChange={(event) => setLocationId(event.target.value)}><option value="">All locations</option><option value="unallocated">Central / Unallocated</option>{locations.map((location) => <option key={location.id} value={location.id}>{location.name}</option>)}</select></label>
        <label className="finance-filter"><span>Status</span><select value={status} onChange={(event) => setStatus(event.target.value)}><option value="">All statuses</option><option value="DRAFT">Draft</option><option value="POSTED">Posted</option><option value="REVERSED">Reversed</option></select></label>
      </div>
      {!permissionsLoading && !canRead ? (
        <div className="finance-state"><strong>Finance access required</strong><span>Your role cannot view expenses.</span></div>
      ) : error ? (
        <div className="finance-state is-error" role="alert"><strong>Expenses could not be loaded.</strong><span>{error}</span></div>
      ) : loading ? (
        <div className="finance-state" aria-live="polite">Loading expenses…</div>
      ) : visible.length === 0 ? (
        <div className="finance-state"><strong>No expenses found</strong><span>Posted costs and saved drafts will appear here.</span></div>
      ) : (
        <div className="finance-table-wrap" tabIndex={0} aria-label="Expenses table">
          <table className="finance-table"><thead><tr><th>Date</th><th>Number</th><th>Category</th><th>Vendor</th><th>Location</th><th>Amount</th><th>Status</th></tr></thead>
            <tbody>{visible.map((expense) => <tr key={expense.id}>
              <td>{formatFinanceDate(expense.occurred_at)}</td>
              <td><Link href={`/app/finance/expenses/${expense.id}`}>{expense.number}</Link></td>
              <td>{categoryNames.get(expense.category_id) ?? "Expense"}</td>
              <td>{expense.vendor ?? "—"}</td>
              <td>{expense.location_id ? locationNames.get(expense.location_id) ?? "Location" : "Central / Unallocated"}</td>
              <td>{formatFinanceMinor(expense.amount_minor, expense.currency_code)}</td>
              <td><span className={`finance-status status-${expense.status.toLowerCase()}`}>{expense.status.toLowerCase()}</span></td>
            </tr>)}</tbody>
          </table>
        </div>
      )}
    </>
  );
}
