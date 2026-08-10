"use client";

import { ArrowLeft, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, useEffect, useMemo, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { emptyInventoryLine, InventoryLinesEditor, type InventoryLineValue } from "@/components/inventory-lines-editor";
import { useWorkspace } from "@/components/workspace-provider";
import { useInventoryPermissions } from "@/hooks/use-inventory-permissions";
import { api, type InventoryItemResponse, type StockRow, type WarehouseResponse } from "@/lib/api";
import { formatInventoryMoney, formatInventoryQuantity } from "@/lib/inventory";
import { localDateTimeNow, toApiDate, validOperationLines } from "@/lib/inventory-operations";

export default function NewTransferPage() {
  const { accessToken } = useAuth();
  const { currentOrganization, locations } = useWorkspace();
  const { canTransfer, loading: permissionsLoading } = useInventoryPermissions();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [warehouses, setWarehouses] = useState<WarehouseResponse[]>([]);
  const [items, setItems] = useState<InventoryItemResponse[]>([]);
  const [stock, setStock] = useState<StockRow[]>([]);
  const [sourceId, setSourceId] = useState("");
  const [destinationId, setDestinationId] = useState("");
  const [occurredAt, setOccurredAt] = useState(localDateTimeNow);
  const [note, setNote] = useState("");
  const [lines, setLines] = useState<InventoryLineValue[]>([emptyInventoryLine()]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let cancelled = false;
    if (!accessToken || !currentOrganization || permissionsLoading) return;
if (!canTransfer) return;
    Promise.all([api.listInventoryWarehouses(currentOrganization.id, accessToken), api.listInventoryItems(currentOrganization.id, accessToken)])
      .then(([nextWarehouses, nextItems]) => { if (!cancelled) { const active = nextWarehouses.filter((warehouse) => warehouse.is_active); const requested = active.find((warehouse) => warehouse.id === searchParams.get("source_warehouse_id"))?.id ?? active[0]?.id ?? ""; setWarehouses(active); setItems(nextItems.filter((item) => item.is_active)); setSourceId(requested); setDestinationId(active.find((warehouse) => warehouse.id !== requested)?.id ?? ""); } })
      .catch((caught) => { if (!cancelled) setError(caught instanceof Error ? caught.message : "Unable to prepare transfer"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [accessToken, canTransfer, currentOrganization, permissionsLoading, searchParams]);
  useEffect(() => {
    let cancelled = false;
    if (!accessToken || !currentOrganization || !sourceId) return;
    api.listStock(currentOrganization.id, accessToken, { warehouseId: sourceId }).then((rows) => { if (!cancelled) setStock(rows); }).catch(() => { if (!cancelled) setStock([]); });
    return () => { cancelled = true; };
  }, [accessToken, currentOrganization, sourceId]);
  const locationNames = useMemo(() => new Map(locations.map((location) => [location.id, location.name])), [locations]);
  const stockMap = useMemo(() => new Map(stock.map((row) => [row.inventory_item_id, row])), [stock]);
  const warnings = lines.flatMap((line) => { const item = items.find((candidate) => candidate.id === line.inventoryItemId); const row = stockMap.get(line.inventoryItemId); if (!item || !row || !line.quantity) return []; const after = Number(row.quantity) - toBaseQuantity(Number(line.quantity), line.unit, item.base_unit); return after < 0 ? [`${item.name} will become ${formatInventoryQuantity(String(after), item.base_unit)}`] : []; });
  const estimatedValue = lines.reduce((total, line) => { const item = items.find((candidate) => candidate.id === line.inventoryItemId); const row = stockMap.get(line.inventoryItemId); if (!item || !row?.average_unit_cost) return total; return total + toBaseQuantity(Number(line.quantity || 0), line.unit, item.base_unit) * Number(row.average_unit_cost); }, 0);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const action = (event.nativeEvent as SubmitEvent).submitter?.getAttribute("data-action");
    if (!accessToken || !currentOrganization || !sourceId || !destinationId || sourceId === destinationId || !validOperationLines(lines)) { setError("Choose different source and destination warehouses and enter positive quantities."); return; }
    if (new Set(lines.map((line) => line.inventoryItemId)).size !== lines.length) { setError("Each item can appear only once."); return; }
    setSaving(true); setError("");
    try { let created = await api.createInventoryTransfer({ source_warehouse_id: sourceId, destination_warehouse_id: destinationId, occurred_at: toApiDate(occurredAt), note: note.trim() || null, lines: lines.map((line) => ({ inventory_item_id: line.inventoryItemId, quantity: line.quantity.trim(), unit: line.unit })) }, currentOrganization.id, accessToken); if (action === "post") created = await api.postInventoryTransfer(created.id, currentOrganization.id, accessToken); router.push(`/app/inventory/transfers/${created.id}`); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to save transfer"); setSaving(false); }
  }
  function warehouseLabel(warehouse: WarehouseResponse) { return `${locationNames.get(warehouse.location_id) ?? "Location"} / ${warehouse.name}`; }
  if (permissionsLoading) return <div className="inventory-state" aria-live="polite">Checking access…</div>;
  if (!canTransfer) return <div className="inventory-state"><strong>Transfer access required</strong></div>;
  if (loading) return <div className="inventory-state" aria-live="polite">Preparing transfer…</div>;
  return <>
    <Link className="inventory-back-link" href="/app/inventory/transfers"><ArrowLeft aria-hidden="true" /> Transfers</Link>
    <header className="inventory-header operation-page-header"><div><h1>New transfer</h1><p>Move stock between warehouses in one atomic posting.</p></div></header>
    <form className="operation-form" onSubmit={submit}>
      <div className="operation-form-grid"><label><span>From</span><select value={sourceId} onChange={(event) => { setSourceId(event.target.value); setStock([]); if (event.target.value === destinationId) setDestinationId(""); }} required><option value="">Select source</option>{warehouses.map((warehouse) => <option key={warehouse.id} value={warehouse.id}>{warehouseLabel(warehouse)}</option>)}</select></label><label><span>To</span><select value={destinationId} onChange={(event) => setDestinationId(event.target.value)} required><option value="">Select destination</option>{warehouses.filter((warehouse) => warehouse.id !== sourceId).map((warehouse) => <option key={warehouse.id} value={warehouse.id}>{warehouseLabel(warehouse)}</option>)}</select></label><label><span>Date</span><input type="datetime-local" value={occurredAt} onChange={(event) => setOccurredAt(event.target.value)} required /></label></div>
      <InventoryLinesEditor items={items} lines={lines} onChange={setLines} disabled={saving} />
      {warnings.length > 0 && <div className="transfer-warnings" role="status">{warnings.map((warning) => <p key={warning}><TriangleAlert aria-hidden="true" /> {warning}</p>)}<small>Negative source stock is allowed.</small></div>}
      <div className="operation-estimate"><span>Estimated value</span><strong>{formatInventoryMoney(String(estimatedValue), currentOrganization?.currency_code ?? "KZT")}</strong></div>
      <label className="operation-note"><span>Comment</span><textarea value={note} onChange={(event) => setNote(event.target.value)} placeholder="Optional transfer note" /></label>
      {error && <div className="purchase-inline-alert is-error" role="alert">{error}</div>}
      <div className="operation-actions"><button className="secondary-button" type="submit" data-action="draft" disabled={saving}>Save draft</button><button className="inventory-adjust-button" type="submit" data-action="post" disabled={saving}>{saving ? "Saving…" : "Post transfer"}</button></div>
    </form>
  </>;
}

function toBaseQuantity(quantity: number, unit: string, baseUnit: string) {
  if ((unit === "kg" && baseUnit === "g") || (unit === "l" && baseUnit === "ml")) return quantity * 1000;
  if ((unit === "g" && baseUnit === "kg") || (unit === "ml" && baseUnit === "l")) return quantity / 1000;
  return quantity;
}
