"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useMemo, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { usePurchasingPermissions } from "@/hooks/use-purchasing-permissions";
import { api, type GoodsReceipt, type InventoryItemResponse, type Supplier, type WarehouseResponse } from "@/lib/api";
import { formatMoneyMinor, formatPurchaseUnit, isPositiveDecimal } from "@/lib/purchasing";
import { localDateTimeNow, toApiDate } from "@/lib/inventory-operations";

export default function NewSupplierReturnPage() {
  const { accessToken } = useAuth();
  const { currentOrganization, currentLocation } = useWorkspace();
  const { canReturn, loading: permissionsLoading } = usePurchasingPermissions();
  const router = useRouter();
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [receipts, setReceipts] = useState<GoodsReceipt[]>([]);
  const [receipt, setReceipt] = useState<GoodsReceipt | null>(null);
  const [items, setItems] = useState<InventoryItemResponse[]>([]);
  const [warehouses, setWarehouses] = useState<WarehouseResponse[]>([]);
  const [supplierId, setSupplierId] = useState("");
  const [receiptId, setReceiptId] = useState("");
  const [quantities, setQuantities] = useState<Record<string, string>>({});
  const [returnedAt, setReturnedAt] = useState(localDateTimeNow);
  const [documentNumber, setDocumentNumber] = useState("");
  const [note, setNote] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadingReceipts, setLoadingReceipts] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let cancelled = false;
    if (!accessToken || !currentOrganization || permissionsLoading) return;
    if (!canReturn) return;
    Promise.all([api.listSuppliers(currentOrganization.id, accessToken), api.listInventoryItems(currentOrganization.id, accessToken), api.listInventoryWarehouses(currentOrganization.id, accessToken)])
      .then(([nextSuppliers, nextItems, nextWarehouses]) => { if (!cancelled) { setSuppliers(nextSuppliers.filter((supplier) => supplier.is_active)); setItems(nextItems); setWarehouses(nextWarehouses); setSupplierId(nextSuppliers.find((supplier) => supplier.is_active)?.id ?? ""); } })
      .catch((caught) => { if (!cancelled) setError(caught instanceof Error ? caught.message : "Unable to prepare supplier return"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [accessToken, canReturn, currentOrganization, permissionsLoading]);
  useEffect(() => {
    let cancelled = false;
    if (!accessToken || !currentOrganization || !currentLocation || !supplierId) return;
    api.listGoodsReceipts(currentOrganization.id, accessToken, { supplierId, status: "POSTED" })
      .then((next) => { if (!cancelled) setReceipts(next.filter((candidate) => candidate.location_id === currentLocation.id)); })
      .catch((caught) => { if (!cancelled) setError(caught instanceof Error ? caught.message : "Unable to load receipts"); })
      .finally(() => { if (!cancelled) setLoadingReceipts(false); });
    return () => { cancelled = true; };
  }, [accessToken, currentLocation, currentOrganization, supplierId]);
  useEffect(() => {
    let cancelled = false;
    if (!accessToken || !currentOrganization || !receiptId) return;
    api.getGoodsReceipt(receiptId, currentOrganization.id, accessToken)
      .then((nextReceipt) => { if (!cancelled) setReceipt(nextReceipt); })
      .catch((caught) => { if (!cancelled) setError(caught instanceof Error ? caught.message : "Unable to load receipt details"); })
      .finally(() => { if (!cancelled) setLoadingReceipts(false); });
    return () => { cancelled = true; };
  }, [accessToken, currentOrganization, receiptId]);
  const itemNames = useMemo(() => new Map(items.map((item) => [item.id, item.name])), [items]);
  const warehouseName = warehouses.find((warehouse) => warehouse.id === receipt?.warehouse_id)?.name ?? "—";
  function alreadyReturned(line: GoodsReceipt["lines"][number]) { return Number(line.returned_base_quantity ?? 0) / Number(line.unit_multiplier); }
  function returnable(line: GoodsReceipt["lines"][number]) { return Number(line.returnable_base_quantity ?? line.base_quantity) / Number(line.unit_multiplier); }
  const totalMinor = receipt?.lines.reduce((sum, line) => sum + Number(quantities[line.id] || 0) * Number(line.unit_price) * 100, 0) ?? 0;
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const action = (event.nativeEvent as SubmitEvent).submitter?.getAttribute("data-action");
    if (!accessToken || !currentOrganization || !currentLocation || !receipt) return;
    const selected = receipt.lines.filter((line) => isPositiveDecimal(quantities[line.id] ?? ""));
    if (selected.length === 0) { setError("Enter a positive return quantity for at least one item."); return; }
    if (selected.some((line) => Number(quantities[line.id]) > returnable(line))) { setError("Return quantity cannot exceed the quantity still available from the receipt."); return; }
    setSaving(true); setError("");
    try { let created = await api.createSupplierReturn({ supplier_id: supplierId, location_id: currentLocation.id, warehouse_id: receipt.warehouse_id, goods_receipt_id: receipt.id, document_number: documentNumber.trim() || null, returned_at: toApiDate(returnedAt), note: note.trim() || null, lines: selected.map((line) => ({ goods_receipt_line_id: line.id, inventory_item_id: line.inventory_item_id, quantity: quantities[line.id].trim() })) }, currentOrganization.id, accessToken); if (action === "post") created = await api.postSupplierReturn(created.id, currentOrganization.id, accessToken); router.push(`/app/purchasing/returns/${created.id}`); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to save supplier return"); setSaving(false); }
  }
  if (permissionsLoading) return <div className="purchasing-state" aria-live="polite">Checking access…</div>;
  if (!canReturn) return <div className="purchasing-state"><strong>Supplier return access required</strong><span>Your role cannot create supplier returns.</span></div>;
  if (loading) return <div className="purchasing-state" aria-live="polite">Preparing supplier return…</div>;
  return <>
    <Link className="purchasing-back" href="/app/purchasing/returns"><ArrowLeft aria-hidden="true" /> Supplier Returns</Link>
    <header className="purchasing-header"><div><h1>Return to supplier</h1><p>Return goods from an original posted receipt.</p></div></header>
    <form className="operation-form purchasing-operation-form" onSubmit={submit}>
      <div className="operation-form-grid"><label><span>Supplier</span><select value={supplierId} onChange={(event) => { setSupplierId(event.target.value); setReceipts([]); setReceiptId(""); setReceipt(null); setQuantities({}); setLoadingReceipts(Boolean(event.target.value)); }} required><option value="">Select supplier</option>{suppliers.map((supplier) => <option key={supplier.id} value={supplier.id}>{supplier.name}</option>)}</select></label><label><span>Original receipt</span><select value={receiptId} onChange={(event) => { setReceiptId(event.target.value); setReceipt(null); setQuantities({}); setLoadingReceipts(Boolean(event.target.value)); }} disabled={!supplierId || loadingReceipts} required><option value="">{loadingReceipts ? "Loading receipts…" : "Select receipt"}</option>{receipts.map((candidate) => <option key={candidate.id} value={candidate.id}>{candidate.number}</option>)}</select></label><label><span>Warehouse</span><input value={warehouseName} readOnly /></label><label><span>Return date</span><input type="datetime-local" value={returnedAt} onChange={(event) => setReturnedAt(event.target.value)} required /></label><label><span>Supplier document</span><input value={documentNumber} onChange={(event) => setDocumentNumber(event.target.value)} placeholder="Optional" /></label></div>
      {receipt && <fieldset className="supplier-return-lines"><legend>Receipt items</legend><div className="supplier-return-head"><span>Item</span><span>Received</span><span>Already returned</span><span>Return now</span></div>{receipt.lines.map((line) => { const returned = alreadyReturned(line); const available = returnable(line); return <div className="supplier-return-line" key={line.id}><strong>{itemNames.get(line.inventory_item_id) ?? "Inventory item"}</strong><span>{line.received_quantity} {formatPurchaseUnit(line.purchase_unit)}</span><span>{returned} {formatPurchaseUnit(line.purchase_unit)}</span><label><span className="sr-only">Return quantity for {itemNames.get(line.inventory_item_id)}</span><input inputMode="decimal" value={quantities[line.id] ?? ""} onChange={(event) => setQuantities((current) => ({ ...current, [line.id]: event.target.value }))} placeholder="0" aria-describedby={`available-${line.id}`} /><small id={`available-${line.id}`}>{available} available</small></label></div>; })}</fieldset>}
      <div className="operation-estimate"><span>Supplier value</span><strong>{formatMoneyMinor(String(Math.round(totalMinor)), currentOrganization?.currency_code ?? "KZT")}</strong></div>
      <label className="operation-note"><span>Comment</span><textarea value={note} onChange={(event) => setNote(event.target.value)} placeholder="Why are these goods being returned?" /></label>
      {error && <div className="purchase-inline-alert is-error" role="alert">{error}</div>}
      <div className="operation-actions"><button className="secondary-button" type="submit" data-action="draft" disabled={saving || !receipt}>Save draft</button><button className="purchasing-primary" type="submit" data-action="post" disabled={saving || !receipt}>{saving ? "Saving…" : "Post return"}</button></div>
    </form>
  </>;
}
