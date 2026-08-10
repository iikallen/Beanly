"use client";

import { ChevronRight, Plus } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { usePurchasingPermissions } from "@/hooks/use-purchasing-permissions";
import { api, type Supplier, type SupplierReturn } from "@/lib/api";
import { formatMoneyMinor, formatPurchaseDate, formatPurchaseStatus, statusClass } from "@/lib/purchasing";

export default function SupplierReturnsPage() {
  const { accessToken } = useAuth();
  const { currentOrganization, currentLocation } = useWorkspace();
  const { canRead, canReturn, loading: permissionsLoading } = usePurchasingPermissions();
  const [rows, setRows] = useState<SupplierReturn[]>([]);
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [supplierId, setSupplierId] = useState("");
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    let cancelled = false;
    if (!accessToken || !currentOrganization || !currentLocation || permissionsLoading) return;
    if (!canRead) return;
    Promise.all([api.listSupplierReturns(currentOrganization.id, accessToken, { supplierId: supplierId || undefined, locationId: currentLocation.id, status: status || undefined }), api.listSuppliers(currentOrganization.id, accessToken, true)])
      .then(([nextRows, nextSuppliers]) => { if (!cancelled) { setRows(nextRows.filter((row) => row.location_id === currentLocation.id)); setSuppliers(nextSuppliers); } })
      .catch((caught) => { if (!cancelled) setError(caught instanceof Error ? caught.message : "Unable to load supplier returns"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [accessToken, canRead, currentLocation, currentOrganization, permissionsLoading, status, supplierId]);
  const names = useMemo(() => new Map(suppliers.map((supplier) => [supplier.id, supplier.name])), [suppliers]);
  return <>
    <header className="purchasing-header"><div><h1>Supplier Returns</h1><p>Return damaged or incorrect goods to suppliers.</p></div>{canReturn && <Link className="purchasing-primary" href="/app/purchasing/returns/new"><Plus aria-hidden="true" /> New return</Link>}</header>
    <div className="purchasing-filters"><label><span className="sr-only">Supplier</span><select value={supplierId} onChange={(event) => setSupplierId(event.target.value)}><option value="">Supplier</option>{suppliers.map((supplier) => <option key={supplier.id} value={supplier.id}>{supplier.name}</option>)}</select></label><label><span className="sr-only">Status</span><select value={status} onChange={(event) => setStatus(event.target.value)}><option value="">Status</option><option value="DRAFT">Draft</option><option value="POSTED">Posted</option><option value="REVERSED">Reversed</option></select></label></div>
    {!permissionsLoading && !canRead ? <div className="purchasing-state"><strong>Purchasing access required</strong><span>Your role cannot view supplier returns.</span></div> : error ? <div className="purchasing-state is-error" role="alert"><strong>Supplier returns could not be loaded.</strong><span>{error}</span></div> : loading ? <div className="purchasing-state" aria-live="polite">Loading supplier returns…</div> : rows.length === 0 ? <div className="purchasing-state"><strong>No supplier returns found</strong><span>Create a return from a posted goods receipt.</span></div> : <div className="purchasing-table-wrap" tabIndex={0} aria-label="Supplier returns table"><table className="purchasing-table"><thead><tr><th>Number</th><th>Supplier</th><th>Receipt</th><th>Total</th><th>Status</th><th>Returned</th><th><span className="sr-only">Open</span></th></tr></thead><tbody>{rows.map((row) => <tr key={row.id}><td><Link href={`/app/purchasing/returns/${row.id}`}>{row.number}</Link></td><td>{row.supplier_name ?? names.get(row.supplier_id) ?? "Supplier"}</td><td>{row.goods_receipt_number ?? "—"}</td><td>{formatMoneyMinor(row.total_minor, currentOrganization?.currency_code ?? "KZT")}</td><td><span className={statusClass(row.status)}>{formatPurchaseStatus(row.status)}</span></td><td>{formatPurchaseDate(row.returned_at)}</td><td><Link className="purchasing-row-link" href={`/app/purchasing/returns/${row.id}`} aria-label={`Open ${row.number}`}><ChevronRight aria-hidden="true" /></Link></td></tr>)}</tbody></table></div>}
  </>;
}
