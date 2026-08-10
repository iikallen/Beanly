import { AlertCircle, ArrowRight, Info, TriangleAlert } from "lucide-react";
import Link from "next/link";

import type { DashboardAlert } from "@/lib/api";

const actionLabels: Record<string, string> = {
  NEGATIVE_STOCK: "View inventory",
  INCOMPLETE_COGS: "Review items",
  INVENTORY_COUNT_IN_PROGRESS: "View progress",
};

export function DashboardAlerts({ alerts }: { alerts: DashboardAlert[] }) {
  return (
    <section className="dashboard-panel dashboard-alerts-panel">
      <header><h2>Needs attention</h2><span>{alerts.length || "All clear"}</span></header>
      {alerts.length === 0 ? (
        <p className="dashboard-panel-empty">Nothing needs attention right now.</p>
      ) : (
        <div className="dashboard-alert-list">
          {alerts.map((alert, index) => {
            const Icon = alert.severity === "CRITICAL" ? AlertCircle : alert.severity === "WARNING" ? TriangleAlert : Info;
            return (
              <article key={`${alert.code}-${alert.entity_id ?? alert.location_id ?? index}`} className={`is-${alert.severity.toLowerCase()}`}>
                <span className="dashboard-alert-icon"><Icon aria-hidden="true" /></span>
                <div><strong>{alert.title}</strong><p>{alert.message}</p></div>
                {alert.action_href && (
                  <Link href={alert.action_href}>{actionLabels[alert.code] ?? "View details"}<ArrowRight aria-hidden="true" /></Link>
                )}
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
