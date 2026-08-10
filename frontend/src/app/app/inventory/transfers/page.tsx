"use client";

import { Plus } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { OperationDocumentList } from "@/components/operation-document-list";
import { useWorkspace } from "@/components/workspace-provider";
import { useInventoryPermissions } from "@/hooks/use-inventory-permissions";
import { api, type InventoryTransfer, type WarehouseResponse } from "@/lib/api";

export default function TransfersPage() {
  const { accessToken } = useAuth();
  const { currentOrganization } = useWorkspace();
  const { canRead, canTransfer, loading: permissionsLoading } = useInventoryPermissions();
  const [rows, setRows] = useState<InventoryTransfer[]>([]);
  const [warehouses, setWarehouses] = useState<WarehouseResponse[]>([]);
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    let cancelled = false;
    if (!accessToken || !currentOrganization || permissionsLoading) return;
    if (!canRead) return;
    Promise.all([api.listInventoryTransfers(currentOrganization.id, accessToken, { status: status || undefined }), api.listInventoryWarehouses(currentOrganization.id, accessToken)])
      .then(([nextRows, nextWarehouses]) => { if (!cancelled) { setRows(nextRows.filter((row) => !status || row.status === status)); setWarehouses(nextWarehouses); } })
      .catch((caught) => { if (!cancelled) setError(caught instanceof Error ? caught.message : "Unable to load transfers"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [accessToken, canRead, currentOrganization, permissionsLoading, status]);
  const names = useMemo(() => new Map(warehouses.map((warehouse) => [warehouse.id, warehouse.name])), [warehouses]);
  return <>
    <header className="inventory-header"><div><h1>Transfers</h1><p>Move stock between warehouses atomically.</p></div>{canTransfer && <Link className="inventory-adjust-button" href="/app/inventory/transfers/new"><Plus aria-hidden="true" /> New transfer</Link>}</header>
    <div className="operation-filters compact"><label><span>Status</span><select value={status} onChange={(event) => setStatus(event.target.value)}><option value="">All statuses</option><option value="DRAFT">Draft</option><option value="POSTED">Posted</option><option value="REVERSED">Reversed</option></select></label></div>
    {!permissionsLoading && !canRead ? <div className="inventory-state"><strong>Inventory access required</strong><span>Your role cannot view transfers.</span></div> : <OperationDocumentList rows={rows.map((row) => ({ id: row.id, number: row.number, description: `${names.get(row.source_warehouse_id) ?? "Warehouse"} → ${names.get(row.destination_warehouse_id) ?? "Warehouse"}`, status: row.status, date: row.occurred_at }))} basePath="/app/inventory/transfers" loading={loading} error={error} emptyTitle="No transfers found" emptyMessage="Create a transfer to move stock between warehouses." />}
  </>;
}
