"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { useInventoryPermissions } from "@/hooks/use-inventory-permissions";
import { api, type InventoryItemResponse, type InventoryWriteOff, type WriteOffReason } from "@/lib/api";
import { formatInventoryDate, formatInventoryMoney, formatInventoryQuantity } from "@/lib/inventory";

export default function WriteOffDetailPage() {
  const { writeOffId } = useParams<{ writeOffId: string }>();
  const { accessToken } = useAuth();
  const { currentOrganization } = useWorkspace();
  const { canRead, canWriteOff, loading: permissionsLoading } = useInventoryPermissions();
  const [document, setDocument] = useState<InventoryWriteOff | null>(null);
  const [items, setItems] = useState<InventoryItemResponse[]>([]);
  const [reasons, setReasons] = useState<WriteOffReason[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let cancelled = false;
    if (!accessToken || !currentOrganization || permissionsLoading) return;
    if (!canRead) return;
    Promise.all([api.getWriteOff(writeOffId, currentOrganization.id, accessToken), api.listInventoryItems(currentOrganization.id, accessToken), api.listWriteOffReasons(currentOrganization.id, accessToken, true)])
      .then(([nextDocument, nextItems, nextReasons]) => { if (!cancelled) { setDocument(nextDocument); setItems(nextItems); setReasons(nextReasons); } })
      .catch((caught) => { if (!cancelled) setError(caught instanceof Error ? caught.message : "Unable to load write-off"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [accessToken, canRead, currentOrganization, permissionsLoading, writeOffId]);
  const itemNames = useMemo(() => new Map(items.map((item) => [item.id, item.name])), [items]);
  const reason = reasons.find((candidate) => candidate.id === document?.reason_id)?.name ?? document?.reason_name ?? "—";
  async function act(action: "post" | "reverse") {
    if (!accessToken || !currentOrganization || !document) return;
    setSaving(true); setError("");
    try { setDocument(action === "post" ? await api.postWriteOff(document.id, currentOrganization.id, accessToken) : await api.reverseWriteOff(document.id, currentOrganization.id, accessToken)); }
    catch (caught) { setError(caught instanceof Error ? caught.message : `Unable to ${action} write-off`); }
    finally { setSaving(false); }
  }
  if (permissionsLoading) return <div className="inventory-state" aria-live="polite">Checking access…</div>;
  if (!canRead) return <div className="inventory-state"><strong>Inventory access required</strong></div>;
  if (loading) return <div className="inventory-state" aria-live="polite">Loading write-off…</div>;
  if (error && !document) return <div className="inventory-state is-error" role="alert"><strong>Write-off could not be loaded.</strong><span>{error}</span></div>;
  if (!document) return null;
  return <>
    <Link className="inventory-back-link" href="/app/inventory/write-offs"><ArrowLeft aria-hidden="true" /> Write-offs</Link>
    <header className="inventory-header operation-page-header"><div><span className="eyebrow">{document.status}</span><h1>{document.number}</h1><p>{reason} · {formatInventoryDate(document.occurred_at)}</p></div>{canWriteOff && <div className="operation-actions compact">{document.status === "DRAFT" && <button className="inventory-adjust-button" type="button" disabled={saving} onClick={() => void act("post")}>Post write-off</button>}{document.status === "POSTED" && <button className="secondary-button is-danger" type="button" disabled={saving} onClick={() => void act("reverse")}>Reverse write-off</button>}</div>}</header>
    {error && <div className="purchase-inline-alert is-error" role="alert">{error}</div>}
    <dl className="operation-summary"><div><dt>Reason</dt><dd>{reason}</dd></div><div><dt>Total stock cost</dt><dd>{formatInventoryMoney(document.total_cost_amount, currentOrganization?.currency_code ?? "KZT")}</dd></div><div><dt>Comment</dt><dd>{document.note || "—"}</dd></div></dl>
    <div className="inventory-table-wrap"><table className="inventory-table operation-lines-table"><thead><tr><th>Item</th><th>Quantity</th></tr></thead><tbody>{document.lines.map((line) => <tr key={line.id}><td>{line.item_name ?? itemNames.get(line.inventory_item_id) ?? "Inventory item"}</td><td>{formatInventoryQuantity(line.quantity, line.unit_code)}</td></tr>)}</tbody></table></div>
  </>;
}
