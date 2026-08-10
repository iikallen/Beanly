"use client";

import { Plus } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { OperationDocumentList } from "@/components/operation-document-list";
import { useWorkspace } from "@/components/workspace-provider";
import { useInventoryPermissions } from "@/hooks/use-inventory-permissions";
import { api, type InventoryWriteOff } from "@/lib/api";

export default function WriteOffsPage() {
  const { accessToken } = useAuth();
  const { currentOrganization, currentLocation } = useWorkspace();
  const { canRead, canWriteOff, loading: permissionsLoading } = useInventoryPermissions();
  const [rows, setRows] = useState<InventoryWriteOff[]>([]);
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    if (!accessToken || !currentOrganization || !currentLocation || permissionsLoading) return;
    if (!canRead) return;
    api.listWriteOffs(currentOrganization.id, accessToken, { locationId: currentLocation.id, status: status || undefined })
      .then((next) => { if (!cancelled) setRows(next.filter((row) => row.location_id === currentLocation.id && (!status || row.status === status))); })
      .catch((caught) => { if (!cancelled) setError(caught instanceof Error ? caught.message : "Unable to load write-offs"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [accessToken, canRead, currentLocation, currentOrganization, permissionsLoading, status]);

  return <>
    <header className="inventory-header"><div><h1>Write-offs</h1><p>Track spoiled, damaged, or consumed stock.</p></div>{canWriteOff && <Link className="inventory-adjust-button" href="/app/inventory/write-offs/new"><Plus aria-hidden="true" /> New write-off</Link>}</header>
    <div className="operation-filters compact"><label><span>Status</span><select value={status} onChange={(event) => setStatus(event.target.value)}><option value="">All statuses</option><option value="DRAFT">Draft</option><option value="POSTED">Posted</option><option value="REVERSED">Reversed</option></select></label></div>
    {!permissionsLoading && !canRead ? <div className="inventory-state"><strong>Inventory access required</strong><span>Your role cannot view write-offs.</span></div> : <OperationDocumentList rows={rows.map((row) => ({ id: row.id, number: row.number, description: row.reason_name ?? "Write-off", status: row.status, date: row.occurred_at }))} basePath="/app/inventory/write-offs" loading={loading} error={error} emptyTitle="No write-offs found" emptyMessage="Create a write-off when stock is spoiled, damaged, or consumed." />}
  </>;
}
