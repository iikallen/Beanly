"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { usePurchasingPermissions } from "@/hooks/use-purchasing-permissions";
import {
  ApiError,
  api,
  type GoodsReceipt,
  type InventoryItemResponse,
  type Supplier,
  type WarehouseResponse,
} from "@/lib/api";
import {
  formatMoneyAmount,
  formatMoneyMinor,
  formatPurchaseDate,
  formatPurchaseStatus,
  formatPurchaseUnit,
  statusClass,
} from "@/lib/purchasing";

export default function GoodsReceiptDetailPage() {
  const { receiptId } = useParams<{ receiptId: string }>();
  const { accessToken } = useAuth();
  const { currentOrganization } = useWorkspace();
  const { canReceive } = usePurchasingPermissions();
  const [receipt, setReceipt] = useState<GoodsReceipt | null>(null);
  const [supplier, setSupplier] = useState<Supplier | null>(null);
  const [warehouse, setWarehouse] = useState<WarehouseResponse | null>(null);
  const [items, setItems] = useState<InventoryItemResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!accessToken || !currentOrganization) return;
    setLoading(true);
    setError("");
    try {
      const nextReceipt = await api.getGoodsReceipt(receiptId, currentOrganization.id, accessToken);
      const [nextSupplier, warehouses, nextItems] = await Promise.all([
        api.getSupplier(nextReceipt.supplier_id, currentOrganization.id, accessToken),
        api.listInventoryWarehouses(currentOrganization.id, accessToken),
        api.listInventoryItems(currentOrganization.id, accessToken),
      ]);
      setReceipt(nextReceipt);
      setSupplier(nextSupplier);
      setWarehouse(warehouses.find((item) => item.id === nextReceipt.warehouse_id) ?? null);
      setItems(nextItems);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to load goods receipt");
    } finally {
      setLoading(false);
    }
  }, [accessToken, currentOrganization, receiptId]);

  useEffect(() => { void Promise.resolve().then(load); }, [load]);

  const itemNames = useMemo(
    () => new Map(items.map((item) => [item.id, item.name])),
    [items],
  );

  async function postReceipt(confirmOverReceipt = false) {
    if (!accessToken || !currentOrganization || !receipt) return;
    setWorking(true);
    setError("");
    try {
      await api.postGoodsReceipt(receipt.id, confirmOverReceipt, currentOrganization.id, accessToken);
      await load();
    } catch (caught) {
      if (
        caught instanceof ApiError &&
        caught.status === 409 &&
        caught.code === "RECEIVED_QUANTITY_EXCEEDS_ORDER" &&
        window.confirm("The received quantity exceeds the order. Post the actual delivery anyway?")
      ) {
        await postReceipt(true);
        return;
      }
      setError(caught instanceof Error ? caught.message : "Unable to post goods receipt");
    } finally {
      setWorking(false);
    }
  }

  async function reverseReceipt() {
    if (!accessToken || !currentOrganization || !receipt) return;
    if (!window.confirm("Reverse this receipt and remove its quantities from inventory?")) return;
    setWorking(true);
    setError("");
    try {
      await api.reverseGoodsReceipt(receipt.id, currentOrganization.id, accessToken);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to reverse goods receipt");
    } finally {
      setWorking(false);
    }
  }

  if (loading) return <div className="purchasing-state">Loading goods receipt…</div>;
  if (error && !receipt) return <div className="purchasing-state is-error" role="alert"><strong>Goods receipt could not be loaded.</strong><span>{error}</span><Link href="/app/purchasing/receipts">Back to goods receipts</Link></div>;
  if (!receipt) return null;
  const currency = currentOrganization?.currency_code ?? "KZT";

  return (
    <>
      <Link className="purchasing-back" href="/app/purchasing/receipts"><ArrowLeft aria-hidden="true" />Goods receipts</Link>
      <header className="purchasing-header order-detail-header">
        <div><h1>{receipt.number}</h1><p>{supplier?.name ?? receipt.supplier_name ?? "Supplier"}</p></div>
        {canReceive && <div className="purchase-header-actions">{receipt.status === "DRAFT" && <button className="purchasing-primary" type="button" disabled={working} onClick={() => void postReceipt()}>{working ? "Posting…" : "Post receipt"}</button>}{receipt.status === "POSTED" && <button className="secondary-button is-danger" type="button" disabled={working} onClick={() => void reverseReceipt()}>{working ? "Reversing…" : "Reverse receipt"}</button>}</div>}
      </header>
      <dl className="purchase-document-meta">
        <div><dt>Status</dt><dd><span className={statusClass(receipt.status)}>{formatPurchaseStatus(receipt.status)}</span></dd></div>
        <div><dt>Received</dt><dd>{formatPurchaseDate(receipt.received_at)}</dd></div>
        <div><dt>Source</dt><dd>{receipt.purchase_order_id ? <Link href={`/app/purchasing/orders/${receipt.purchase_order_id}`}>{receipt.purchase_order_number ?? "Purchase order"}</Link> : "Quick receive"}</dd></div>
        <div><dt>Warehouse</dt><dd>{warehouse?.name ?? receipt.warehouse_name ?? "—"}</dd></div>
        {receipt.document_number && <div><dt>Supplier document</dt><dd>{receipt.document_number}</dd></div>}
      </dl>
      {error && <div className="purchase-inline-alert is-error" role="alert">{error}</div>}
      <div className="purchasing-table-wrap" tabIndex={0} aria-label="Goods receipt lines">
        <table className="purchasing-table receipt-lines-table">
          <caption className="sr-only">Items in {receipt.number}</caption>
          <thead><tr><th scope="col">Item</th><th scope="col">Received quantity</th><th scope="col">Base quantity</th><th scope="col">Actual price</th><th scope="col">Total</th></tr></thead>
          <tbody>{(receipt.lines ?? []).map((line) => <tr key={line.id}><td><strong>{itemNames.get(line.inventory_item_id) ?? "Inventory item"}</strong></td><td>{line.received_quantity} {formatPurchaseUnit(line.purchase_unit)}</td><td>{line.base_quantity} base units</td><td>{formatMoneyAmount(line.unit_price, currency)} / {formatPurchaseUnit(line.purchase_unit)}</td><td>{formatMoneyMinor(line.line_total_minor, currency)}</td></tr>)}</tbody>
          <tfoot><tr><th colSpan={4} scope="row">Total</th><td>{formatMoneyMinor(receipt.total_minor ?? (receipt.lines ?? []).reduce((total, line) => total + Number(line.line_total_minor), 0), currency)}</td></tr></tfoot>
        </table>
      </div>
      {receipt.note && <p className="purchase-document-note"><strong>Note</strong>{receipt.note}</p>}
      {receipt.status !== "DRAFT" && <p className="purchase-readonly-note">Posted receipts are immutable. Reverse this receipt to correct an inventory mistake.</p>}
    </>
  );
}
