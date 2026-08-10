"use client";

import { Plus } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { OperationDocumentList } from "@/components/operation-document-list";
import { useWorkspace } from "@/components/workspace-provider";
import { useInventoryPermissions } from "@/hooks/use-inventory-permissions";
import { api, type InventoryCount } from "@/lib/api";

export default function InventoryCountsPage() {
  const { accessToken } = useAuth();
  const { currentOrganization, currentLocation } = useWorkspace();
  const { canCount, canRead, loading: permissionsLoading } = useInventoryPermissions();
  const [rows, setRows] = useState<InventoryCount[]>([]);
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    let cancelled = false;
    if (!accessToken || !currentOrganization || !currentLocation || permissionsLoading) return;
    if (!canRead) return;
    api.listInventoryCounts(currentOrganization.id, accessToken, { locationId: currentLocation.id, status: status || undefined })
      .then((next) => { if (!cancelled) setRows(next.filter((row) => row.location_id === currentLocation.id && (!status || row.status === status))); })
      .catch((caught) => { if (!cancelled) setError(caught instanceof Error ? caught.message : "Unable to load counts"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [accessToken, canRead, currentLocation, currentOrganization, permissionsLoading, status]);
  return <>
    <header className="inventory-header"><div><h1>Inventory Counts</h1><p>Compare physical stock with Beanly.</p></div>{canCount && <Link className="inventory-adjust-button" href="/app/inventory/counts/new"><Plus aria-hidden="true" /> New count</Link>}</header>
    <div className="operation-filters compact"><label><span>Status</span><select value={status} onChange={(event) => setStatus(event.target.value)}><option value="">All statuses</option><option value="COUNTING">Counting</option><option value="POSTED">Posted</option><option value="CANCELLED">Cancelled</option></select></label></div>
    {!permissionsLoading && !canRead ? <div className="inventory-state"><strong>Inventory access required</strong><span>Your role cannot view inventory counts.</span></div> : <OperationDocumentList rows={rows.map((row) => ({ id: row.id, number: row.number, description: `${row.type.toLowerCase()} count`, status: row.status, date: row.snapshot_at }))} basePath="/app/inventory/counts" loading={loading} error={error} emptyTitle="No inventory counts found" emptyMessage="Start a full count or count selected items." />}
  </>;
}
