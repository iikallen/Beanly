"use client";

import { ArrowLeft, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { useInventoryPermissions } from "@/hooks/use-inventory-permissions";
import { ApiError, api, type InventoryCount, type InventoryItemResponse, type InventoryUnitCode, type StockRow } from "@/lib/api";
import { formatBaseInventoryQuantity, formatInventoryDate, formatInventoryMoney } from "@/lib/inventory";
import { decimalDifference } from "@/lib/inventory-operations";

type ChangedItem = { inventory_item_id: string; expected_at_start: string; current: string };

export default function InventoryCountDetailPage() {
  const { countId } = useParams<{ countId: string }>();
  const { accessToken } = useAuth();
  const { currentOrganization } = useWorkspace();
  const { canCount, canRead, loading: permissionsLoading } = useInventoryPermissions();
  const [document, setDocument] = useState<InventoryCount | null>(null);
  const [items, setItems] = useState<InventoryItemResponse[]>([]);
  const [stock, setStock] = useState<StockRow[]>([]);
  const [actual, setActual] = useState<Record<string, string>>({});
  const [costs, setCosts] = useState<Record<string, string>>({});
  const [changedItems, setChangedItems] = useState<ChangedItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let cancelled = false;
    if (!accessToken || !currentOrganization || permissionsLoading) return;
    if (!canRead) return;
    Promise.all([api.getInventoryCount(countId, currentOrganization.id, accessToken), api.listInventoryItems(currentOrganization.id, accessToken)])
      .then(([nextDocument, nextItems]) => {
        if (cancelled) return;
        setDocument(nextDocument); setItems(nextItems);
        setActual(Object.fromEntries(nextDocument.lines.map((line) => [line.inventory_item_id, line.counted_quantity ?? ""])));
        setCosts(Object.fromEntries(nextDocument.lines.map((line) => [line.inventory_item_id, line.unit_cost_amount ?? ""])));
      }).catch((caught) => { if (!cancelled) setError(caught instanceof Error ? caught.message : "Unable to load inventory count"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [accessToken, canRead, countId, currentOrganization, permissionsLoading]);
  useEffect(() => {
    let cancelled = false;
    if (!accessToken || !currentOrganization || !document?.warehouse_id) return;
    api.listStock(currentOrganization.id, accessToken, { warehouseId: document.warehouse_id })
      .then((rows) => { if (!cancelled) setStock(rows); })
      .catch(() => { if (!cancelled) setStock([]); });
    return () => { cancelled = true; };
  }, [accessToken, currentOrganization, document?.warehouse_id]);
  const itemMap = useMemo(() => new Map(items.map((item) => [item.id, item])), [items]);
  const stockMap = useMemo(() => new Map(stock.map((row) => [row.inventory_item_id, row])), [stock]);
  const costFor = (line: InventoryCount["lines"][number]) => line.unit_cost_amount ?? stockMap.get(line.inventory_item_id)?.average_unit_cost ?? costs[line.inventory_item_id] ?? null;
  const expectedValue = document && document.lines.every((line) => costFor(line) !== null)
    ? document.lines.reduce((sum, line) => sum + Number(line.expected_quantity) * Number(costFor(line)), 0)
    : null;
  const variance = document?.status === "POSTED"
    ? document.lines.reduce((sum, line) => sum + Number(line.difference_cost_amount ?? 0), 0)
    : document && document.lines.every((line) => actual[line.inventory_item_id]?.trim() && costFor(line) !== null)
      ? document.lines.reduce((sum, line) => sum + Number(decimalDifference(actual[line.inventory_item_id], line.expected_quantity)) * Number(costFor(line)), 0)
      : null;

  function linePayload() {
    if (!document) return null;
    const invalid = document.lines.some((line) => !/^\d+(?:\.\d{1,6})?$/.test((actual[line.inventory_item_id] ?? "").trim()));
    if (invalid) { setError("Enter an actual quantity of zero or more for every item."); return null; }
    return document.lines.map((line) => ({
      inventory_item_id: line.inventory_item_id,
      counted_quantity: actual[line.inventory_item_id].trim(),
      unit: (line.base_unit ?? line.unit_code ?? itemMap.get(line.inventory_item_id)?.base_unit ?? "pcs") as InventoryUnitCode,
      ...(costs[line.inventory_item_id]?.trim() ? { unit_cost_amount: costs[line.inventory_item_id].trim() } : {}),
    }));
  }

  async function save() {
    if (!accessToken || !currentOrganization || !document) return false;
    const lines = linePayload();
    if (!lines) return false;
    setSaving(true); setError("");
    try { setDocument(await api.updateInventoryCountLines(document.id, lines, currentOrganization.id, accessToken)); return true; }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to save count"); return false; }
    finally { setSaving(false); }
  }

  async function post(confirmStockChanges: boolean) {
    if (!accessToken || !currentOrganization || !document) return;
    if (!confirmStockChanges && !(await save())) return;
    setSaving(true); setError("");
    try { setDocument(await api.postInventoryCount(document.id, confirmStockChanges, currentOrganization.id, accessToken)); setChangedItems([]); }
    catch (caught) {
      if (caught instanceof ApiError && caught.status === 409 && (caught.code === "INVENTORY_COUNT_CHANGED" || staleItems(caught.detail).length)) {
        setChangedItems(staleItems(caught.detail));
      } else setError(caught instanceof Error ? caught.message : "Unable to post count");
    } finally { setSaving(false); }
  }

  async function cancel() {
    if (!accessToken || !currentOrganization || !document) return;
    setSaving(true); setError("");
    try { setDocument(await api.cancelInventoryCount(document.id, currentOrganization.id, accessToken)); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to cancel count"); }
    finally { setSaving(false); }
  }

  if (permissionsLoading) return <div className="inventory-state" aria-live="polite">Checking access…</div>;
  if (!canRead) return <div className="inventory-state"><strong>Inventory access required</strong></div>;
  if (loading) return <div className="inventory-state" aria-live="polite">Loading inventory count…</div>;
  if (error && !document) return <div className="inventory-state is-error" role="alert"><strong>Inventory count could not be loaded.</strong><span>{error}</span></div>;
  if (!document) return null;
  return <>
    <Link className="inventory-back-link" href="/app/inventory/counts"><ArrowLeft aria-hidden="true" /> Inventory Counts</Link>
    <header className="inventory-header operation-page-header"><div><span className="eyebrow">{document.status} · {document.type}</span><h1>{document.number}</h1><p>Snapshot {formatInventoryDate(document.snapshot_at)}</p></div></header>
    {error && <div className="purchase-inline-alert is-error" role="alert">{error}</div>}
    {changedItems.length > 0 && <section className="stale-count-alert" role="alertdialog" aria-labelledby="stale-count-title"><TriangleAlert aria-hidden="true" /><div><h2 id="stale-count-title">Stock changed while you were counting.</h2>{changedItems.map((changed) => { const item = itemMap.get(changed.inventory_item_id); const unit = item?.base_unit ?? "pcs"; return <p key={changed.inventory_item_id}><strong>{item?.name ?? "Inventory item"}</strong>: {formatBaseInventoryQuantity(changed.expected_at_start, unit)} → {formatBaseInventoryQuantity(changed.current, unit)}</p>; })}<div className="operation-actions compact"><button className="secondary-button" type="button" onClick={() => setChangedItems([])}>Review count</button><button className="inventory-adjust-button" type="button" disabled={saving} onClick={() => void post(true)}>Post anyway</button></div></div></section>}
    <div className="inventory-table-wrap">
      <table className="inventory-table count-table">
        <thead><tr><th>Item</th><th>Expected</th><th>Actual</th><th>Difference</th><th>Unit cost</th></tr></thead>
        <tbody>{document.lines.map((line) => {
          const item = itemMap.get(line.inventory_item_id);
          const unit = (line.base_unit ?? line.unit_code ?? item?.base_unit ?? "pcs") as InventoryUnitCode;
          const difference = document.status === "POSTED" ? line.difference_quantity ?? "0" : decimalDifference(actual[line.inventory_item_id] ?? "", line.expected_quantity);
          const availableCost = costFor(line);
          const needsCost = difference !== "—" && Number(difference) > 0 && availableCost === null;
          return <tr key={line.id}>
            <td><strong>{line.item_name ?? item?.name ?? "Inventory item"}</strong></td>
            <td>{formatBaseInventoryQuantity(line.expected_quantity, unit)}</td>
            <td>{document.status === "COUNTING" && canCount ? <label className="count-quantity-input"><span className="sr-only">Actual quantity for {item?.name}</span><input inputMode="decimal" value={actual[line.inventory_item_id] ?? ""} onChange={(event) => setActual((current) => ({ ...current, [line.inventory_item_id]: event.target.value }))} /><span aria-hidden="true">{unit === "l" ? "L" : unit}</span></label> : line.counted_quantity === null ? "Not counted" : formatBaseInventoryQuantity(line.counted_quantity, unit)}</td>
            <td className={difference.startsWith("-") ? "is-negative" : difference !== "—" && difference !== "0" ? "is-positive" : ""}>{difference === "—" ? difference : formatBaseInventoryQuantity(difference, unit, true)}</td>
            <td>{needsCost && document.status === "COUNTING" && canCount ? <label><span className="sr-only">Unit cost for {item?.name}</span><input inputMode="decimal" value={costs[line.inventory_item_id] ?? ""} onChange={(event) => setCosts((current) => ({ ...current, [line.inventory_item_id]: event.target.value }))} placeholder="Required" /></label> : formatInventoryMoney(availableCost, currentOrganization?.currency_code ?? "KZT")}</td>
          </tr>;
        })}</tbody>
      </table>
    </div>
    <section className="count-value-summary" aria-label="Count value summary"><div><span>Expected value</span><strong>{formatInventoryMoney(expectedValue === null ? null : String(expectedValue), currentOrganization?.currency_code ?? "KZT")}</strong></div><div><span>Variance</span><strong className={variance !== null && variance < 0 ? "is-negative" : ""}>{formatInventoryMoney(variance === null ? null : String(variance), currentOrganization?.currency_code ?? "KZT")}</strong></div></section>
    {document.status === "COUNTING" && canCount && <div className="operation-actions count-actions"><button className="secondary-button is-danger" type="button" disabled={saving} onClick={() => void cancel()}>Cancel count</button><button className="secondary-button" type="button" disabled={saving} onClick={() => void save()}>Save progress</button><button className="inventory-adjust-button" type="button" disabled={saving} onClick={() => void post(false)}>{saving ? "Saving…" : "Post inventory count"}</button></div>}
  </>;
}

function staleItems(detail: unknown): ChangedItem[] {
  if (!detail || typeof detail !== "object") return [];
  const items = (detail as { changed_items?: unknown }).changed_items;
  if (!Array.isArray(items)) return [];
  return items.filter((item): item is ChangedItem => Boolean(item && typeof item === "object" && typeof (item as ChangedItem).inventory_item_id === "string"));
}
