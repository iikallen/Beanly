import type { ReactNode } from "react";

import type { DashboardMetric } from "@/lib/api";
import { comparisonLabel, comparisonTone } from "@/lib/dashboard";

export function DashboardKpi({
  label,
  value,
  metric,
  icon,
  detail,
  breakdown,
  favorable = "UP",
}: {
  label: string;
  value: string;
  metric?: DashboardMetric<string | number>;
  icon: ReactNode;
  detail?: string;
  breakdown?: string;
  favorable?: "UP" | "DOWN" | "NONE";
}) {
  const tone = metric ? comparisonTone(metric.direction, favorable) : "neutral";
  return (
    <article className="dashboard-kpi">
      <div>
        <span>{label}</span>
        <strong>{value}</strong>
      </div>
      <span className="dashboard-kpi-icon" aria-hidden="true">{icon}</span>
      {breakdown && <span className="dashboard-kpi-breakdown">{breakdown}</span>}
      <small className={`dashboard-comparison is-${tone}`}>
        {metric ? comparisonLabel(metric) : detail}
      </small>
    </article>
  );
}

export function DashboardMetricRail({
  metrics,
}: {
  metrics: Array<{ label: string; value: string; icon: ReactNode }>;
}) {
  return (
    <section className="dashboard-metric-rail" aria-label="Business health">
      {metrics.map((metric) => (
        <article key={metric.label}>
          <div><span>{metric.label}</span><strong>{metric.value}</strong></div>
          <span aria-hidden="true">{metric.icon}</span>
        </article>
      ))}
    </section>
  );
}
