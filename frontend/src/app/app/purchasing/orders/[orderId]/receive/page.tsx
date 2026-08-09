"use client";

import { ArrowLeft, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { usePurchasingPermissions } from "@/hooks/use-purchasing-permissions";
import {
  ApiError,
  api,
  type InventoryItemResponse,
  type PurchaseOrder,
  type Supplier,
  type WarehouseResponse,
} from "@/lib/api";
import {
  formatPurchaseDate,
  formatPurchaseUnit,
  isNonNegativeDecimal,
} from "@/lib/purchasing";

type ReceiveLine = {
  orderLineId: string;
  inventoryItemId: string;
  quantity: string;
  previouslyReceived: string;
  remaining: string;
  purchaseUnit: string;
  unitMultiplier: string;
  unitPrice: string;
};

export default function ReceivePurchaseOrderPage() {
  const { orderId } = useParams<{ orderId: string }>();
  const router = useRouter();
  const { accessToken } = useAuth();
  const { currentOrganization, currentLocation } = useWorkspace();
  const { canReceive, loading: permissionsLoading } = usePurchasingPermissions();
  const [order, setOrder] = useState<PurchaseOrder | null>(null);
  const [supplier, setSupplier] = useState<Supplier | null>(null);
  const [warehouse, setWarehouse] = useState<WarehouseResponse | null>(null);
  const [items, setItems] = useState<InventoryItemResponse[]>([]);
  const [lines, setLines] = useState<ReceiveLine[]>([]);
  const [documentNumber, setDocumentNumber] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState<"draft" | "post" | "">("");
  const [error, setError] = useState("");
  const receiptId = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (!accessToken || !currentOrganization) return;
    Promise.resolve().then(() => {
      if (cancelled) return null;
      setLoading(true);
      setError("");
      return api.getPurchaseOrder(orderId, currentOrganization.id, accessToken);
    })
      .then(async (nextOrder) => {
        if (!nextOrder) return;
        const [nextSupplier, warehouses, nextItems] = await Promise.all([
          api.getSupplier(nextOrder.supplier_id, currentOrganization.id, accessToken),
          api.listInventoryWarehouses(currentOrganization.id, accessToken),
          api.listInventoryItems(currentOrganization.id, accessToken),
        ]);
        if (cancelled) return;
        setOrder(nextOrder);
        setSupplier(nextSupplier);
        setWarehouse(warehouses.find((item) => item.id === nextOrder.warehouse_id) ?? null);
        setItems(nextItems);
        setLines((nextOrder.lines ?? []).map((line) => {
          const multiplier = Number(line.unit_multiplier) || 1;
          const received = Number(line.received_base_quantity ?? "0") / multiplier;
          const remaining = Math.max(0, Number(line.ordered_quantity) - received);
          return {
            orderLineId: line.id,
            inventoryItemId: line.inventory_item_id,
            quantity: String(remaining),
            previouslyReceived: String(received),
            remaining: String(remaining),
            purchaseUnit: line.purchase_unit,
            unitMultiplier: line.unit_multiplier,
            unitPrice: line.unit_price,
          };
        }));
      })
      .catch((caught) => {
        if (!cancelled) setError(caught instanceof Error ? caught.message : "Unable to prepare receipt");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [accessToken, currentOrganization, orderId]);

  const itemNames = useMemo(
    () => new Map(items.map((item) => [item.id, item.name])),
    [items],
  );
  const partialLines = lines.filter(
    (line) => Number(line.quantity) >= 0 && Number(line.quantity) < Number(line.remaining),
  );
  const hasOverReceipt = lines.some((line) => Number(line.quantity) > Number(line.remaining));

  function updateLine(orderLineId: string, patch: Partial<ReceiveLine>) {
    setLines((current) => current.map((line) => line.orderLineId === orderLineId ? { ...line, ...patch } : line));
  }

  async function save(post: boolean) {
    if (!accessToken || !currentOrganization || !order) return;
    const included = lines.filter((line) => Number(line.quantity) > 0);
    if (included.length === 0) {
      setError("Enter a received quantity for at least one item.");
      return;
    }
    if (included.some((line) => !isNonNegativeDecimal(line.quantity) || !isNonNegativeDecimal(line.unitPrice))) {
      setError("Quantities and prices must be valid numbers with no more than 6 decimal places.");
      return;
    }
    let confirmOverReceipt = false;
    if (post && hasOverReceipt) {
      confirmOverReceipt = window.confirm("The received quantity exceeds the order. Post the actual delivery anyway?");
      if (!confirmOverReceipt) return;
    }
    setSubmitting(post ? "post" : "draft");
    setError("");
    try {
      const input = {
        document_number: documentNumber.trim() || null,
        received_at: new Date().toISOString(),
        note: null,
        lines: included.map((line) => ({
          purchase_order_line_id: line.orderLineId,
          inventory_item_id: line.inventoryItemId,
          quantity: line.quantity.trim(),
          purchase_unit: line.purchaseUnit,
          unit_multiplier: line.unitMultiplier,
          unit_price: line.unitPrice.trim(),
        })),
      };
      const receipt = receiptId.current
        ? await api.updateGoodsReceipt(receiptId.current, input, currentOrganization.id, accessToken)
        : await api.createOrderReceipt(order.id, input, currentOrganization.id, accessToken);
      receiptId.current = receipt.id;
      if (post) {
        try {
          await api.postGoodsReceipt(receipt.id, confirmOverReceipt, currentOrganization.id, accessToken);
        } catch (caught) {
          if (
            caught instanceof ApiError &&
            caught.status === 409 &&
            caught.code === "RECEIVED_QUANTITY_EXCEEDS_ORDER" &&
            window.confirm("The received quantity exceeds the order. Post the actual delivery anyway?")
          ) {
            await api.postGoodsReceipt(receipt.id, true, currentOrganization.id, accessToken);
          } else {
            throw caught;
          }
        }
      }
      router.replace(`/app/purchasing/receipts/${receipt.id}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to save goods receipt");
      setSubmitting("");
    }
  }

  if (loading || permissionsLoading) return <div className="purchasing-state">Preparing receipt…</div>;
  if (!canReceive) return <div className="purchasing-state is-error" role="alert"><strong>Receive permission required</strong><span>Your role cannot receive goods.</span></div>;
  if (error && !order) return <div className="purchasing-state is-error" role="alert"><strong>Receipt could not be prepared.</strong><span>{error}</span></div>;
  if (!order) return null;

  return (
    <>
      <Link className="purchasing-back" href={`/app/purchasing/orders/${order.id}`}>
        <ArrowLeft aria-hidden="true" />
        Purchase orders
      </Link>
      <header className="purchasing-header receive-header">
        <div>
          <h1>Receive {order.number}</h1>
          <p>Record the quantities and actual prices delivered to {warehouse?.name ?? "the warehouse"}.</p>
        </div>
      </header>

      <dl className="receive-meta">
        <div><dt>Supplier</dt><dd>{supplier?.name ?? order.supplier_name ?? "—"}</dd></div>
        <div><dt>Expected</dt><dd>{formatPurchaseDate(order.expected_at)}</dd></div>
        <div><dt>Delivery</dt><dd>{currentLocation?.name ?? order.location_name ?? "—"}</dd></div>
      </dl>

      <label className="purchase-field receive-document-number">
        <span>Supplier document number</span>
        <input value={documentNumber} onChange={(event) => setDocumentNumber(event.target.value)} placeholder="Invoice #INV-34819" maxLength={100} />
      </label>

      <div className="receive-table-wrap" tabIndex={0} aria-label="Items to receive">
        <table className="receive-table">
          <caption className="sr-only">Receive items for {order.number}</caption>
          <thead><tr><th scope="col">Item</th><th scope="col">Ordered</th><th scope="col">Previously received</th><th scope="col">Received now</th><th scope="col">Actual price</th></tr></thead>
          <tbody>
            {lines.map((line, index) => (
              <tr key={line.orderLineId}>
                <td><strong>{itemNames.get(line.inventoryItemId) ?? "Inventory item"}</strong></td>
                <td>{Number(line.remaining) + Number(line.previouslyReceived)} {formatPurchaseUnit(line.purchaseUnit)}</td>
                <td>{line.previouslyReceived} {formatPurchaseUnit(line.purchaseUnit)}</td>
                <td>
                  <label className="receive-input-group">
                    <span className="sr-only">Received now for item {index + 1}</span>
                    <input aria-label={`Received now for ${itemNames.get(line.inventoryItemId) ?? `item ${index + 1}`}`} inputMode="decimal" value={line.quantity} onChange={(event) => updateLine(line.orderLineId, { quantity: event.target.value })} />
                    <span>{formatPurchaseUnit(line.purchaseUnit)}</span>
                  </label>
                </td>
                <td>
                  <label className="receive-input-group receive-price-group">
                    <span className="sr-only">Actual price for item {index + 1}</span>
                    <input aria-label={`Actual price for ${itemNames.get(line.inventoryItemId) ?? `item ${index + 1}`}`} inputMode="decimal" value={line.unitPrice} onChange={(event) => updateLine(line.orderLineId, { unitPrice: event.target.value })} />
                    <span>{order.currency_code} per {formatPurchaseUnit(line.purchaseUnit)}</span>
                  </label>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {(partialLines.length > 0 || hasOverReceipt) && (
        <div className="receive-warning" role="status">
          <TriangleAlert aria-hidden="true" />
          <span>
            {hasOverReceipt
              ? "One or more quantities exceed the remaining order and require confirmation."
              : `${itemNames.get(partialLines[0].inventoryItemId) ?? "An item"} will remain partially received: ${Number(partialLines[0].remaining) - Number(partialLines[0].quantity)} ${formatPurchaseUnit(partialLines[0].purchaseUnit)} remaining.`}
          </span>
        </div>
      )}
      <div className="form-message purchase-error" role="alert">{error}</div>
      <div className="receive-actions">
        <button className="secondary-button" type="button" disabled={Boolean(submitting)} onClick={() => void save(false)}>{submitting === "draft" ? "Saving…" : "Save draft"}</button>
        <button className="purchasing-primary" type="button" disabled={Boolean(submitting)} onClick={() => void save(true)}>{submitting === "post" ? "Posting…" : "Post receipt"}</button>
      </div>
    </>
  );
}
