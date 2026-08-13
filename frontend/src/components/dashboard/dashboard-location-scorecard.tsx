import type { DashboardOverview } from "@/lib/api";
import { formatDashboardMinor, formatDashboardMoney } from "@/lib/dashboard";

export function DashboardLocationScorecard({
  locations,
  currency,
}: {
  locations: DashboardOverview["locations"];
  currency: string;
}) {
  const showProfit = locations.some((location) => location.operating_profit !== null);
  const hasRefundMetrics = locations.some((location) => location.net_sales_minor !== undefined);
  return (
    <section className="dashboard-panel dashboard-locations-panel">
      <header><h2>Locations</h2></header>
      {locations.length === 0 ? (
        <p className="dashboard-panel-empty">No location results in this period.</p>
      ) : (
        <div className="dashboard-table-wrap">
          <table>
            <thead><tr><th>Location</th><th>{hasRefundMetrics ? "Net sales" : "Revenue"}</th><th>Orders</th><th>Avg check</th>{showProfit && <th>Operating profit</th>}</tr></thead>
            <tbody>
              {locations.map((location) => (
                <tr key={location.location_id}>
                  <th scope="row">{location.location_name}</th>
                  <td>{location.net_sales_minor !== undefined ? formatDashboardMinor(location.net_sales_minor, currency) : formatDashboardMoney(location.revenue, currency)}{location.gross_sales_minor !== undefined && location.refund_amount_minor !== undefined && <small>Gross {formatDashboardMinor(location.gross_sales_minor, currency)} · Discounts −{formatDashboardMinor(location.discount_amount_minor, currency)} · Refunds −{formatDashboardMinor(location.refund_amount_minor, currency)}</small>}</td>
                  <td>{new Intl.NumberFormat().format(location.paid_orders)}</td>
                  <td>{formatDashboardMoney(location.average_check, currency)}</td>
                  {showProfit && <td>{location.operating_profit === null ? "—" : formatDashboardMoney(location.operating_profit, currency)}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
