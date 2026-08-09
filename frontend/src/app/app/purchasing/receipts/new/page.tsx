"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import {
  makePurchaseLine,
  PurchaseLinesEditor,
  type EditablePurchaseLine,
} from "@/components/purchase-lines-editor";
import { useWorkspace } from "@/components/workspace-provider";
import { usePurchasingPermissions } from "@/hooks/use-purchasing-permissions";
import { api, type InventoryItemResponse, type Supplier, type WarehouseResponse } from "@/lib/api";
import { isNonNegativeDecimal, isPositiveDecimal } from "@/lib/purchasing";

export default function QuickReceivePage() {
  const { accessToken } = useAuth();
  const { currentOrganization, currentLocation } = useWorkspace();
  const { canReceive, loading: permissionsLoading } = usePurchasingPermissions();
  const router = useRouter();
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [warehouses, setWarehouses] = useState<WarehouseResponse[]>([]);
  const [items, setItems] = useState<InventoryItemResponse[]>([]);
  const [supplierId, setSupplierId] = useState("");
  const [warehouseId, setWarehouseId] = useState("");
  const [documentNumber, setDocumentNumber] = useState("");
  const [receivedAt, setReceivedAt] = useState(() => localDateTimeValue(new Date()));
  const [note, setNote] = useState("");
  const [lines, setLines] = useState<EditablePurchaseLine[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState<"draft" | "post" | "">("");
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    if (!accessToken || !currentOrganization || !currentLocation) return;
    Promise.all([
      api.listSuppliers(currentOrganization.id, accessToken),
      api.listInventoryWarehouses(currentOrganization.id, accessToken),
      api.listInventoryItems(currentOrganization.id, accessToken),
    ])
      .then(([nextSuppliers, nextWarehouses, nextItems]) => {
        if (cancelled) return;
        const localWarehouses = nextWarehouses.filter((item) => item.is_active && item.location_id === currentLocation.id);
        const activeItems = nextItems.filter((item) => item.is_active);
        const activeSuppliers = nextSuppliers.filter((item) => item.is_active);
        setSuppliers(activeSuppliers);
        setWarehouses(localWarehouses);
        setItems(activeItems);
        setSupplierId(activeSuppliers[0]?.id ?? "");
        setWarehouseId(localWarehouses[0]?.id ?? "");
        setLines([makePurchaseLine(activeItems[0])]);
      })
      .catch((caught) => {
        if (!cancelled) setError(caught instanceof Error ? caught.message : "Unable to prepare quick receipt");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [accessToken, currentLocation, currentOrganization]);

  async function save(post: boolean) {
    if (!accessToken || !currentOrganization || !currentLocation) return;
    const validationError = validateLines(lines);
    if (!supplierId || !warehouseId || !receivedAt || validationError) {
      setError(validationError || "Select a supplier, warehouse, and received time.");
      return;
    }
    setSubmitting(post ? "post" : "draft");
    setError("");
    try {
      const receipt = await api.createGoodsReceipt({
        purchase_order_id: null,
        supplier_id: supplierId,
        location_id: currentLocation.id,
        warehouse_id: warehouseId,
        document_number: documentNumber.trim() || null,
        received_at: new Date(receivedAt).toISOString(),
        note: note.trim() || null,
        lines: lines.map((line) => ({
          inventory_item_id: line.inventoryItemId,
          quantity: line.quantity.trim(),
          purchase_unit: line.purchaseUnit.trim(),
          unit_multiplier: line.unitMultiplier.trim(),
          unit_price: line.unitPrice.trim(),
        })),
      }, currentOrganization.id, accessToken);
      if (post) await api.postGoodsReceipt(receipt.id, false, currentOrganization.id, accessToken);
      router.replace(`/app/purchasing/receipts/${receipt.id}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to save goods receipt");
      setSubmitting("");
    }
  }

  if (loading || permissionsLoading) return <div className="purchasing-state">Preparing quick receipt…</div>;
  if (!canReceive) return <div className="purchasing-state is-error" role="alert"><strong>Receive permission required</strong><span>Your role cannot receive goods.</span></div>;

  return (
    <>
      <Link className="purchasing-back" href="/app/purchasing/receipts"><ArrowLeft aria-hidden="true" />Goods receipts</Link>
      <header className="purchasing-header"><div><h1>Quick receive</h1><p>Record goods delivered without a purchase order.</p></div></header>
      <form className="purchase-form" onSubmit={(event) => { event.preventDefault(); void save(false); }}>
        <div className="purchase-form-grid">
          <label className="purchase-field"><span>Supplier</span><select value={supplierId} onChange={(event) => setSupplierId(event.target.value)} required><option value="">Select supplier</option>{suppliers.map((supplier) => <option key={supplier.id} value={supplier.id}>{supplier.name}</option>)}</select></label>
          <label className="purchase-field"><span>Warehouse</span><select value={warehouseId} onChange={(event) => setWarehouseId(event.target.value)} required><option value="">Select warehouse</option>{warehouses.map((warehouse) => <option key={warehouse.id} value={warehouse.id}>{warehouse.name}</option>)}</select></label>
          <label className="purchase-field"><span>Received at</span><input type="datetime-local" value={receivedAt} onChange={(event) => setReceivedAt(event.target.value)} required /></label>
          <label className="purchase-field"><span>Supplier document number</span><input value={documentNumber} onChange={(event) => setDocumentNumber(event.target.value)} placeholder="Invoice #INV-34819" maxLength={100} /></label>
        </div>
        <PurchaseLinesEditor lines={lines} items={items} currency={currentOrganization?.currency_code ?? "KZT"} onChange={setLines} />
        <label className="purchase-field purchase-note"><span>Note</span><textarea maxLength={1000} value={note} onChange={(event) => setNote(event.target.value)} placeholder="Optional note" /></label>
        <div className="form-message purchase-error" role="alert">{error}</div>
        <div className="purchase-form-actions"><Link className="secondary-button" href="/app/purchasing/receipts">Cancel</Link><button className="secondary-button" type="submit" disabled={Boolean(submitting)}>{submitting === "draft" ? "Saving…" : "Save draft"}</button><button className="purchasing-primary" type="button" disabled={Boolean(submitting)} onClick={() => void save(true)}>{submitting === "post" ? "Posting…" : "Post receipt"}</button></div>
      </form>
    </>
  );
}

function validateLines(lines: EditablePurchaseLine[]) {
  if (lines.length === 0) return "Add at least one item.";
  for (const line of lines) {
    if (!line.inventoryItemId) return "Select an inventory item on every line.";
    if (!isPositiveDecimal(line.quantity)) return "Every quantity must be greater than zero.";
    if (!line.purchaseUnit.trim()) return "Enter a purchase unit on every line.";
    if (!isPositiveDecimal(line.unitMultiplier)) return "Every unit multiplier must be greater than zero.";
    if (!isNonNegativeDecimal(line.unitPrice)) return "Every unit price must be zero or greater.";
  }
  return "";
}

function localDateTimeValue(date: Date) {
  const offset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}
