"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { useInventoryPermissions } from "@/hooks/use-inventory-permissions";
import { api, type InventoryItemResponse, type InventoryTransfer, type WarehouseResponse } from "@/lib/api";
import { formatInventoryDate, formatInventoryQuantity } from "@/lib/inventory";

export default function TransferDetailPage() {
  const { transferId } = useParams<{ transferId: string }>();
  const { accessToken } = useAuth();
  const { currentOrganization, locations } = useWorkspace();
  const { canRead, canTransfer, loading: permissionsLoading } = useInventoryPermissions();
  const [document, setDocument] = useState<InventoryTransfer | null>(null);
  const [warehouses, setWarehouses] = useState<WarehouseResponse[]>([]);
  const [items, setItems] = useState<InventoryItemResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let cancelled = false;
    if (!accessToken || !currentOrganization || permissionsLoading) return;
    if (!canRead) return;
    Promise.all([api.getInventoryTransfer(transferId, currentOrganization.id, accessToken), api.listInventoryWarehouses(currentOrganization.id, accessToken), api.listInventoryItems(currentOrganization.id, accessToken)])
      .then(([nextDocument, nextWarehouses, nextItems]) => { if (!cancelled) { setDocument(nextDocument); setWarehouses(nextWarehouses); setItems(nextItems); } })
      .catch((caught) => { if (!cancelled) setError(caught instanceof Error ? caught.message : "Unable to load transfer"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [accessToken, canRead, currentOrganization, permissionsLoading, transferId]);
  const warehouseMap = useMemo(() => new Map(warehouses.map((warehouse) => [warehouse.id, warehouse])), [warehouses]);
  const locationMap = useMemo(() => new Map(locations.map((location) => [location.id, location.name])), [locations]);
  const itemMap = useMemo(() => new Map(items.map((item) => [item.id, item])), [items]);
  function warehouseLabel(id: string) { const warehouse = warehouseMap.get(id); return warehouse ? `${locationMap.get(warehouse.location_id) ?? "Location"} / ${warehouse.name}` : "Warehouse"; }
  async function act(action: "post" | "reverse") { if (!accessToken || !currentOrganization || !document) return; setSaving(true); setError(""); try { setDocument(action === "post" ? await api.postInventoryTransfer(document.id, currentOrganization.id, accessToken) : await api.reverseInventoryTransfer(document.id, currentOrganization.id, accessToken)); } catch (caught) { setError(caught instanceof Error ? caught.message : `Unable to ${action} transfer`); } finally { setSaving(false); } }
  if (permissionsLoading) return <div className="inventory-state" aria-live="polite">Checking access…</div>;
  if (!canRead) return <div className="inventory-state"><strong>Inventory access required</strong></div>;
  if (loading) return <div className="inventory-state" aria-live="polite">Loading transfer…</div>;
  if (error && !document) return <div className="inventory-state is-error" role="alert"><strong>Transfer could not be loaded.</strong><span>{error}</span></div>;
  if (!document) return null;
  return <>
    <Link className="inventory-back-link" href="/app/inventory/transfers"><ArrowLeft aria-hidden="true" /> Transfers</Link>
    <header className="inventory-header operation-page-header"><div><span className="eyebrow">{document.status}</span><h1>{document.number}</h1><p>{formatInventoryDate(document.occurred_at)}</p></div>{canTransfer && <div className="operation-actions compact">{document.status === "DRAFT" && <button className="inventory-adjust-button" type="button" disabled={saving} onClick={() => void act("post")}>Post transfer</button>}{document.status === "POSTED" && <button className="secondary-button is-danger" type="button" disabled={saving} onClick={() => void act("reverse")}>Reverse transfer</button>}</div>}</header>
    {error && <div className="purchase-inline-alert is-error" role="alert">{error}</div>}
    <dl className="operation-summary"><div><dt>From</dt><dd>{warehouseLabel(document.source_warehouse_id)}</dd></div><div><dt>To</dt><dd>{warehouseLabel(document.destination_warehouse_id)}</dd></div><div><dt>Comment</dt><dd>{document.note || "—"}</dd></div></dl>
    <div className="inventory-table-wrap"><table className="inventory-table operation-lines-table"><thead><tr><th>Item</th><th>Quantity</th></tr></thead><tbody>{document.lines.map((line) => <tr key={line.id}><td>{line.item_name ?? itemMap.get(line.inventory_item_id)?.name ?? "Inventory item"}</td><td>{formatInventoryQuantity(line.quantity, line.unit_code)}</td></tr>)}</tbody></table></div>
  </>;
}
