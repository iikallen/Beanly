"use client";

import { Plus, Trash2 } from "lucide-react";

import type { InventoryItemResponse, InventoryUnitCode } from "@/lib/api";
import { unitsFor } from "@/lib/inventory";

export type InventoryLineValue = {
  key: string;
  inventoryItemId: string;
  quantity: string;
  unit: InventoryUnitCode;
};

export function InventoryLinesEditor({
  items,
  lines,
  onChange,
  disabled = false,
}: {
  items: InventoryItemResponse[];
  lines: InventoryLineValue[];
  onChange: (lines: InventoryLineValue[]) => void;
  disabled?: boolean;
}) {
  function update(key: string, patch: Partial<InventoryLineValue>) {
    onChange(lines.map((line) => line.key === key ? { ...line, ...patch } : line));
  }

  return (
    <fieldset className="operation-lines" disabled={disabled}>
      <legend>Items</legend>
      <div className="operation-line-list">
        {lines.map((line, index) => {
          const item = items.find((candidate) => candidate.id === line.inventoryItemId);
          return (
            <div className="operation-line" key={line.key}>
              <label>
                <span>Item {index + 1}</span>
                <select
                  aria-label={`Item ${index + 1}`}
                  value={line.inventoryItemId}
                  onChange={(event) => {
                    const next = items.find((candidate) => candidate.id === event.target.value);
                    update(line.key, {
                      inventoryItemId: event.target.value,
                      unit: next?.base_unit ?? "pcs",
                    });
                  }}
                  required
                >
                  <option value="">Select item</option>
                  {items.map((candidate) => <option key={candidate.id} value={candidate.id}>{candidate.name}</option>)}
                </select>
              </label>
              <label>
                <span>Quantity</span>
                <input
                  aria-label={`Quantity for item ${index + 1}`}
                  inputMode="decimal"
                  value={line.quantity}
                  onChange={(event) => update(line.key, { quantity: event.target.value })}
                  placeholder="0"
                  required
                />
              </label>
              <label>
                <span>Unit</span>
                <select
                  aria-label={`Unit for item ${index + 1}`}
                  value={line.unit}
                  onChange={(event) => update(line.key, { unit: event.target.value as InventoryUnitCode })}
                >
                  {unitsFor(item?.base_unit ?? "pcs").map((unit) => <option key={unit} value={unit}>{unit === "l" ? "L" : unit}</option>)}
                </select>
              </label>
              <button
                className="operation-remove-line"
                type="button"
                aria-label={`Remove item ${index + 1}`}
                disabled={lines.length === 1}
                onClick={() => onChange(lines.filter((candidate) => candidate.key !== line.key))}
              >
                <Trash2 aria-hidden="true" />
              </button>
            </div>
          );
        })}
      </div>
      <button
        className="operation-add-line"
        type="button"
        onClick={() => onChange([...lines, emptyInventoryLine()])}
      >
        <Plus aria-hidden="true" /> Add item
      </button>
    </fieldset>
  );
}

export function emptyInventoryLine(): InventoryLineValue {
  return { key: crypto.randomUUID(), inventoryItemId: "", quantity: "", unit: "pcs" };
}
