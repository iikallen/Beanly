"use client";

import { ArrowDown, Info } from "lucide-react";
import { useCallback, useState } from "react";

import { AnalyticsHeader } from "@/components/analytics/analytics-controls";
import { useAnalyticsScope } from "@/components/analytics/analytics-provider";
import { AnalyticsAccessState, AnalyticsEmpty, AnalyticsError, AnalyticsLoading } from "@/components/analytics/analytics-state";
import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-provider";
import { useAnalyticsQuery } from "@/hooks/use-analytics-query";
import { api, type AnalyticsAbc, type AnalyticsGroupBy, type AnalyticsProductSort, type AnalyticsProducts } from "@/lib/api";
import { compareAnalyticsDecimal, formatAnalyticsInteger, formatAnalyticsMoney, formatAnalyticsPercent } from "@/lib/analytics";

type ProductsBundle = { products: AnalyticsProducts; abc: AnalyticsAbc };
type ProductTableSort = "NAME" | "QUANTITY" | "REVENUE" | "COGS" | "GROSS_PROFIT" | "MARGIN" | "ORDERS";

export default function AnalyticsProductsPage() {
  const { accessToken } = useAuth();
  const { currentOrganization } = useWorkspace();
  const scope = useAnalyticsScope();
  const [groupBy, setGroupBy] = useState<AnalyticsGroupBy>("PRODUCT");
  const [sortBy, setSortBy] = useState<ProductTableSort>("REVENUE");
  const [sortDirection, setSortDirection] = useState<"ascending" | "descending">("descending");
  const tableSort = !scope.canReadFinance && ["COGS", "GROSS_PROFIT", "MARGIN"].includes(sortBy) ? "REVENUE" : sortBy;
  const effectiveServerSort: AnalyticsProductSort = tableSort === "QUANTITY" || tableSort === "GROSS_PROFIT" ? tableSort : "REVENUE";
  const key = `${currentOrganization?.id}:${scope.dateFrom}:${scope.dateTo}:${scope.locationId}:${groupBy}:${effectiveServerSort}`;
  const load = useCallback(async (): Promise<ProductsBundle> => {
    if (!currentOrganization || !accessToken) throw new Error("Authentication required");
    const filters = { dateFrom: scope.dateFrom, dateTo: scope.dateTo, locationId: scope.locationId || undefined };
    const [products, abc] = await Promise.all([
      api.getAnalyticsProducts(currentOrganization.id, accessToken, { ...filters, groupBy, sortBy: effectiveServerSort, limit: "100" }),
      api.getAnalyticsAbc(currentOrganization.id, accessToken, filters),
    ]);
    return { products, abc };
  }, [accessToken, currentOrganization, effectiveServerSort, groupBy, scope.dateFrom, scope.dateTo, scope.locationId]);
  const query = useAnalyticsQuery(key, scope.canRead && Boolean(accessToken && currentOrganization), load);
  const data = query.data;
  const hasRefundMetrics = data?.products.rows.some((row) => row.net_revenue !== undefined) ?? false;
  const rows = data ? [...data.products.rows].sort((left, right) => {
    const compared = tableSort === "NAME" ? left.name.localeCompare(right.name)
      : tableSort === "QUANTITY" ? left.quantity_sold - right.quantity_sold
        : tableSort === "REVENUE" ? compareAnalyticsDecimal(left.net_revenue ?? left.revenue, right.net_revenue ?? right.revenue)
          : tableSort === "COGS" ? compareAnalyticsDecimal(left.cogs, right.cogs)
            : tableSort === "GROSS_PROFIT" ? compareAnalyticsDecimal(left.gross_profit, right.gross_profit)
              : tableSort === "MARGIN" ? compareAnalyticsDecimal(left.gross_margin_percent, right.gross_margin_percent)
                : left.orders - right.orders;
    return sortDirection === "ascending" ? compared : -compared;
  }) : [];
  const chooseSort = (next: ProductTableSort) => {
    if (next === sortBy) setSortDirection((current) => current === "ascending" ? "descending" : "ascending");
    else { setSortBy(next); setSortDirection(next === "NAME" ? "ascending" : "descending"); }
  };

  return <>
    <AnalyticsHeader title="Products" description="Product and variant performance across the selected period." dataAsOf={data?.products.data_as_of}>
      <label><span>Group by</span><select value={groupBy} onChange={(event) => setGroupBy(event.target.value as AnalyticsGroupBy)}><option value="PRODUCT">Product</option><option value="VARIANT">Variant</option></select></label>
    </AnalyticsHeader>
    {!scope.canRead ? <AnalyticsAccessState /> : query.error ? <AnalyticsError message={query.error} onRetry={query.retry} /> : !data ? <AnalyticsLoading /> : !data.products.rows.length ? <AnalyticsEmpty message="No product sales are available for this period." /> : <>
      <section className="analytics-panel analytics-table-panel">
        <header><div><span>{data.products.group_by === "PRODUCT" ? "Grouped products" : "Product variants"}</span><h2>Sales performance</h2></div><p><Info aria-hidden="true" /> Click a metric heading to sort</p></header>
        <div className="analytics-table-wrap"><table className="analytics-table"><thead><tr><SortableHeading label="Product" active={tableSort === "NAME"} direction={sortDirection} onClick={() => chooseSort("NAME")} /><SortableHeading label={hasRefundMetrics ? "Net qty" : "Qty"} active={tableSort === "QUANTITY"} direction={sortDirection} onClick={() => chooseSort("QUANTITY")} /><SortableHeading label={hasRefundMetrics ? "Net revenue" : "Revenue"} active={tableSort === "REVENUE"} direction={sortDirection} onClick={() => chooseSort("REVENUE")} />{scope.canReadFinance && <><SortableHeading label="COGS" active={tableSort === "COGS"} direction={sortDirection} onClick={() => chooseSort("COGS")} /><SortableHeading label="Profit" active={tableSort === "GROSS_PROFIT"} direction={sortDirection} onClick={() => chooseSort("GROSS_PROFIT")} /><SortableHeading label="Margin" active={tableSort === "MARGIN"} direction={sortDirection} onClick={() => chooseSort("MARGIN")} /></>}<SortableHeading label="Orders" active={tableSort === "ORDERS"} direction={sortDirection} onClick={() => chooseSort("ORDERS")} /></tr></thead><tbody>{rows.map((row) => <tr key={row.product_variant_id ?? row.product_id}><th scope="row"><strong>{row.name}</strong>{row.variant_name && <small>{row.variant_name}</small>}</th><td>{formatAnalyticsInteger(row.quantity_sold - (row.refunded_quantity ?? 0))}{row.refunded_quantity !== undefined && <small>{formatAnalyticsInteger(row.quantity_sold)} sold · {formatAnalyticsInteger(row.refunded_quantity)} refunded</small>}</td><td>{formatAnalyticsMoney(row.net_revenue ?? row.revenue, scope.currency)}{row.gross_revenue !== undefined && row.refund_amount !== undefined && <small>Gross {formatAnalyticsMoney(row.gross_revenue, scope.currency)} · Refunds −{formatAnalyticsMoney(row.refund_amount, scope.currency)}</small>}</td>{scope.canReadFinance && <><td>{formatAnalyticsMoney(row.cogs, scope.currency)}</td><td>{formatAnalyticsMoney(row.gross_profit, scope.currency)}</td><td>{formatAnalyticsPercent(row.gross_margin_percent)}</td></>}<td>{formatAnalyticsInteger(row.orders)}{row.refund_orders !== undefined && row.refund_orders > 0 && <small>{formatAnalyticsInteger(row.refund_orders)} refund orders</small>}</td></tr>)}</tbody></table></div>
      </section>
      {groupBy === "PRODUCT" && <section className="analytics-panel analytics-abc-panel"><header><div><span>Revenue concentration</span><h2>ABC Analysis</h2></div><p>A ≤ {data.abc.thresholds.a_max_cumulative_share}% · B ≤ {data.abc.thresholds.b_max_cumulative_share}%</p></header><div className="analytics-abc-list">{data.abc.rows.map((row) => <article key={row.product_id}><span className={`analytics-class class-${row.abc_class.toLowerCase()}`}>{row.abc_class}</span><strong>{row.name}</strong><span>{formatAnalyticsMoney(row.revenue, scope.currency)}</span><small>{formatAnalyticsPercent(row.revenue_share_percent)} share · {formatAnalyticsPercent(row.cumulative_share_percent)} cumulative</small></article>)}</div></section>}
    </>}
  </>;
}

function SortableHeading({ label, active, direction, onClick }: { label: string; active: boolean; direction: "ascending" | "descending"; onClick: () => void }) {
  return <th scope="col" aria-sort={active ? direction : "none"}><button type="button" className={active ? "is-active" : ""} onClick={onClick}>{label}<ArrowDown className={active && direction === "ascending" ? "is-ascending" : ""} aria-hidden="true" /></button></th>;
}
