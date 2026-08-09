"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, useEffect, useRef, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { useInventoryPermissions } from "@/hooks/use-inventory-permissions";
import {
  api,
  type InventoryItemResponse,
  type InventoryUnitCode,
  type StockRow,
  type WarehouseResponse,
} from "@/lib/api";
import {
  formatInventoryQuantity,
  isZeroDecimal,
  preferredDisplayUnit,
  unitsFor,
} from "@/lib/inventory";

const DECIMAL = /^[+-]?\d+(?:\.\d{1,6})?$/;

export default function InventoryAdjustmentPage() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const { accessToken } = useAuth();
  const { currentOrganization, currentLocation } = useWorkspace();
  const { canAdjust, loading: permissionsLoading } = useInventoryPermissions();
  const [warehouses, setWarehouses] = useState<WarehouseResponse[]>([]);
  const [items, setItems] = useState<InventoryItemResponse[]>([]);
  const [warehouseId, setWarehouseId] = useState("");
  const [itemId, setItemId] = useState("");
  const [stock, setStock] = useState<StockRow | null>(null);
  const [quantity, setQuantity] = useState("");
  const [unit, setUnit] = useState<InventoryUnitCode>("pcs");
  const [reason, setReason] = useState("");
  const [unitCost, setUnitCost] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const idempotencyKey = useRef<string | null>(null);
  const [requestedWarehouse] = useState(() => searchParams.get("warehouse_id"));
  const [requestedItem] = useState(() => searchParams.get("item_id"));
  const [openingMode] = useState(() => searchParams.get("mode") === "opening");

  useEffect(() => {
    let cancelled = false;
    if (!accessToken || !currentOrganization || !currentLocation) return;
    Promise.resolve().then(() => {
      if (cancelled) return [[], []] as [WarehouseResponse[], InventoryItemResponse[]];
      setLoading(true);
      setError("");
      return Promise.all([
        api.listInventoryWarehouses(currentOrganization.id, accessToken),
        api.listInventoryItems(currentOrganization.id, accessToken),
      ]);
    })
      .then(([availableWarehouses, availableItems]) => {
        if (cancelled) return;
        const localWarehouses = availableWarehouses.filter(
          (item) => item.is_active && item.location_id === currentLocation.id,
        );
        const activeItems = availableItems.filter((item) => item.is_active);
        setWarehouses(localWarehouses);
        setItems(activeItems);
        setWarehouseId(
          localWarehouses.find((item) => item.id === requestedWarehouse)?.id ??
          localWarehouses[0]?.id ??
          "",
        );
        const selectedItem =
          activeItems.find((item) => item.id === requestedItem) ?? activeItems[0] ?? null;
        setItemId(selectedItem?.id ?? "");
        if (selectedItem) setUnit(unitsFor(selectedItem.base_unit)[0]);
      })
      .catch((caught) => {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : "Unable to prepare adjustment");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [accessToken, currentLocation, currentOrganization, requestedItem, requestedWarehouse]);

  useEffect(() => {
    let cancelled = false;
    if (!accessToken || !currentOrganization || !warehouseId || !itemId) return;
    Promise.resolve().then(() => {
      if (cancelled) return null;
      setStock(null);
      setError("");
      return api.getItemStock(itemId, warehouseId, currentOrganization.id, accessToken);
    })
      .then((nextStock) => {
        if (cancelled || !nextStock) return;
        setStock(nextStock);
        setUnit(preferredDisplayUnit(nextStock.quantity, nextStock.base_unit));
        setUnitCost("");
      })
      .catch(() => {
        if (!cancelled) {
          setStock(null);
          setError("Current stock could not be loaded. Try again before posting.");
        }
      });
    return () => { cancelled = true; };
  }, [accessToken, currentOrganization, itemId, warehouseId]);

  const selectedItem = items.find((item) => item.id === itemId) ?? null;
  const itemUnits = unitsFor(selectedItem?.base_unit ?? "pcs");
  const backHref = warehouseId
    ? `/app/inventory?warehouse_id=${encodeURIComponent(warehouseId)}`
    : "/app/inventory";
  const cleanQuantityValue = quantity.trim();
  const isPositive = DECIMAL.test(cleanQuantityValue) &&
    !cleanQuantityValue.startsWith("-") && !isZeroDecimal(cleanQuantityValue);
  const needsManualCost = openingMode || Boolean(
    isPositive && stock && stock.average_unit_cost !== null &&
    isZeroDecimal(stock.average_unit_cost) && isZeroDecimal(stock.quantity)
  );

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!accessToken || !currentOrganization || !warehouseId || !itemId || !stock) return;
    const cleanQuantity = quantity.trim();
    if (!DECIMAL.test(cleanQuantity) || isZeroDecimal(cleanQuantity)) {
      setError("Enter a non-zero quantity with no more than 6 decimal places.");
      return;
    }
    if (openingMode && cleanQuantity.startsWith("-")) {
      setError("Opening balance quantity must be positive.");
      return;
    }
    const cleanCost = unitCost.trim();
    if (needsManualCost && (!DECIMAL.test(cleanCost) || cleanCost.startsWith("-"))) {
      setError("Enter a non-negative unit cost with no more than 6 decimal places.");
      return;
    }
    if (!openingMode && !reason.trim()) {
      setError("Enter a reason for this adjustment.");
      return;
    }
    setSubmitting(true);
    setError("");
    idempotencyKey.current ??= crypto.randomUUID();
    try {
      const line = {
        inventory_item_id: itemId,
        quantity: cleanQuantity,
        unit_code: unit,
        ...(needsManualCost ? { unit_cost_amount: cleanCost } : {}),
      };
      if (openingMode) {
        await api.createOpeningBalance(
          { warehouse_id: warehouseId, items: [line] },
          currentOrganization.id,
          accessToken,
          idempotencyKey.current,
        );
      } else {
        await api.createInventoryAdjustment(
          { warehouse_id: warehouseId, reason: reason.trim(), lines: [line] },
          currentOrganization.id,
          accessToken,
          idempotencyKey.current,
        );
      }
      router.replace(
        `/app/inventory/items/${itemId}?warehouse_id=${encodeURIComponent(warehouseId)}`,
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to adjust inventory");
      setSubmitting(false);
    }
  }

  if (loading || permissionsLoading) {
    return <div className="inventory-state">Preparing adjustment…</div>;
  }
  if (!canAdjust) {
    return (
      <div className="inventory-state is-error" role="alert">
        <strong>Inventory adjustment permission required</strong>
        <span>Your role cannot change inventory balances.</span>
        <Link href={backHref}>Back to inventory</Link>
      </div>
    );
  }

  return (
    <>
      <Link className="inventory-back-link" href={backHref}>
        <ArrowLeft aria-hidden="true" />
        Inventory
      </Link>
      <header className="inventory-header">
        <div>
          <h1>{openingMode ? "Opening balance" : "Adjust inventory"}</h1>
          <p>
            {openingMode
              ? "Record the starting quantity and estimated acquisition cost."
              : "Add or subtract from the current stock."}
          </p>
        </div>
      </header>

      <form className="adjustment-card" onSubmit={submit}>
        <label className="adjustment-field">
          <span>Warehouse</span>
          <select
            value={warehouseId}
            disabled={warehouses.length === 0}
            onChange={(event) => setWarehouseId(event.target.value)}
          >
            {warehouses.length === 0 && <option value="">No warehouses</option>}
            {warehouses.map((warehouse) => (
              <option key={warehouse.id} value={warehouse.id}>{warehouse.name}</option>
            ))}
          </select>
        </label>
        <label className="adjustment-field">
          <span>Inventory item</span>
          <select
            value={itemId}
            disabled={items.length === 0}
            onChange={(event) => {
              const nextId = event.target.value;
              const nextItem = items.find((item) => item.id === nextId);
              setItemId(nextId);
              setUnit(unitsFor(nextItem?.base_unit ?? "pcs")[0]);
              setUnitCost("");
            }}
          >
            {items.length === 0 && <option value="">No inventory items</option>}
            {items.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}{item.sku ? ` · ${item.sku}` : ""}
              </option>
            ))}
          </select>
        </label>
        <label className="adjustment-field">
          <span>Current stock</span>
          <input
            value={stock ? formatInventoryQuantity(stock.quantity, stock.base_unit) : `0 ${selectedItem?.base_unit ?? ""}`}
            readOnly
            aria-readonly="true"
          />
        </label>
        <fieldset className="adjustment-change">
          <legend>Change</legend>
          <input
            aria-label="Quantity change"
            type="text"
            inputMode="decimal"
            placeholder={openingMode ? "10" : "-0.25"}
            value={quantity}
            onChange={(event) => setQuantity(event.target.value)}
            required
          />
          <select
            aria-label="Unit"
            value={unit}
            onChange={(event) => {
              setUnit(event.target.value as InventoryUnitCode);
              setUnitCost("");
            }}
          >
            {itemUnits.map((itemUnit) => (
              <option key={itemUnit} value={itemUnit}>{itemUnit === "l" ? "L" : itemUnit}</option>
            ))}
          </select>
          <small>
            {openingMode
              ? "Opening quantity must be positive."
              : "Use a positive number to add stock or a negative number to remove stock."}
          </small>
        </fieldset>
        {needsManualCost && (
          <label className="adjustment-field">
            <span>Estimated cost per {unit === "l" ? "L" : unit}</span>
            <input
              name="unit-cost"
              inputMode="decimal"
              placeholder="0"
              value={unitCost}
              onChange={(event) => setUnitCost(event.target.value)}
              required
            />
            {unitCost.trim() === "0" && (
              <small className="cost-warning">
                A zero cost is allowed, but inventory valuation will be understated until corrected.
              </small>
            )}
          </label>
        )}
        {!openingMode && (
          <label className="adjustment-field">
            <span>Reason</span>
            <input
              name="reason"
              placeholder="Spillage"
              maxLength={1000}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              required
            />
          </label>
        )}

        {quantity && DECIMAL.test(quantity.trim()) && !isZeroDecimal(quantity) && (
          <p className="adjustment-summary">
            This will change the current stock by <strong>{quantity.trim()} {unit === "l" ? "L" : unit}</strong>.
          </p>
        )}
        <div className="form-message adjustment-error" role="alert">{error}</div>
        <div className="adjustment-actions">
          <Link className="secondary-button" href={backHref}>Cancel</Link>
          <button
            className="inventory-adjust-button"
            type="submit"
            disabled={submitting || !warehouseId || !itemId || !stock}
          >
            {submitting
              ? "Saving…"
              : openingMode ? "Post opening balance" : "Confirm adjustment"}
          </button>
        </div>
      </form>
    </>
  );
}
