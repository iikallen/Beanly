import type { DashboardOverview } from "@/lib/api";
import {
  formatDashboardMoney,
  formatPercent,
  paymentMethodLabel,
} from "@/lib/dashboard";

export function DashboardPaymentMix({
  items,
  currency,
}: {
  items: DashboardOverview["payment_mix"];
  currency: string;
}) {
  return (
    <section className="dashboard-panel dashboard-payment-panel">
      <header><h2>Payment methods</h2></header>
      {items.length === 0 ? (
        <p className="dashboard-panel-empty">No completed sales in this period yet.</p>
      ) : (
        <div className="dashboard-payment-list">
          {items.map((item) => {
            const width = Math.min(100, Math.max(0, Number(item.share_percent)));
            return (
              <div key={item.method}>
                <span>{paymentMethodLabel(item.method)}</span>
                <span className="dashboard-payment-track" aria-hidden="true"><i style={{ width: `${width}%` }} /></span>
                <strong>{formatPercent(item.share_percent)}</strong>
                <small>{formatDashboardMoney(item.amount, currency)}</small>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
