"use client";

import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { useInventoryPermissions } from "@/hooks/use-inventory-permissions";
import { api, type InventoryItemResponse, type InventoryMovement, type WarehouseResponse } from "@/lib/api";
import { formatInventoryDate, formatInventoryMoney, formatInventoryQuantity, formatTransactionType } from "@/lib/inventory";

export default function InventoryMovementsPage() {
  const { accessToken } = useAuth();
  const { currentOrganization, currentLocation } = useWorkspace();
  const { canReadMovements, loading: permissionsLoading } = useInventoryPermissions();
  const [warehouses, setWarehouses] = useState<WarehouseResponse[]>([]);
  const [items, setItems] = useState<InventoryItemResponse[]>([]);
  const [rows, setRows] = useState<InventoryMovement[]>([]);
  const [warehouseId, setWarehouseId] = useState("");
  const [itemId, setItemId] = useState("");
  const [type, setType] = useState("");
  const [referenceType, setReferenceType] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    if (!accessToken || !currentOrganization || !currentLocation || permissionsLoading) return;
if (!canReadMovements) return;
    Promise.all([
      api.listInventoryWarehouses(currentOrganization.id, accessToken),
      api.listInventoryItems(currentOrganization.id, accessToken),
      api.listInventoryMovements(currentOrganization.id, accessToken, {
        locationId: currentLocation.id,
        warehouseId: warehouseId || undefined,
        inventoryItemId: itemId || undefined,
        type: type || undefined,
        referenceType: referenceType || undefined,
        dateFrom: dateFrom ? new Date(`${dateFrom}T00:00:00`).toISOString() : undefined,
        dateTo: dateTo ? new Date(`${dateTo}T23:59:59.999`).toISOString() : undefined,
      }),
    ]).then(([nextWarehouses, nextItems, nextRows]) => {
      if (cancelled) return;
      setWarehouses(nextWarehouses.filter((warehouse) => warehouse.location_id === currentLocation.id));
      setItems(nextItems);
      setRows(nextRows);
    }).catch((caught) => {
      if (!cancelled) setError(caught instanceof Error ? caught.message : "Unable to load movements");
    }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [accessToken, canReadMovements, currentLocation, currentOrganization, dateFrom, dateTo, itemId, permissionsLoading, referenceType, type, warehouseId]);

  return (
    <>
      <header className="inventory-header"><div><h1>Movements</h1><p>Every stock change across this location.</p></div></header>
      <div className="operation-filters">
        <label><span>Warehouse</span><select value={warehouseId} onChange={(event) => setWarehouseId(event.target.value)}><option value="">All warehouses</option>{warehouses.map((warehouse) => <option key={warehouse.id} value={warehouse.id}>{warehouse.name}</option>)}</select></label>
        <label><span>Item</span><select value={itemId} onChange={(event) => setItemId(event.target.value)}><option value="">All items</option>{items.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label><span>Type</span><select value={type} onChange={(event) => setType(event.target.value)}><option value="">All types</option>{["SALE", "PURCHASE", "WRITE_OFF", "ADJUSTMENT", "TRANSFER_OUT", "TRANSFER_IN", "RETURN_OUT"].map((value) => <option key={value} value={value}>{formatTransactionType(value)}</option>)}</select></label>
        <label><span>Reference</span><select value={referenceType} onChange={(event) => setReferenceType(event.target.value)}><option value="">All references</option>{["ORDER", "GOODS_RECEIPT", "WRITE_OFF", "INVENTORY_COUNT", "TRANSFER", "SUPPLIER_RETURN"].map((value) => <option key={value} value={value}>{formatTransactionType(value)}</option>)}</select></label>
        <label><span>From</span><input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} /></label>
        <label><span>To</span><input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} /></label>
      </div>
      {!permissionsLoading && !canReadMovements ? (
        <div className="inventory-state"><strong>Movement access required</strong><span>Your role cannot view the movement report.</span></div>
      ) : error ? (
        <div className="inventory-state is-error" role="alert"><strong>Movements could not be loaded.</strong><span>{error}</span></div>
      ) : loading ? (
        <div className="inventory-state" aria-live="polite">Loading movements…</div>
      ) : rows.length === 0 ? (
        <div className="inventory-state"><strong>No movements found</strong><span>Try a different warehouse, item, type, or date range.</span></div>
      ) : (
        <div className="inventory-table-wrap" tabIndex={0} aria-label="Inventory movements table">
          <table className="inventory-table operation-table">
            <caption className="sr-only">Inventory movements for the selected filters</caption>
            <thead><tr><th>Date</th><th>Item</th><th>Type</th><th>Quantity</th><th>Cost</th><th>Reference</th></tr></thead>
            <tbody>{rows.map((row) => <tr key={row.line_id ?? `${row.transaction_id}:${row.inventory_item_id}`}>
              <td>{formatInventoryDate(row.posted_at)}</td>
              <td><strong>{row.item_name}</strong></td>
              <td>{formatTransactionType(row.type)}</td>
              <td className={row.quantity_delta.startsWith("-") ? "inventory-quantity is-negative" : "inventory-quantity is-positive"}>{formatInventoryQuantity(row.quantity_delta, row.unit_code, true)}</td>
              <td>{formatInventoryMoney(row.total_cost_amount, currentOrganization?.currency_code ?? "KZT")}</td>
              <td>{row.reference_type ? `${row.reference_type}${row.reference_id ? ` · ${row.reference_id.slice(0, 8)}` : ""}` : "—"}</td>
            </tr>)}</tbody>
          </table>
        </div>
      )}
    </>
  );
}
