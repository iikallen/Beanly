"use client";

import { Info } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import { AnalyticsHeader } from "@/components/analytics/analytics-controls";
import { useAnalyticsScope } from "@/components/analytics/analytics-provider";
import { AnalyticsAccessState, AnalyticsEmpty, AnalyticsError, AnalyticsLoading } from "@/components/analytics/analytics-state";
import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { useAnalyticsQuery } from "@/hooks/use-analytics-query";
import { api } from "@/lib/api";
import { formatAnalyticsMoney, formatAnalyticsPercent, formatAnalyticsQuantity } from "@/lib/analytics";

export default function AnalyticsInventoryPage() {
  const { accessToken } = useAuth();
  const { currentOrganization } = useWorkspace();
  const scope = useAnalyticsScope();
  const [warehouseSelection, setWarehouseSelection] = useState("");
  const [itemSelection, setItemSelection] = useState("");
  const optionLoader = useCallback(async () => {
    if (!currentOrganization || !accessToken) throw new Error("Authentication required");
    const [warehouses, items] = await Promise.all([api.listInventoryWarehouses(currentOrganization.id, accessToken), api.listInventoryItems(currentOrganization.id, accessToken)]);
    return { warehouses, items };
  }, [accessToken, currentOrganization]);
  const options = useAnalyticsQuery(`${currentOrganization?.id}:inventory-options`, scope.canRead && Boolean(accessToken && currentOrganization), optionLoader);
  const availableWarehouses = useMemo(() => (options.data?.warehouses ?? []).filter((warehouse) => !scope.locationId || warehouse.location_id === scope.locationId), [options.data, scope.locationId]);
  const warehouseId = availableWarehouses.some((warehouse) => warehouse.id === warehouseSelection) ? warehouseSelection : "";
  const inventoryItemId = options.data?.items.some((item) => item.id === itemSelection) ? itemSelection : "";
  const key = `${currentOrganization?.id}:${scope.dateFrom}:${scope.dateTo}:${scope.locationId}:${warehouseId}:${inventoryItemId}`;
  const load = useCallback(async () => {
    if (!currentOrganization || !accessToken) throw new Error("Authentication required");
    return api.getAnalyticsInventoryConsumption(currentOrganization.id, accessToken, { dateFrom: scope.dateFrom, dateTo: scope.dateTo, locationId: scope.locationId || undefined, warehouseId: warehouseId || undefined, inventoryItemId: inventoryItemId || undefined });
  }, [accessToken, currentOrganization, inventoryItemId, scope.dateFrom, scope.dateTo, scope.locationId, warehouseId]);
  const query = useAnalyticsQuery(key, scope.canRead && Boolean(accessToken && currentOrganization), load);
  const data = query.data;

  return <>
    <AnalyticsHeader title="Inventory Consumption" description="Actual ingredient usage and waste from posted inventory movements." dataAsOf={data?.data_as_of}>
      <label><span>Warehouse</span><select value={warehouseId} onChange={(event) => setWarehouseSelection(event.target.value)}><option value="">All warehouses</option>{availableWarehouses.map((warehouse) => <option key={warehouse.id} value={warehouse.id}>{warehouse.name}</option>)}</select></label>
      <label><span>Item</span><select value={inventoryItemId} onChange={(event) => setItemSelection(event.target.value)}><option value="">All items</option>{options.data?.items.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
    </AnalyticsHeader>
    {!scope.canRead ? <AnalyticsAccessState /> : options.error ? <AnalyticsError message={options.error} onRetry={options.retry} /> : query.error ? <AnalyticsError message={query.error} onRetry={query.retry} /> : !data ? <AnalyticsLoading /> : !data.rows.length ? <AnalyticsEmpty message="No inventory consumption or write-offs are available for this period." /> : <section className="analytics-panel analytics-table-panel"><header><div><span>Item-level quantities</span><h2>Consumption &amp; Waste</h2></div><p><Info aria-hidden="true" /> Different units are never combined</p></header><div className="analytics-table-wrap"><table className="analytics-table"><thead><tr><th scope="col">Inventory item</th><th scope="col">Used in sales</th>{scope.canReadFinance && <th scope="col">Sales COGS</th>}<th scope="col">Written off</th>{scope.canReadFinance && <th scope="col">Waste cost</th>}<th scope="col">Waste rate</th><th scope="col">Adjustments</th></tr></thead><tbody>{data.rows.map((row) => <tr key={row.inventory_item_id}><th scope="row">{row.name}</th><td>{formatAnalyticsQuantity(row.sale_quantity, row.base_unit)}</td>{scope.canReadFinance && <td>{formatAnalyticsMoney(row.sale_cost_amount, scope.currency)}</td>}<td>{formatAnalyticsQuantity(row.writeoff_quantity, row.base_unit)}</td>{scope.canReadFinance && <td>{formatAnalyticsMoney(row.writeoff_cost_amount, scope.currency)}</td>}<td>{formatAnalyticsPercent(row.waste_rate_percent)}</td><td>{formatAnalyticsQuantity(row.adjustment_quantity, row.base_unit)}</td></tr>)}</tbody></table></div></section>}
  </>;
}
