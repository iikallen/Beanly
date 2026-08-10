"use client";

import { ArrowLeft, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { emptyInventoryLine, InventoryLinesEditor, type InventoryLineValue } from "@/components/inventory-lines-editor";
import { useWorkspace } from "@/components/workspace-provider";
import { useInventoryPermissions } from "@/hooks/use-inventory-permissions";
import { api, type InventoryItemResponse, type StockRow, type WarehouseResponse, type WriteOffReason } from "@/lib/api";
import { formatInventoryMoney } from "@/lib/inventory";
import { localDateTimeNow, toApiDate, validOperationLines } from "@/lib/inventory-operations";

export default function NewWriteOffPage() {
  const { accessToken } = useAuth();
  const { currentOrganization, currentLocation } = useWorkspace();
  const { canWriteOff, loading: permissionsLoading } = useInventoryPermissions();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [warehouses, setWarehouses] = useState<WarehouseResponse[]>([]);
  const [items, setItems] = useState<InventoryItemResponse[]>([]);
  const [reasons, setReasons] = useState<WriteOffReason[]>([]);
  const [stock, setStock] = useState<StockRow[] | null>(null);
  const [warehouseId, setWarehouseId] = useState("");
  const [reasonId, setReasonId] = useState("");
  const [occurredAt, setOccurredAt] = useState(localDateTimeNow);
  const [note, setNote] = useState("");
  const [lines, setLines] = useState<InventoryLineValue[]>([emptyInventoryLine()]);
  const [newReason, setNewReason] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    if (!accessToken || !currentOrganization || !currentLocation || permissionsLoading) return;
if (!canWriteOff) return;
    Promise.all([api.listInventoryWarehouses(currentOrganization.id, accessToken), api.listInventoryItems(currentOrganization.id, accessToken), api.listWriteOffReasons(currentOrganization.id, accessToken)])
      .then(([nextWarehouses, nextItems, nextReasons]) => {
        if (cancelled) return;
        const local = nextWarehouses.filter((warehouse) => warehouse.is_active && warehouse.location_id === currentLocation.id);
        setWarehouses(local); setItems(nextItems.filter((item) => item.is_active)); setReasons(nextReasons.filter((reason) => reason.is_active));
        setWarehouseId(local.find((warehouse) => warehouse.id === searchParams.get("warehouse_id"))?.id ?? local[0]?.id ?? "");
        setReasonId(nextReasons.find((reason) => reason.is_active)?.id ?? "");
      }).catch((caught) => { if (!cancelled) setError(caught instanceof Error ? caught.message : "Unable to prepare write-off"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [accessToken, canWriteOff, currentLocation, currentOrganization, permissionsLoading, searchParams]);
  useEffect(() => {
    let cancelled = false;
    if (!accessToken || !currentOrganization || !warehouseId) return;
    api.listStock(currentOrganization.id, accessToken, { warehouseId })
      .then((rows) => { if (!cancelled) setStock(rows); })
      .catch(() => { if (!cancelled) setStock(null); });
    return () => { cancelled = true; };
  }, [accessToken, currentOrganization, warehouseId]);

  const estimatedCost = stock === null ? null : lines.reduce((total, line) => {
    const item = items.find((candidate) => candidate.id === line.inventoryItemId);
    const row = stock.find((candidate) => candidate.inventory_item_id === line.inventoryItemId);
    if (!item || !row?.average_unit_cost) return total;
    return total + toBaseQuantity(Number(line.quantity || 0), line.unit, item.base_unit) * Number(row.average_unit_cost);
  }, 0);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const action = (event.nativeEvent as SubmitEvent).submitter?.getAttribute("data-action");
    if (!accessToken || !currentOrganization || !warehouseId || !reasonId || !validOperationLines(lines)) {
      setError("Choose a warehouse, reason, and enter a positive quantity for every item."); return;
    }
    if (new Set(lines.map((line) => line.inventoryItemId)).size !== lines.length) { setError("Each item can appear only once."); return; }
    setSaving(true); setError("");
    try {
      let created = await api.createWriteOff({ warehouse_id: warehouseId, reason_id: reasonId, occurred_at: toApiDate(occurredAt), note: note.trim() || null, lines: lines.map((line) => ({ inventory_item_id: line.inventoryItemId, quantity: line.quantity.trim(), unit: line.unit })) }, currentOrganization.id, accessToken);
      if (action === "post") created = await api.postWriteOff(created.id, currentOrganization.id, accessToken);
      router.push(`/app/inventory/write-offs/${created.id}`);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to save write-off"); setSaving(false); }
  }

  if (permissionsLoading) return <div className="inventory-state" aria-live="polite">Checking access…</div>;
  if (!canWriteOff) return <div className="inventory-state"><strong>Write-off access required</strong><span>Your role cannot create write-offs.</span></div>;
  if (loading) return <div className="inventory-state" aria-live="polite">Preparing write-off…</div>;
  return <>
    <Link className="inventory-back-link" href="/app/inventory/write-offs"><ArrowLeft aria-hidden="true" /> Write-offs</Link>
    <header className="inventory-header operation-page-header"><div><h1>New write-off</h1><p>Record the business reason; Beanly calculates stock cost from WAC.</p></div></header>
    <form className="operation-form" onSubmit={submit}>
      <div className="operation-form-grid">
        <label><span>Warehouse</span><select value={warehouseId} onChange={(event) => { setWarehouseId(event.target.value); setStock(null); }} required><option value="">Select warehouse</option>{warehouses.map((warehouse) => <option key={warehouse.id} value={warehouse.id}>{warehouse.name}</option>)}</select></label>
        <label><span>Reason</span><select value={reasonId} onChange={(event) => setReasonId(event.target.value)} required><option value="">Select reason</option>{reasons.map((reason) => <option key={reason.id} value={reason.id}>{reason.name}</option>)}</select></label>
        <label><span>Date</span><input type="datetime-local" value={occurredAt} onChange={(event) => setOccurredAt(event.target.value)} required /></label>
      </div>
      <div className="operation-inline-create"><label><span>New reason</span><input value={newReason} onChange={(event) => setNewReason(event.target.value)} maxLength={150} placeholder="For example: Spoilage" /></label><button type="button" disabled={!newReason.trim() || saving} onClick={async () => { if (!accessToken || !currentOrganization || !newReason.trim()) return; try { const reason = await api.createWriteOffReason(newReason.trim(), currentOrganization.id, accessToken); setReasons((current) => [...current, reason]); setReasonId(reason.id); setNewReason(""); } catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to add reason"); } }}><Plus aria-hidden="true" /> Add reason</button></div>
      <InventoryLinesEditor items={items} lines={lines} onChange={setLines} disabled={saving} />
      <div className="operation-estimate"><span>Estimated stock cost</span><strong>{formatInventoryMoney(estimatedCost === null ? null : String(estimatedCost), currentOrganization?.currency_code ?? "KZT")}</strong></div>
      <label className="operation-note"><span>Comment</span><textarea value={note} onChange={(event) => setNote(event.target.value)} placeholder="Optional context for this write-off" /></label>
      {error && <div className="purchase-inline-alert is-error" role="alert">{error}</div>}
      <div className="operation-actions"><button className="secondary-button" type="submit" data-action="draft" disabled={saving}>Save draft</button><button className="inventory-adjust-button" type="submit" data-action="post" disabled={saving}>{saving ? "Saving…" : "Post write-off"}</button></div>
    </form>
  </>;
}

function toBaseQuantity(quantity: number, unit: string, baseUnit: string) {
  if ((unit === "kg" && baseUnit === "g") || (unit === "l" && baseUnit === "ml")) return quantity * 1000;
  if ((unit === "g" && baseUnit === "kg") || (unit === "ml" && baseUnit === "l")) return quantity / 1000;
  return quantity;
}
