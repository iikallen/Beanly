"use client";

import { ChevronRight, Plus } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { usePurchasingPermissions } from "@/hooks/use-purchasing-permissions";
import { api, type GoodsReceipt, type GoodsReceiptStatus, type Supplier } from "@/lib/api";
import {
  formatMoneyMinor,
  formatPurchaseDate,
  formatPurchaseStatus,
  statusClass,
} from "@/lib/purchasing";

export default function GoodsReceiptsPage() {
  const { accessToken } = useAuth();
  const { currentOrganization, currentLocation } = useWorkspace();
  const { canReceive } = usePurchasingPermissions();
  const [receipts, setReceipts] = useState<GoodsReceipt[]>([]);
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [supplierId, setSupplierId] = useState("");
  const [status, setStatus] = useState<GoodsReceiptStatus | "">("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    if (!accessToken || !currentOrganization || !currentLocation) return;
    Promise.resolve().then(() => {
      if (cancelled) return [[], []] as [GoodsReceipt[], Supplier[]];
      setLoading(true);
      setError("");
      return Promise.all([
        api.listGoodsReceipts(currentOrganization.id, accessToken, {
          supplierId: supplierId || undefined,
          status,
        }),
        api.listSuppliers(currentOrganization.id, accessToken, true),
      ]);
    })
      .then(([nextReceipts, nextSuppliers]) => {
        if (cancelled) return;
        setReceipts(nextReceipts.filter((receipt) => receipt.location_id === currentLocation.id));
        setSuppliers(nextSuppliers);
      })
      .catch((caught) => {
        if (!cancelled) setError(caught instanceof Error ? caught.message : "Unable to load goods receipts");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [accessToken, currentLocation, currentOrganization, status, supplierId]);

  const supplierNames = useMemo(
    () => new Map(suppliers.map((supplier) => [supplier.id, supplier.name])),
    [suppliers],
  );

  return (
    <>
      <header className="purchasing-header">
        <div><h1>Goods Receipts</h1><p>Review delivered goods and stock postings.</p></div>
        {canReceive && <Link className="purchasing-primary" href="/app/purchasing/receipts/new"><Plus aria-hidden="true" />Quick receive</Link>}
      </header>
      <div className="purchasing-filters">
        <label><span className="sr-only">Supplier</span><select value={supplierId} onChange={(event) => setSupplierId(event.target.value)}><option value="">Supplier</option>{suppliers.map((supplier) => <option key={supplier.id} value={supplier.id}>{supplier.name}</option>)}</select></label>
        <label><span className="sr-only">Status</span><select value={status} onChange={(event) => setStatus(event.target.value as GoodsReceiptStatus | "")}><option value="">Status</option><option value="DRAFT">Draft</option><option value="POSTED">Posted</option><option value="REVERSED">Reversed</option></select></label>
      </div>
      {error ? (
        <div className="purchasing-state is-error" role="alert"><strong>Goods receipts could not be loaded.</strong><span>{error}</span></div>
      ) : loading ? (
        <div className="purchasing-state" aria-live="polite">Loading goods receipts…</div>
      ) : receipts.length === 0 ? (
        <div className="purchasing-state"><strong>No goods receipts found</strong><span>Receive a purchase order or record a quick delivery.</span></div>
      ) : (
        <div className="purchasing-table-wrap" tabIndex={0} aria-label="Goods receipts table">
          <table className="purchasing-table receipts-table">
            <caption className="sr-only">Goods receipts for the selected location</caption>
            <thead><tr><th scope="col">Number</th><th scope="col">Supplier</th><th scope="col">Source</th><th scope="col">Total</th><th scope="col">Status</th><th scope="col">Received</th><th scope="col"><span className="sr-only">Open</span></th></tr></thead>
            <tbody>{receipts.map((receipt) => (
              <tr key={receipt.id}>
                <td><Link href={`/app/purchasing/receipts/${receipt.id}`}>{receipt.number}</Link></td>
                <td>{receipt.supplier_name ?? supplierNames.get(receipt.supplier_id) ?? "Unknown supplier"}</td>
                <td>{receipt.purchase_order_number ?? (receipt.purchase_order_id ? "Purchase order" : "Quick receive")}</td>
                <td>{formatMoneyMinor(receipt.total_minor, currentOrganization?.currency_code ?? "KZT")}</td>
                <td><span className={statusClass(receipt.status)}>{formatPurchaseStatus(receipt.status)}</span></td>
                <td>{formatPurchaseDate(receipt.received_at)}</td>
                <td><Link className="purchasing-row-link" href={`/app/purchasing/receipts/${receipt.id}`} aria-label={`Open ${receipt.number}`}><ChevronRight aria-hidden="true" /></Link></td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
    </>
  );
}
