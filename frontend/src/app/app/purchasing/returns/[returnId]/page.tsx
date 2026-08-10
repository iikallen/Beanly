"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { usePurchasingPermissions } from "@/hooks/use-purchasing-permissions";
import { api, type InventoryItemResponse, type SupplierReturn, type WarehouseResponse } from "@/lib/api";
import { formatMoneyMinor, formatPurchaseDate, formatPurchaseStatus, formatPurchaseUnit, statusClass } from "@/lib/purchasing";

export default function SupplierReturnDetailPage() {
  const { returnId } = useParams<{ returnId: string }>();
  const { accessToken } = useAuth();
  const { currentOrganization } = useWorkspace();
  const { canRead, canReturn, loading: permissionsLoading } = usePurchasingPermissions();
  const [document, setDocument] = useState<SupplierReturn | null>(null);
  const [items, setItems] = useState<InventoryItemResponse[]>([]);
  const [warehouses, setWarehouses] = useState<WarehouseResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let cancelled = false;
    if (!accessToken || !currentOrganization || permissionsLoading) return;
    if (!canRead) return;
    Promise.all([api.getSupplierReturn(returnId, currentOrganization.id, accessToken), api.listInventoryItems(currentOrganization.id, accessToken), api.listInventoryWarehouses(currentOrganization.id, accessToken)])
      .then(([nextDocument, nextItems, nextWarehouses]) => { if (!cancelled) { setDocument(nextDocument); setItems(nextItems); setWarehouses(nextWarehouses); } })
      .catch((caught) => { if (!cancelled) setError(caught instanceof Error ? caught.message : "Unable to load supplier return"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [accessToken, canRead, currentOrganization, permissionsLoading, returnId]);
  const itemNames = useMemo(() => new Map(items.map((item) => [item.id, item.name])), [items]);
  async function act(action: "post" | "reverse") { if (!accessToken || !currentOrganization || !document) return; setSaving(true); setError(""); try { setDocument(action === "post" ? await api.postSupplierReturn(document.id, currentOrganization.id, accessToken) : await api.reverseSupplierReturn(document.id, currentOrganization.id, accessToken)); } catch (caught) { setError(caught instanceof Error ? caught.message : `Unable to ${action} supplier return`); } finally { setSaving(false); } }
  if (permissionsLoading) return <div className="purchasing-state" aria-live="polite">Checking access…</div>;
  if (!canRead) return <div className="purchasing-state"><strong>Purchasing access required</strong></div>;
  if (loading) return <div className="purchasing-state" aria-live="polite">Loading supplier return…</div>;
  if (error && !document) return <div className="purchasing-state is-error" role="alert"><strong>Supplier return could not be loaded.</strong><span>{error}</span></div>;
  if (!document) return null;
  return <>
    <Link className="purchasing-back" href="/app/purchasing/returns"><ArrowLeft aria-hidden="true" /> Supplier Returns</Link>
    <header className="purchasing-header"><div><span className={statusClass(document.status)}>{formatPurchaseStatus(document.status)}</span><h1>{document.number}</h1><p>{document.supplier_name ?? "Supplier"} · {formatPurchaseDate(document.returned_at)}</p></div>{canReturn && <div className="purchase-header-actions">{document.status === "DRAFT" && <button className="purchasing-primary" type="button" disabled={saving} onClick={() => void act("post")}>Post return</button>}{document.status === "POSTED" && <button className="secondary-button is-danger" type="button" disabled={saving} onClick={() => void act("reverse")}>Reverse return</button>}</div>}</header>
    {error && <div className="purchase-inline-alert is-error" role="alert">{error}</div>}
    <dl className="purchase-document-meta"><div><dt>Original receipt</dt><dd>{document.goods_receipt_number ?? "—"}</dd></div><div><dt>Warehouse</dt><dd>{warehouses.find((warehouse) => warehouse.id === document.warehouse_id)?.name ?? "Warehouse"}</dd></div><div><dt>Supplier document</dt><dd>{document.document_number || "—"}</dd></div><div><dt>Total</dt><dd>{formatMoneyMinor(document.total_minor, currentOrganization?.currency_code ?? "KZT")}</dd></div></dl>
    {document.note && <div className="purchase-document-note"><strong>Comment</strong><p>{document.note}</p></div>}
    <div className="purchasing-table-wrap"><table className="purchasing-table"><thead><tr><th>Item</th><th>Return quantity</th><th>Supplier price</th><th>Line total</th></tr></thead><tbody>{document.lines.map((line) => <tr key={line.id}><td>{line.item_name ?? itemNames.get(line.inventory_item_id) ?? "Inventory item"}</td><td>{line.return_quantity} {formatPurchaseUnit(line.purchase_unit)}</td><td>{line.unit_price} / {formatPurchaseUnit(line.purchase_unit)}</td><td>{formatMoneyMinor(line.line_total_minor, currentOrganization?.currency_code ?? "KZT")}</td></tr>)}</tbody></table></div>
  </>;
}
