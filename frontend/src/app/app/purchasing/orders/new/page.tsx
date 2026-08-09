"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import {
  makePurchaseLine,
  PurchaseLinesEditor,
  type EditablePurchaseLine,
} from "@/components/purchase-lines-editor";
import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { usePurchasingPermissions } from "@/hooks/use-purchasing-permissions";
import {
  api,
  type InventoryItemResponse,
  type Supplier,
  type WarehouseResponse,
} from "@/lib/api";
import { isNonNegativeDecimal, isPositiveDecimal } from "@/lib/purchasing";

export default function NewPurchaseOrderPage() {
  const { accessToken } = useAuth();
  const { currentOrganization, currentLocation } = useWorkspace();
  const { canCreate, loading: permissionsLoading } = usePurchasingPermissions();
  const router = useRouter();
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [warehouses, setWarehouses] = useState<WarehouseResponse[]>([]);
  const [items, setItems] = useState<InventoryItemResponse[]>([]);
  const [supplierId, setSupplierId] = useState("");
  const [warehouseId, setWarehouseId] = useState("");
  const [expectedAt, setExpectedAt] = useState("");
  const [note, setNote] = useState("");
  const [lines, setLines] = useState<EditablePurchaseLine[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState<"draft" | "submit" | "">("");
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    if (!accessToken || !currentOrganization || !currentLocation) return;
    Promise.resolve().then(() => {
      if (cancelled) return [[], [], []] as [Supplier[], WarehouseResponse[], InventoryItemResponse[]];
      setLoading(true);
      return Promise.all([
        api.listSuppliers(currentOrganization.id, accessToken),
        api.listInventoryWarehouses(currentOrganization.id, accessToken),
        api.listInventoryItems(currentOrganization.id, accessToken),
      ]);
    })
      .then(([nextSuppliers, nextWarehouses, nextItems]) => {
        if (cancelled) return;
        const localWarehouses = nextWarehouses.filter(
          (warehouse) => warehouse.is_active && warehouse.location_id === currentLocation.id,
        );
        const activeItems = nextItems.filter((item) => item.is_active);
        setSuppliers(nextSuppliers.filter((supplier) => supplier.is_active));
        setWarehouses(localWarehouses);
        setItems(activeItems);
        setSupplierId(nextSuppliers.find((supplier) => supplier.is_active)?.id ?? "");
        setWarehouseId(localWarehouses[0]?.id ?? "");
        setLines([makePurchaseLine(activeItems[0])]);
      })
      .catch((caught) => {
        if (!cancelled) setError(caught instanceof Error ? caught.message : "Unable to prepare order");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [accessToken, currentLocation, currentOrganization]);

  async function save(shouldSubmit: boolean) {
    if (!accessToken || !currentOrganization || !currentLocation) return;
    const validationError = validateLines(lines);
    if (!supplierId || !warehouseId || validationError) {
      setError(validationError || "Select a supplier and warehouse.");
      return;
    }
    setSubmitting(shouldSubmit ? "submit" : "draft");
    setError("");
    try {
      const order = await api.createPurchaseOrder(
        {
          supplier_id: supplierId,
          location_id: currentLocation.id,
          warehouse_id: warehouseId,
          expected_at: expectedAt ? new Date(`${expectedAt}T12:00:00`).toISOString() : null,
          note: note.trim() || null,
          lines: lines.map((line) => ({
            inventory_item_id: line.inventoryItemId,
            quantity: line.quantity.trim(),
            purchase_unit: line.purchaseUnit.trim(),
            unit_multiplier: line.unitMultiplier.trim(),
            unit_price: line.unitPrice.trim(),
          })),
        },
        currentOrganization.id,
        accessToken,
      );
      if (shouldSubmit) {
        await api.submitPurchaseOrder(order.id, currentOrganization.id, accessToken);
      }
      router.replace(`/app/purchasing/orders/${order.id}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to save purchase order");
      setSubmitting("");
    }
  }

  if (loading || permissionsLoading) {
    return <div className="purchasing-state">Preparing purchase order…</div>;
  }
  if (!canCreate) {
    return <div className="purchasing-state is-error" role="alert"><strong>Create permission required</strong><span>Your role cannot create purchase orders.</span></div>;
  }

  return (
    <>
      <Link className="purchasing-back" href="/app/purchasing/orders">
        <ArrowLeft aria-hidden="true" />
        Purchase orders
      </Link>
      <header className="purchasing-header">
        <div>
          <h1>New purchase order</h1>
          <p>Plan the items and prices expected from a supplier.</p>
        </div>
      </header>
      <form className="purchase-form" onSubmit={(event) => { event.preventDefault(); void save(false); }}>
        <div className="purchase-form-grid">
          <label className="purchase-field">
            <span>Supplier</span>
            <select value={supplierId} onChange={(event) => setSupplierId(event.target.value)} required>
              <option value="">Select supplier</option>
              {suppliers.map((supplier) => <option key={supplier.id} value={supplier.id}>{supplier.name}</option>)}
            </select>
          </label>
          <label className="purchase-field">
            <span>Deliver to</span>
            <input value={currentLocation?.name ?? ""} readOnly aria-readonly="true" />
          </label>
          <label className="purchase-field">
            <span>Warehouse</span>
            <select value={warehouseId} onChange={(event) => setWarehouseId(event.target.value)} required>
              <option value="">Select warehouse</option>
              {warehouses.map((warehouse) => <option key={warehouse.id} value={warehouse.id}>{warehouse.name}</option>)}
            </select>
          </label>
          <label className="purchase-field">
            <span>Expected</span>
            <input type="date" value={expectedAt} onChange={(event) => setExpectedAt(event.target.value)} />
          </label>
        </div>

        <PurchaseLinesEditor
          lines={lines}
          items={items}
          currency={currentOrganization?.currency_code ?? "KZT"}
          onChange={setLines}
        />

        <label className="purchase-field purchase-note">
          <span>Note</span>
          <textarea maxLength={1000} value={note} onChange={(event) => setNote(event.target.value)} placeholder="Optional delivery instructions" />
        </label>
        <div className="form-message purchase-error" role="alert">{error}</div>
        <div className="purchase-form-actions">
          <Link className="secondary-button" href="/app/purchasing/orders">Cancel</Link>
          <button className="secondary-button" type="submit" disabled={Boolean(submitting)}>
            {submitting === "draft" ? "Saving…" : "Save draft"}
          </button>
          <button
            className="purchasing-primary"
            type="button"
            disabled={Boolean(submitting)}
            onClick={() => void save(true)}
          >
            {submitting === "submit" ? "Submitting…" : "Submit order"}
          </button>
        </div>
      </form>
    </>
  );
}

function validateLines(lines: EditablePurchaseLine[]) {
  if (lines.length === 0) return "Add at least one item.";
  for (const line of lines) {
    if (!line.inventoryItemId) return "Select an inventory item on every line.";
    if (!isPositiveDecimal(line.quantity)) return "Every quantity must be greater than zero with no more than 6 decimal places.";
    if (!line.purchaseUnit.trim()) return "Enter a purchase unit on every line.";
    if (!isPositiveDecimal(line.unitMultiplier)) return "Every unit multiplier must be greater than zero.";
    if (!isNonNegativeDecimal(line.unitPrice)) return "Every unit price must be zero or greater.";
  }
  return "";
}
