"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { usePurchasingPermissions } from "@/hooks/use-purchasing-permissions";
import {
  api,
  type GoodsReceipt,
  type InventoryItemResponse,
  type PurchaseOrder,
  type Supplier,
  type WarehouseResponse,
} from "@/lib/api";
import {
  formatMoneyAmount,
  formatMoneyMinor,
  formatPurchaseDate,
  formatPurchaseStatus,
  formatPurchaseUnit,
  orderTotalMinor,
  statusClass,
} from "@/lib/purchasing";

export default function PurchaseOrderDetailPage() {
  const { orderId } = useParams<{ orderId: string }>();
  const { accessToken } = useAuth();
  const { currentOrganization } = useWorkspace();
  const { canCancel, canReceive, canUpdate } = usePurchasingPermissions();
  const router = useRouter();
  const [order, setOrder] = useState<PurchaseOrder | null>(null);
  const [supplier, setSupplier] = useState<Supplier | null>(null);
  const [warehouse, setWarehouse] = useState<WarehouseResponse | null>(null);
  const [items, setItems] = useState<InventoryItemResponse[]>([]);
  const [receipts, setReceipts] = useState<GoodsReceipt[]>([]);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!accessToken || !currentOrganization) return;
    setLoading(true);
    setError("");
    try {
      const nextOrder = await api.getPurchaseOrder(orderId, currentOrganization.id, accessToken);
      const [nextSupplier, warehouses, nextItems, nextReceipts] = await Promise.all([
        api.getSupplier(nextOrder.supplier_id, currentOrganization.id, accessToken),
        api.listInventoryWarehouses(currentOrganization.id, accessToken),
        api.listInventoryItems(currentOrganization.id, accessToken),
        api.listGoodsReceipts(currentOrganization.id, accessToken, { purchaseOrderId: orderId }),
      ]);
      setOrder(nextOrder);
      setSupplier(nextSupplier);
      setWarehouse(warehouses.find((item) => item.id === nextOrder.warehouse_id) ?? null);
      setItems(nextItems);
      setReceipts(nextReceipts);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to load purchase order");
    } finally {
      setLoading(false);
    }
  }, [accessToken, currentOrganization, orderId]);

  useEffect(() => { void Promise.resolve().then(load); }, [load]);

  const itemNames = useMemo(
    () => new Map(items.map((item) => [item.id, item.name])),
    [items],
  );

  async function transition(action: "submit" | "cancel") {
    if (!accessToken || !currentOrganization || !order) return;
    setWorking(true);
    setError("");
    try {
      if (action === "submit") {
        await api.submitPurchaseOrder(order.id, currentOrganization.id, accessToken);
      } else {
        await api.cancelPurchaseOrder(order.id, currentOrganization.id, accessToken);
      }
      await load();
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : `Unable to ${action} order`);
    } finally {
      setWorking(false);
    }
  }

  if (loading) return <div className="purchasing-state">Loading purchase order…</div>;
  if (error && !order) {
    return <div className="purchasing-state is-error" role="alert"><strong>Purchase order could not be loaded.</strong><span>{error}</span><Link href="/app/purchasing/orders">Back to purchase orders</Link></div>;
  }
  if (!order) return null;

  return (
    <>
      <Link className="purchasing-back" href="/app/purchasing/orders">
        <ArrowLeft aria-hidden="true" />
        Purchase orders
      </Link>
      <header className="purchasing-header order-detail-header">
        <div>
          <h1>{order.number}</h1>
          <p>{supplier?.name ?? order.supplier_name ?? "Supplier"}</p>
        </div>
        <div className="purchase-header-actions">
          {order.status === "DRAFT" && canCancel && (
            <button className="secondary-button is-danger" type="button" disabled={working} onClick={() => void transition("cancel")}>Cancel order</button>
          )}
          {order.status === "DRAFT" && canUpdate && (
            <button className="purchasing-primary" type="button" disabled={working} onClick={() => void transition("submit")}>{working ? "Submitting…" : "Submit order"}</button>
          )}
          {(order.status === "ORDERED" || order.status === "PARTIALLY_RECEIVED") && canReceive && (
            <Link className="purchasing-primary" href={`/app/purchasing/orders/${order.id}/receive`}>Receive goods</Link>
          )}
        </div>
      </header>

      <dl className="purchase-document-meta">
        <div><dt>Status</dt><dd><span className={statusClass(order.status)}>{formatPurchaseStatus(order.status)}</span></dd></div>
        <div><dt>Expected</dt><dd>{formatPurchaseDate(order.expected_at)}</dd></div>
        <div><dt>Delivery</dt><dd>{order.location_name ?? "Current location"}</dd></div>
        <div><dt>Warehouse</dt><dd>{warehouse?.name ?? order.warehouse_name ?? "—"}</dd></div>
      </dl>

      {error && <div className="purchase-inline-alert is-error" role="alert">{error}</div>}

      <div className="purchasing-table-wrap" tabIndex={0} aria-label="Purchase order lines">
        <table className="purchasing-table order-lines-table">
          <caption className="sr-only">Items in {order.number}</caption>
          <thead><tr><th scope="col">Item</th><th scope="col">Ordered</th><th scope="col">Received</th><th scope="col">Remaining</th><th scope="col">Unit price</th><th scope="col">Total</th></tr></thead>
          <tbody>
            {(order.lines ?? []).map((line) => {
              const receivedBase = line.received_base_quantity ?? "0";
              const multiplier = Number(line.unit_multiplier) || 1;
              const received = Number(receivedBase) / multiplier;
              const remaining = Math.max(0, Number(line.ordered_quantity) - received);
              return (
                <tr key={line.id}>
                  <td><strong>{itemNames.get(line.inventory_item_id) ?? "Inventory item"}</strong></td>
                  <td>{line.ordered_quantity} {formatPurchaseUnit(line.purchase_unit)}</td>
                  <td>{received} {formatPurchaseUnit(line.purchase_unit)}</td>
                  <td>{remaining} {formatPurchaseUnit(line.purchase_unit)}</td>
                  <td>{formatMoneyAmount(line.unit_price, order.currency_code)} / {formatPurchaseUnit(line.purchase_unit)}</td>
                  <td>{formatMoneyMinor(line.line_total_minor, order.currency_code)}</td>
                </tr>
              );
            })}
          </tbody>
          <tfoot><tr><th colSpan={5} scope="row">Total</th><td>{formatMoneyMinor(order.total_minor ?? orderTotalMinor(order.lines ?? []), order.currency_code)}</td></tr></tfoot>
        </table>
      </div>

      {order.note && <p className="purchase-document-note"><strong>Note</strong>{order.note}</p>}

      <section className="purchase-related">
        <div className="purchase-section-heading"><div><h2>Goods receipts</h2><p>Deliveries posted against this order.</p></div><span>{receipts.length}</span></div>
        {receipts.length === 0 ? (
          <div className="purchasing-state is-compact">No receipts yet.</div>
        ) : (
          <div className="purchase-related-list">
            {receipts.map((receipt) => (
              <Link key={receipt.id} href={`/app/purchasing/receipts/${receipt.id}`}>
                <strong>{receipt.number}</strong>
                <span>{formatPurchaseDate(receipt.received_at)}</span>
                <span className={statusClass(receipt.status)}>{formatPurchaseStatus(receipt.status)}</span>
              </Link>
            ))}
          </div>
        )}
      </section>
    </>
  );
}
