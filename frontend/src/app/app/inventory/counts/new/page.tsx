"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { useInventoryPermissions } from "@/hooks/use-inventory-permissions";
import { api, type InventoryCountType, type InventoryItemResponse, type WarehouseResponse } from "@/lib/api";

export default function NewInventoryCountPage() {
  const { accessToken } = useAuth();
  const { currentOrganization, currentLocation } = useWorkspace();
  const { canCount, loading: permissionsLoading } = useInventoryPermissions();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [warehouses, setWarehouses] = useState<WarehouseResponse[]>([]);
  const [items, setItems] = useState<InventoryItemResponse[]>([]);
  const [warehouseId, setWarehouseId] = useState("");
  const [type, setType] = useState<InventoryCountType>("FULL");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [note, setNote] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let cancelled = false;
    if (!accessToken || !currentOrganization || !currentLocation || permissionsLoading) return;
if (!canCount) return;
    Promise.all([api.listInventoryWarehouses(currentOrganization.id, accessToken), api.listInventoryItems(currentOrganization.id, accessToken)])
      .then(([nextWarehouses, nextItems]) => { if (!cancelled) { const local = nextWarehouses.filter((warehouse) => warehouse.is_active && warehouse.location_id === currentLocation.id); setWarehouses(local); setItems(nextItems.filter((item) => item.is_active)); setWarehouseId(local.find((warehouse) => warehouse.id === searchParams.get("warehouse_id"))?.id ?? local[0]?.id ?? ""); } })
      .catch((caught) => { if (!cancelled) setError(caught instanceof Error ? caught.message : "Unable to prepare inventory count"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [accessToken, canCount, currentLocation, currentOrganization, permissionsLoading, searchParams]);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!accessToken || !currentOrganization || !warehouseId || (type === "PARTIAL" && selectedIds.length === 0)) { setError(type === "PARTIAL" ? "Select at least one item." : "Select a warehouse."); return; }
    setSaving(true); setError("");
    try { const created = await api.createInventoryCount({ warehouse_id: warehouseId, type, ...(type === "PARTIAL" ? { inventory_item_ids: selectedIds } : {}), note: note.trim() || null }, currentOrganization.id, accessToken); router.push(`/app/inventory/counts/${created.id}`); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to start count"); setSaving(false); }
  }
  if (permissionsLoading) return <div className="inventory-state" aria-live="polite">Checking access…</div>;
  if (!canCount) return <div className="inventory-state"><strong>Inventory count access required</strong></div>;
  if (loading) return <div className="inventory-state" aria-live="polite">Preparing inventory count…</div>;
  return <>
    <Link className="inventory-back-link" href="/app/inventory/counts"><ArrowLeft aria-hidden="true" /> Inventory Counts</Link>
    <header className="inventory-header operation-page-header"><div><h1>New inventory count</h1><p>Choose a full count or count selected items.</p></div></header>
    <form className="operation-form" onSubmit={submit}>
      <label className="operation-field"><span>Warehouse</span><select value={warehouseId} onChange={(event) => setWarehouseId(event.target.value)} required><option value="">Select warehouse</option>{warehouses.map((warehouse) => <option key={warehouse.id} value={warehouse.id}>{warehouse.name}</option>)}</select></label>
      <fieldset className="count-type-selector"><legend>Type</legend><label><input type="radio" name="count-type" checked={type === "FULL"} onChange={() => setType("FULL")} /><span><strong>Full inventory</strong><small>All active items and archived items with stock</small></span></label><label><input type="radio" name="count-type" checked={type === "PARTIAL"} onChange={() => setType("PARTIAL")} /><span><strong>Selected items</strong><small>Count only the items you choose</small></span></label></fieldset>
      {type === "PARTIAL" && <fieldset className="count-item-selector"><legend>Items</legend>{items.length === 0 ? <p>No active inventory items.</p> : items.map((item) => <label key={item.id}><input type="checkbox" checked={selectedIds.includes(item.id)} onChange={(event) => setSelectedIds((current) => event.target.checked ? [...current, item.id] : current.filter((id) => id !== item.id))} /> {item.name} <small>{item.base_unit}</small></label>)}</fieldset>}
      <label className="operation-note"><span>Comment</span><textarea value={note} onChange={(event) => setNote(event.target.value)} placeholder="Optional counting note" /></label>
      {error && <div className="purchase-inline-alert is-error" role="alert">{error}</div>}
      <div className="operation-actions"><Link className="secondary-button" href="/app/inventory/counts">Cancel</Link><button className="inventory-adjust-button" type="submit" disabled={saving}>{saving ? "Starting…" : "Start count"}</button></div>
    </form>
  </>;
}
