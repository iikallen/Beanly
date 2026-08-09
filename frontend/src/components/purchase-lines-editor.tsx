"use client";

import { Plus, Trash2 } from "lucide-react";

import type { InventoryItemResponse } from "@/lib/api";
import { defaultPurchaseUnit, formatPurchaseUnit } from "@/lib/purchasing";

export type EditablePurchaseLine = {
  key: string;
  inventoryItemId: string;
  quantity: string;
  purchaseUnit: string;
  unitMultiplier: string;
  unitPrice: string;
};

export function makePurchaseLine(item?: InventoryItemResponse): EditablePurchaseLine {
  const defaults = defaultPurchaseUnit(item?.base_unit ?? "pcs");
  return {
    key: crypto.randomUUID(),
    inventoryItemId: item?.id ?? "",
    quantity: "",
    purchaseUnit: defaults.unit,
    unitMultiplier: defaults.multiplier,
    unitPrice: "",
  };
}

export function PurchaseLinesEditor({
  lines,
  items,
  currency,
  onChange,
}: {
  lines: EditablePurchaseLine[];
  items: InventoryItemResponse[];
  currency: string;
  onChange: (lines: EditablePurchaseLine[]) => void;
}) {
  function update(key: string, patch: Partial<EditablePurchaseLine>) {
    onChange(lines.map((line) => line.key === key ? { ...line, ...patch } : line));
  }

  return (
    <fieldset className="purchase-lines-fieldset">
      <legend>Items</legend>
      <div className="purchase-line-head" aria-hidden="true">
        <span>Inventory item</span>
        <span>Quantity</span>
        <span>Purchase unit</span>
        <span>1 unit equals</span>
        <span>Unit price</span>
        <span />
      </div>
      <div className="purchase-line-list">
        {lines.map((line, index) => {
          const selectedItem = items.find((item) => item.id === line.inventoryItemId);
          return (
            <div className="purchase-line-row" key={line.key}>
              <label>
                <span className="sr-only">Item {index + 1}</span>
                <select
                  aria-label={`Item ${index + 1}`}
                  value={line.inventoryItemId}
                  onChange={(event) => {
                    const nextItem = items.find((item) => item.id === event.target.value);
                    const defaults = defaultPurchaseUnit(nextItem?.base_unit ?? "pcs");
                    update(line.key, {
                      inventoryItemId: event.target.value,
                      purchaseUnit: defaults.unit,
                      unitMultiplier: defaults.multiplier,
                    });
                  }}
                >
                  <option value="">Select item</option>
                  {items.map((item) => (
                    <option key={item.id} value={item.id}>{item.name}</option>
                  ))}
                </select>
              </label>
              <label>
                <span className="sr-only">Quantity for item {index + 1}</span>
                <input
                  aria-label={`Quantity for item ${index + 1}`}
                  inputMode="decimal"
                  placeholder="10"
                  value={line.quantity}
                  onChange={(event) => update(line.key, { quantity: event.target.value })}
                />
              </label>
              <label>
                <span className="sr-only">Purchase unit for item {index + 1}</span>
                <input
                  aria-label={`Purchase unit for item ${index + 1}`}
                  placeholder="bag"
                  maxLength={50}
                  value={line.purchaseUnit}
                  onChange={(event) => update(line.key, { purchaseUnit: event.target.value })}
                />
              </label>
              <label className="purchase-multiplier">
                <span className="sr-only">Unit multiplier for item {index + 1}</span>
                <input
                  aria-label={`Unit multiplier for item ${index + 1}`}
                  inputMode="decimal"
                  placeholder="1000"
                  value={line.unitMultiplier}
                  onChange={(event) => update(line.key, { unitMultiplier: event.target.value })}
                />
                <span>{selectedItem ? formatPurchaseUnit(selectedItem.base_unit) : "base units"}</span>
              </label>
              <label className="purchase-price">
                <span className="sr-only">Unit price for item {index + 1}</span>
                <input
                  aria-label={`Unit price for item ${index + 1}`}
                  inputMode="decimal"
                  placeholder="8000"
                  value={line.unitPrice}
                  onChange={(event) => update(line.key, { unitPrice: event.target.value })}
                />
                <span>{currency} / {formatPurchaseUnit(line.purchaseUnit || "unit")}</span>
              </label>
              <button
                className="purchase-line-remove"
                type="button"
                aria-label={`Remove item ${index + 1}`}
                disabled={lines.length === 1}
                onClick={() => onChange(lines.filter((item) => item.key !== line.key))}
              >
                <Trash2 aria-hidden="true" />
              </button>
            </div>
          );
        })}
      </div>
      <button
        className="purchase-add-line"
        type="button"
        disabled={items.length === 0}
        onClick={() => onChange([...lines, makePurchaseLine(items[0])])}
      >
        <Plus aria-hidden="true" />
        Add item
      </button>
    </fieldset>
  );
}
