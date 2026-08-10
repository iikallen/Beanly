import type { DashboardOverview } from "@/lib/api";
import { formatDashboardMoney } from "@/lib/dashboard";

export function DashboardLocationScorecard({
  locations,
  currency,
}: {
  locations: DashboardOverview["locations"];
  currency: string;
}) {
  const showProfit = locations.some((location) => location.operating_profit !== null);
  return (
    <section className="dashboard-panel dashboard-locations-panel">
      <header><h2>Locations</h2></header>
      {locations.length === 0 ? (
        <p className="dashboard-panel-empty">No location results in this period.</p>
      ) : (
        <div className="dashboard-table-wrap">
          <table>
            <thead><tr><th>Location</th><th>Revenue</th><th>Orders</th><th>Avg check</th>{showProfit && <th>Operating profit</th>}</tr></thead>
            <tbody>
              {locations.map((location) => (
                <tr key={location.location_id}>
                  <th scope="row">{location.location_name}</th>
                  <td>{formatDashboardMoney(location.revenue, currency)}</td>
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
